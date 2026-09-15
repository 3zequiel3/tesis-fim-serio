"""
Static lint of `n8n/workflows/*.json` (D44/RN-138, change 52, task 7.5).

Checks structural properties that `test_n8n_workflow_contract.py` does not:
node/expression hygiene, workflow identity, and wiring — not payload field
names.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / "n8n" / "workflows"

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _workflow_files() -> list[Path]:
    return sorted(WORKFLOWS_DIR.glob("*.json"))


def _load_all() -> dict[str, dict]:
    return {p.name: json.loads(p.read_text(encoding="utf-8")) for p in _workflow_files()}


def _webhook_nodes(workflow: dict) -> list[dict]:
    return [n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.webhook"]


def _switch_nodes(workflow: dict) -> list[dict]:
    return [n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.switch"]


def _execute_workflow_nodes(workflow: dict) -> list[dict]:
    return [n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.executeWorkflow"]


def test_exactly_one_webhook_with_fim_alert_path() -> None:
    workflows = _load_all()
    webhook_hits: list[tuple[str, dict]] = []
    for name, wf in workflows.items():
        for node in _webhook_nodes(wf):
            webhook_hits.append((name, node))

    assert len(webhook_hits) == 1, (
        f"expected exactly one webhook node across n8n/workflows/, found {len(webhook_hits)}: "
        f"{[name for name, _ in webhook_hits]}"
    )
    name, node = webhook_hits[0]
    assert node["parameters"]["path"] == "fim-alert"
    assert node["parameters"]["httpMethod"] == "POST"
    assert node["parameters"]["responseMode"] == "responseNode", (
        "responseMode must be responseNode — onReceived would ack the backend "
        "before any channel confirms delivery (RN-53)"
    )


def test_workflow_ids_are_stable_uuids_and_unique() -> None:
    workflows = _load_all()
    ids = {}
    for name, wf in workflows.items():
        wf_id = wf.get("id")
        assert wf_id, f"{name} has no top-level id"
        assert _UUID_RE.match(wf_id), f"{name}'s id {wf_id!r} is not a UUID"
        assert wf_id not in ids, f"duplicate id {wf_id!r}: {ids[wf_id]} and {name}"
        ids[wf_id] = name


def test_no_meta_key() -> None:
    workflows = _load_all()
    offenders = [name for name, wf in workflows.items() if "__meta" in wf]
    assert not offenders, f"non-standard __meta key present in: {offenders}"


def test_node_ids_are_uuids() -> None:
    workflows = _load_all()
    for name, wf in workflows.items():
        for node in wf["nodes"]:
            node_id = node.get("id")
            assert node_id, f"{name}: node {node.get('name')!r} has no id"
            # n8n accepts short numeric-looking ids historically, but every
            # node this change writes must use a real UUID (change 47's
            # divergence used numeric ids "1", "2", ...).
            try:
                uuid.UUID(str(node_id))
            except ValueError:
                raise AssertionError(
                    f"{name}: node {node.get('name')!r} has a non-UUID id {node_id!r}"
                ) from None


def test_no_jinja_filters_or_credential_expressions() -> None:
    for path in _workflow_files():
        raw = path.read_text(encoding="utf-8")
        assert "| upper" not in raw, f"{path.name} uses a Jinja-style filter (invalid n8n JS expression)"
        assert "$credentials." not in raw, (
            f"{path.name} references $credentials in an expression — declare the "
            "credential in the node's own `credentials` block instead"
        )


def test_email_slack_jira_linear_nodes_declare_credentials() -> None:
    workflows = _load_all()
    checked = 0
    for name, wf in workflows.items():
        for node in wf["nodes"]:
            node_type = node["type"]
            is_email = node_type == "n8n-nodes-base.emailSend"
            is_http_with_cred = node_type == "n8n-nodes-base.httpRequest" and node.get(
                "parameters", {}
            ).get("authentication") in ("predefinedCredentialType", "genericCredentialType")
            if not (is_email or is_http_with_cred):
                continue
            checked += 1
            creds = node.get("credentials")
            assert creds, f"{name}: node {node['name']!r} ({node_type}) has no credentials block"
    assert checked >= 4, (
        f"expected at least 4 credentialed nodes (email, slack, jira, linear), found {checked}"
    )


def test_switch_nodes_use_v3_with_number_outputs() -> None:
    workflows = _load_all()
    found_switch = False
    for name, wf in workflows.items():
        for node in _switch_nodes(wf):
            found_switch = True
            assert node["typeVersion"] >= 3, f"{name}: Switch {node['name']!r} is not typeVersion 3+"
            params = node["parameters"]
            assert params.get("mode") == "expression", (
                f"{name}: Switch {node['name']!r} must use mode=expression with numberOutputs "
                "(rules mode does not declare numberOutputs)"
            )
            assert isinstance(params.get("numberOutputs"), int) and params["numberOutputs"] >= 1
            # Connections for this node must be indexed 0..numberOutputs-1.
            conns = wf["connections"].get(node["name"], {}).get("main", [])
            assert len(conns) == params["numberOutputs"], (
                f"{name}: Switch {node['name']!r} declares {params['numberOutputs']} outputs "
                f"but has {len(conns)} connection groups"
            )
    assert found_switch, "expected at least one Switch node (the router's type discriminator)"


def test_execute_workflow_references_resolve_to_a_present_subflow() -> None:
    workflows = _load_all()
    known_ids = {wf["id"] for wf in workflows.values()}
    referencing_files = 0
    for name, wf in workflows.items():
        for node in _execute_workflow_nodes(wf):
            referencing_files += 1
            target_id = node["parameters"].get("workflowId")
            assert target_id in known_ids, (
                f"{name}: Execute Workflow node {node['name']!r} references "
                f"unknown workflow id {target_id!r}"
            )
    assert referencing_files > 0, "expected at least one Execute Workflow node in the router"


def test_email_send_parameters_match_email_format() -> None:
    """14.7: `emailSend` v2.1 reads the body from parameters named after
    `emailFormat` — `html` for 'html', `text` for 'text', both for 'both' —
    never from a `message` parameter (n8n-nodes-base's send.operation.js,
    verified against n8nio/n8n:2.17.8)."""
    workflows = _load_all()
    checked = 0
    for wf_name, wf in workflows.items():
        for node in wf["nodes"]:
            if node["type"] != "n8n-nodes-base.emailSend":
                continue
            checked += 1
            params = node["parameters"]
            assert "message" not in params, (
                f"{wf_name}: emailSend node {node['name']!r} uses the parameter "
                "'message', which emailSend v2.1 never reads — use 'html'/'text' "
                "depending on emailFormat"
            )
            email_format = params.get("emailFormat")
            assert email_format in ("html", "text", "both"), (
                f"{wf_name}: emailSend node {node['name']!r} has an unexpected "
                f"emailFormat {email_format!r}"
            )
            if email_format in ("html", "both"):
                assert params.get("html"), (
                    f"{wf_name}: emailSend node {node['name']!r} has emailFormat="
                    f"{email_format!r} but no non-empty 'html' parameter"
                )
            if email_format in ("text", "both"):
                assert params.get("text"), (
                    f"{wf_name}: emailSend node {node['name']!r} has emailFormat="
                    f"{email_format!r} but no non-empty 'text' parameter"
                )
    assert checked >= 1, "expected at least one emailSend node"


def test_email_send_attribution_explicitly_disabled() -> None:
    """14.7: `options.appendAttribution` SHALL be explicitly `false` —
    emailSend v2.1 defaults it to `true` (appending "This email was sent
    automatically with n8n") unless the workflow sets it."""
    workflows = _load_all()
    checked = 0
    for wf_name, wf in workflows.items():
        for node in wf["nodes"]:
            if node["type"] != "n8n-nodes-base.emailSend":
                continue
            checked += 1
            options = node["parameters"].get("options", {})
            assert options.get("appendAttribution") is False, (
                f"{wf_name}: emailSend node {node['name']!r} must set "
                "options.appendAttribution to false"
            )
    assert checked >= 1, "expected at least one emailSend node"


def test_no_on_received_response_mode() -> None:
    for path in _workflow_files():
        raw = path.read_text(encoding="utf-8")
        assert '"responseMode": "onReceived"' not in raw, (
            f"{path.name} uses responseMode=onReceived — the router must wait for "
            "channel results before responding (RN-53)"
        )
