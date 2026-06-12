from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path

import structlog
import valkey.asyncio as avalkey

import agent.bootstrap as bootstrap
from agent.baseline import BaselineEngine, load_master_secret
from agent.config import load_config
from agent.heartbeat import HeartbeatPublisher
from agent.logging import configure_logging
from agent.publisher import Publisher
from agent.queue import EventQueue
from agent.state import load_state

log = structlog.get_logger()


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
    # Señala que el agente está en modo drenaje graceful (SIGTERM recibido)
    shutdown_flag = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _shutdown(sig_name: str) -> None:
        log.info("shutting down", signal=sig_name)
        shutdown_flag.set()
        stop_event.set()

    loop.add_signal_handler(signal.SIGTERM, lambda: _shutdown("SIGTERM"))
    loop.add_signal_handler(signal.SIGINT, lambda: _shutdown("SIGINT"))

    # Una conexión Valkey por proceso, compartida por publisher y heartbeat (D-1, D8)
    valkey_client: avalkey.Valkey = avalkey.Valkey.from_url(cfg.valkey_url, decode_responses=True)

    queue = EventQueue(cfg.storage.queue_dir)
    publisher = Publisher(cfg, queue, valkey_client)
    heartbeat = HeartbeatPublisher(cfg, queue, state, valkey_client)

    try:
        await asyncio.gather(
            publisher.run(stop_event),
            heartbeat.run(stop_event, shutdown_flag),
        )
    finally:
        await valkey_client.aclose()


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
