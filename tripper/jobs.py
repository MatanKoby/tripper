"""Job-document state helpers: the idempotent claim, the lease heartbeat, and terminal writes.

These carry the reliability machinery from ``spec/flows.md`` and operate directly on a Firestore
``DocumentReference``; the orchestration flow that strings them together lives in
``tripper.orchestrator``. Keeping them here (transport-free, no agent knowledge) lets the sweeper
(Batch 5) reuse the same claim/state vocabulary.

Timestamps: ``leaseExpiresAt`` and ``startedAt`` are computed from a ``clock`` (injectable for
tests, UTC-aware); ``updatedAt`` uses the Firestore server clock.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from firebase_admin import firestore

from tripper.contract import TripError, TripSuggestions

logger = logging.getLogger("tripper.jobs")

#: Worst-case run budget (cold start + agent loop); sizes the lease and the sweeper reap window.
LEASE_BUDGET = timedelta(minutes=15)
#: How often the background heartbeat bumps the lease while a job runs (``spec/flows.md``: 30-60s).
HEARTBEAT_INTERVAL = 45.0
#: Attempts allowed before the sweeper gives a stuck job a terminal ``error`` (``spec/flows.md``).
DEFAULT_MAX_ATTEMPTS = 3

#: A source of the current UTC-aware time; injectable so tests can pin "now".
Clock = Callable[[], datetime]


def utcnow() -> datetime:
    """The default clock: the current time, UTC-aware."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class ClaimOutcome:
    """Result of an attempted claim. ``input``/``attempts`` are set only when ``claimed``."""

    claimed: bool
    reason: str
    input: dict[str, Any] | None = None
    attempts: int = 0


def _lease_expired(lease: Any, now: datetime) -> bool:
    """True when ``lease`` is a datetime strictly before ``now`` (missing lease is not expired)."""
    if not isinstance(lease, datetime):
        return False
    if lease.tzinfo is None:
        lease = lease.replace(tzinfo=UTC)
    return lease < now


def claim_job(
    db: Any,
    doc_ref: Any,
    *,
    clock: Clock = utcnow,
    lease_budget: timedelta = LEASE_BUDGET,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> ClaimOutcome:
    """Idempotently claim the job in a transaction (``spec/flows.md`` under *Idempotent claim*).

    Proceeds only if the doc is ``pending`` OR (``running`` AND its lease has expired). On success
    it sets ``status="running"``, ``startedAt``, ``attempts += 1`` and a fresh ``leaseExpiresAt``,
    seeding ``maxAttempts`` on first claim. A duplicate delivery whose lease is still valid is
    reported as not claimed, so the agent never double-runs.
    """
    now = clock()

    @firestore.transactional
    def _txn(transaction: Any) -> ClaimOutcome:
        snapshot = doc_ref.get(transaction=transaction)
        if not getattr(snapshot, "exists", False):
            return ClaimOutcome(claimed=False, reason="missing")
        data = snapshot.to_dict() or {}
        status = data.get("status")
        claimable = status == "pending" or (
            status == "running" and _lease_expired(data.get("leaseExpiresAt"), now)
        )
        if not claimable:
            return ClaimOutcome(claimed=False, reason=f"not-claimable:{status}")

        attempts = int(data.get("attempts") or 0) + 1
        update: dict[str, Any] = {
            "status": "running",
            "startedAt": now,
            "attempts": attempts,
            "leaseExpiresAt": now + lease_budget,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        }
        if "maxAttempts" not in data:
            update["maxAttempts"] = max_attempts
        transaction.update(doc_ref, update)
        return ClaimOutcome(
            claimed=True, reason="claimed", input=data.get("input"), attempts=attempts
        )

    return _txn(db.transaction())


@contextmanager
def lease_heartbeat(
    doc_ref: Any,
    *,
    clock: Clock = utcnow,
    interval: float = HEARTBEAT_INTERVAL,
    lease_budget: timedelta = LEASE_BUDGET,
) -> Iterator[None]:
    """Keep the job's lease fresh while the body runs (``spec/flows.md`` under *Lease heartbeat*).

    A background daemon thread bumps ``leaseExpiresAt`` every ``interval`` seconds. This is a
    Firestore write only; it never touches the agent/Nebius endpoint, so it does not keep anything
    warm, it just tells the sweeper the worker is still alive. A failed heartbeat is logged, not
    raised. The thread is stopped and joined on exit.
    """
    stop = threading.Event()

    def _beat() -> None:
        while not stop.wait(interval):
            try:
                doc_ref.update(
                    {
                        "leaseExpiresAt": clock() + lease_budget,
                        "updatedAt": firestore.SERVER_TIMESTAMP,
                    }
                )
            except Exception:
                logger.warning("lease heartbeat failed for %s", doc_ref.path, exc_info=True)

    thread = threading.Thread(target=_beat, name="tripper-lease-heartbeat", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=interval + 5.0)


def write_done(doc_ref: Any, results: TripSuggestions) -> None:
    """Write the terminal success state: ``status="done"`` with schema-valid ``results``."""
    doc_ref.update(
        {
            "status": "done",
            "results": results.to_dict(),
            "updatedAt": firestore.SERVER_TIMESTAMP,
        }
    )


def write_error(doc_ref: Any, error: TripError) -> None:
    """Write the terminal failure state: ``status="error"`` with ``error`` and ``lastError``."""
    payload = error.to_dict()
    doc_ref.update(
        {
            "status": "error",
            "error": payload,
            "lastError": error.message,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        }
    )
