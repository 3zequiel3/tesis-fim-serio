from __future__ import annotations

import argparse
import asyncio
import datetime
import os
import platform
import signal
import sys
from pathlib import Path

import httpx
import structlog
import valkey.asyncio as avalkey

import agent.bootstrap as bootstrap
from agent.baseline import BaselineEngine, load_master_secret
from agent.config import AgentConfig, load_config
from agent.decision import DecisionEngine
from agent.heartbeat import HeartbeatPublisher
from agent.journal import JournalManager
from agent.logging import configure_logging
from agent.publisher import Publisher
from agent.queue import EventQueue
from agent.rules import RulesCache
from agent.state import load_state
from agent.streams import load_shared_secret
from agent.transport import create_valkey_client

_LINUX = platform.system() == "Linux"

log = structlog.get_logger()


_CERT_RENEWAL_DAYS_THRESHOLD = 15
_ATOMIC_CERT_SUFFIX = ".fim_cert_tmp"


async def _cert_renewal_loop(cfg: AgentConfig, stop_event: asyncio.Event) -> None:
    """
    Verifica periódicamente el certificado mTLS y lo renueva si vence en ≤ 15 días (G3/RN-111).

    Loop: duerme cert_renewal_check_interval_h horas (interruptible por stop_event),
    luego verifica not_valid_after_utc. Si el margen es ≤ 15 días, llama POST /agents/renew
    con el cert/key actuales como client cert + CA para autenticación mTLS.

    Cualquier error → log.warning + continuar. Nunca interrumpe la operación del agente.
    """
    from cryptography import x509 as _x509

    certs_dir = Path(cfg.storage.certs_dir)
    cert_path = certs_dir / "agent-cert.pem"
    key_path = certs_dir / "agent-key.pem"
    ca_path = certs_dir / "ca.pem"
    interval_s = cfg.cert_renewal_check_interval_h * 3600

    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
        except asyncio.TimeoutError:
            pass

        if stop_event.is_set():
            break

        try:
            cert_pem = cert_path.read_bytes()
            cert = _x509.load_pem_x509_certificate(cert_pem)
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            days_left = (cert.not_valid_after_utc - now_utc).days

            if days_left > _CERT_RENEWAL_DAYS_THRESHOLD:
                log.debug(
                    "cert_renewal.skipped",
                    days_left=days_left,
                    threshold=_CERT_RENEWAL_DAYS_THRESHOLD,
                )
                continue

            log.info("cert_renewal.triggering", days_left=days_left)
            url = cfg.backend_url.rstrip("/") + "/agents/renew"

            async with httpx.AsyncClient(
                cert=(str(cert_path), str(key_path)),
                verify=str(ca_path),
                timeout=30.0,
            ) as client:
                resp = await client.post(url, json={"agent_id": cfg.agent_id})

            if resp.status_code != 200:
                log.warning(
                    "cert_renewal.backend_error",
                    status=resp.status_code,
                    body=resp.text[:256],
                )
                continue

            data = resp.json()
            new_cert_pem: str = data["cert_pem"]
            ca_cert_pem: str = data.get("ca_cert_pem", ca_path.read_text())

            bootstrap.verify_cert(new_cert_pem, ca_cert_pem, cfg.agent_id)

            tmp_path = Path(str(cert_path) + _ATOMIC_CERT_SUFFIX)
            fd = os.open(str(tmp_path), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(new_cert_pem.encode())
                    f.flush()
                    os.fsync(f.fileno())
            except Exception:
                try:
                    os.unlink(str(tmp_path))
                except OSError:
                    pass
                raise
            os.replace(str(tmp_path), str(cert_path))
            os.chmod(str(cert_path), 0o600)

            log.info("cert_renewal.complete", agent_id=cfg.agent_id)

        except Exception as exc:
            log.warning("cert_renewal.error", error=str(exc))


async def _drain_then_stop(
    queue: EventQueue,
    stop_event: asyncio.Event,
    timeout: float = 30.0,
) -> None:
    """Espera hasta que la cola offline drene o se cumpla el timeout, luego señala stop."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if queue.queue_size == 0:
            break
        await asyncio.sleep(0.5)
    stop_event.set()


async def main(config_path: Path, log_level: str, log_format: str) -> None:
    configure_logging(level=log_level, fmt=log_format)

    cfg = load_config(config_path)

    certs_dir = Path(cfg.storage.certs_dir)
    if not bootstrap.is_bootstrapped(certs_dir):
        secret = os.environ.get("FIM_BOOTSTRAP_SECRET")
        if not secret:
            log.error("agent.bootstrap.missing_secret")
            print("FIM_BOOTSTRAP_SECRET env var is required for initial bootstrap", file=sys.stderr)
            sys.exit(1)
        bootstrap.run(cfg, secret)

    state_path = Path(cfg.storage.baseline_dir).parent / "state.json"
    state = load_state(state_path)

    # RulesCache se auto-carga desde state.json (clave "rules")
    rules_cache = RulesCache(state_path)

    try:
        shared_secret = load_shared_secret(cfg.storage.secrets_dir)
    except FileNotFoundError as exc:
        log.error("agent.startup.missing_shared_secret", error=str(exc))
        print(f"shared_secret not found — run bootstrap first: {exc}", file=sys.stderr)
        sys.exit(1)

    master_secret = load_master_secret(cfg.storage.secrets_dir)
    engine = BaselineEngine(cfg, master_secret)
    report = engine.init_scan(cfg.watch_paths)
    log.info(
        "baseline.init_scan.complete",
        scanned=report.scanned,
        skipped=report.skipped,
        oversize=report.oversize,
        errors=report.errors,
    )

    log.info(
        "agent started",
        agent_id=cfg.agent_id,
        ruleset_version=state.ruleset_version,
    )

    stop_event = asyncio.Event()
    shutdown_flag = asyncio.Event()
    loop = asyncio.get_running_loop()
    _drain_task: asyncio.Task | None = None

    def _shutdown(sig_name: str) -> None:
        log.info("shutting down", signal=sig_name)
        publisher.set_shutdown(True)
        shutdown_flag.set()
        nonlocal _drain_task
        # Drena la cola y luego activa stop_event (RN-93)
        _drain_task = loop.create_task(_drain_then_stop(queue, stop_event))

    loop.add_signal_handler(signal.SIGTERM, lambda: _shutdown("SIGTERM"))
    loop.add_signal_handler(signal.SIGINT, lambda: _shutdown("SIGINT"))

    valkey_client: avalkey.Valkey = create_valkey_client(cfg)

    queue = EventQueue(cfg.storage.queue_dir)
    publisher = Publisher(cfg, queue, valkey_client)
    heartbeat = HeartbeatPublisher(cfg, queue, state, valkey_client, publisher=publisher)

    quarantine_dir = Path(cfg.storage.journal_dir).parent / "quarantine"
    journal = JournalManager(cfg.storage.journal_dir, shared_secret)
    decision_engine = DecisionEngine(
        rules=rules_cache,
        journal=journal,
        baseline=engine,
        quarantine_dir=quarantine_dir,
    )

    coroutines = [
        publisher.run(stop_event),
        heartbeat.run(stop_event, shutdown_flag),
    ]

    # Renovación proactiva de certificado: solo si ya está bootstrapped (G3/RN-111)
    if bootstrap.is_bootstrapped(Path(cfg.storage.certs_dir)):
        coroutines.append(_cert_renewal_loop(cfg, stop_event))

    if _LINUX:
        from agent.detector import FanotifyDetector

        # Rehidratación del journal antes de arrancar el detector (RN-83)
        await decision_engine.rehydrate(publisher)

        detector = FanotifyDetector(
            agent_id=cfg.agent_id,
            watch_paths=cfg.watch_paths,
            baseline=engine,
            publisher=publisher,
            stop_event=stop_event,
            decision_engine=decision_engine,
        )

        def _on_rule_sync(rules_payload: list, ruleset_version: int) -> None:
            rules_cache.update(rules_payload, ruleset_version, state)

        publisher.register_callbacks(
            on_ack=detector.on_ack,
            on_update_config=detector.reload_paths,
            on_rule_sync=_on_rule_sync,
        )
        publisher.register_command_handlers(
            baseline_engine=engine,
            state=state,
            journal=journal,
            quarantine_dir=str(quarantine_dir),
            detector=detector,
        )
        coroutines.append(detector.start())
    else:
        log.warning("agent.detector.skipped", reason="fanotify only available on Linux")

    try:
        await asyncio.gather(*coroutines)
    finally:
        await valkey_client.aclose()
        sys.exit(0)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FIM Agent — File Integrity Monitor")
    parser.add_argument(
        "--config",
        default="/etc/fim-agent/config.yaml",
        metavar="PATH",
        help="Path to config.yaml (default: /etc/fim-agent/config.yaml)",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
        dest="log_level",
    )
    parser.add_argument(
        "--log-format",
        default="json",
        choices=["json", "console"],
        dest="log_format",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        asyncio.run(
            main(
                config_path=Path(args.config),
                log_level=args.log_level,
                log_format=args.log_format,
            )
        )
    except KeyboardInterrupt:
        sys.exit(0)
