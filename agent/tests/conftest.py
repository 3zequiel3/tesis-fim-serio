"""Shared pytest fixtures for the agent test suite.

Change 53 (D63/RN-157) requires every `EventQueue` to be constructed with a
`master_secret` and an `agent_id`, and queue/discard files can no longer be
inspected as plain JSON. This module centralizes the fixed test key material
and the file-decryption helper so each test module can update its
`EventQueue` call sites mechanically instead of re-deriving key material or
duplicating the decrypt logic by hand.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent.queue import derive_queue_key, read_queue_file

# Fixed 32-byte master secret and agent_id shared by tests that construct an
# EventQueue directly (not through an AgentConfig carrying its own
# agent_id). Any test module with its own agent_id must pass that same
# agent_id to `decrypt_queue_file` below.
TEST_MASTER_SECRET: bytes = bytes(range(32))
TEST_AGENT_ID: str = "test-agent-01"


@pytest.fixture()
def master_secret() -> bytes:
    """Fixed 32-byte master secret for tests that construct an EventQueue."""
    return TEST_MASTER_SECRET


@pytest.fixture()
def agent_id() -> str:
    """Fixed agent_id paired with `master_secret` above."""
    return TEST_AGENT_ID


def decrypt_queue_file(
    path: Path,
    master_secret: bytes = TEST_MASTER_SECRET,
    agent_id: str = TEST_AGENT_ID,
) -> dict[str, Any]:
    """Decrypt one queue/discard file for test assertions (D63/RN-157).

    Wraps `agent.queue.read_queue_file`, which reuses the module's own
    decrypt/legacy-detection logic instead of duplicating it in tests.
    """
    key = derive_queue_key(master_secret, agent_id)
    return read_queue_file(path, key)
