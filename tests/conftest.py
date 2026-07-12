"""Shared fixtures: a Firestore emulator and a client for the orchestrator tests.

If ``FIRESTORE_EMULATOR_HOST`` is already set (e.g. under ``firebase emulators:exec``) the fixture
reuses it; if something is already listening on the emulator port, it reuses that too. Otherwise it
starts a firestore-only emulator on a ``demo-`` project (which runs fully offline, no credentials).
When no emulator can be reached or started, the emulator-backed tests are skipped (not failed), so
``pytest`` still runs the pure-Python suites anywhere.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EMULATOR_HOST = "127.0.0.1"
EMULATOR_PORT = 8080
PROJECT_ID = "demo-tripper"
STARTUP_TIMEOUT = 90.0


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _reset_data(host: str) -> None:
    """Wipe all documents in the emulator between tests (the emulator's admin REST endpoint)."""
    url = f"http://{host}/emulator/v1/projects/{PROJECT_ID}/databases/(default)/documents"
    try:
        urllib.request.urlopen(urllib.request.Request(url, method="DELETE"), timeout=10)
    except Exception:
        pass


@pytest.fixture(scope="session")
def firestore_emulator() -> Iterator[str]:
    host = f"{EMULATOR_HOST}:{EMULATOR_PORT}"

    existing = os.environ.get("FIRESTORE_EMULATOR_HOST")
    if existing:
        yield existing
        return
    if _port_open(EMULATOR_HOST, EMULATOR_PORT):
        os.environ["FIRESTORE_EMULATOR_HOST"] = host
        yield host
        return

    firebase = shutil.which("firebase")
    if firebase is None:
        pytest.skip("firebase CLI not available; skipping emulator-backed tests")

    log = tempfile.NamedTemporaryFile(  # noqa: SIM115 - kept open for the emulator's lifetime
        prefix="tripper-firestore-emulator-", suffix=".log", delete=False
    )
    proc = subprocess.Popen(
        [firebase, "emulators:start", "--only", "firestore", "--project", PROJECT_ID],
        cwd=str(REPO_ROOT),
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        deadline = time.time() + STARTUP_TIMEOUT
        while time.time() < deadline:
            if proc.poll() is not None:
                pytest.skip(f"firestore emulator exited early; see {log.name}")
            if _port_open(EMULATOR_HOST, EMULATOR_PORT):
                break
            time.sleep(0.5)
        else:
            pytest.skip(f"firestore emulator not ready in {STARTUP_TIMEOUT:.0f}s; see {log.name}")

        os.environ["FIRESTORE_EMULATOR_HOST"] = host
        yield host
    finally:
        os.environ.pop("FIRESTORE_EMULATOR_HOST", None)
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=15)
        except Exception:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass
        log.close()


@pytest.fixture
def db(firestore_emulator: str) -> Iterator[object]:
    """A Firestore client bound to the emulator, with a clean database per test."""
    from google.cloud import firestore as gcf

    _reset_data(firestore_emulator)
    client = gcf.Client(project=PROJECT_ID)
    yield client
    client.close()
