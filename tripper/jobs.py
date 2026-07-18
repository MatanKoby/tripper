"""Job-document state helpers: the idempotent claim, the lease heartbeat, and terminal writes.

These carry the reliability machinery from ``spec/flows.md`` and operate directly on a Firestore
``DocumentReference``; the orchestration flow that strings them together lives in
``tripper.orchestrator``. Keeping them here (transport-free, no agent knowledge) lets the sweeper
(Batch 5) reuse the same claim/state vocabulary.

Both run kinds share one claim: a **search** run claims its ``domains/{domain}`` doc (its lifecycle
field is ``agentStatus``), a **refine** run its ``refinements/{id}`` doc (``status``); the claim's
``status_field`` selects which. On success a search writes its candidates into ``suggested/*`` and
drives the domain doc to ``agentStatus: "idle"`` (:func:`write_search_result`).

Timestamps: ``leaseExpiresAt`` and ``startedAt`` are computed from a ``clock`` (injectable for
tests, UTC-aware); ``updatedAt`` uses the Firestore server clock.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from firebase_admin import firestore

from tripper.agents.base import DomainSearchResult
from tripper.contract import SuggestedDoc, TripError

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
    status_field: str = "status",
    clock: Clock = utcnow,
    lease_budget: timedelta = LEASE_BUDGET,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> ClaimOutcome:
    """Idempotently claim the run in a transaction (``spec/flows.md`` under *Idempotent claim*).

    ``status_field`` is the doc's lifecycle field: ``"status"`` for a trip/refinement doc,
    ``"agentStatus"`` for a ``domains/{domain}`` doc. Proceeds only if that field is ``pending`` OR
    (``running`` AND its lease has expired). On success it sets the field to ``"running"``,
    ``startedAt``, ``attempts += 1``, a fresh ``leaseExpiresAt``, seeding ``maxAttempts`` on first
    claim. A duplicate delivery whose lease is still valid is reported as not claimed, so the agent
    never double-runs.
    """
    now = clock()

    @firestore.transactional
    def _txn(transaction: Any) -> ClaimOutcome:
        snapshot = doc_ref.get(transaction=transaction)
        if not getattr(snapshot, "exists", False):
            return ClaimOutcome(claimed=False, reason="missing")
        data = snapshot.to_dict() or {}
        status = data.get(status_field)
        claimable = status == "pending" or (
            status == "running" and _lease_expired(data.get("leaseExpiresAt"), now)
        )
        if not claimable:
            return ClaimOutcome(claimed=False, reason=f"not-claimable:{status}")

        attempts = int(data.get("attempts") or 0) + 1
        update: dict[str, Any] = {
            status_field: "running",
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


def write_search_result(domain_ref: Any, result: DomainSearchResult, *, round: int = 1) -> None:
    """Write a completed search run to its ``domains/{domain}`` subtree (``spec/flows.md``).

    Each :class:`~tripper.agents.base.Suggestion` becomes a ``suggested/{id}`` doc (a
    :class:`~tripper.contract.SuggestedDoc`: the neutral item + ``lens`` / ``rank`` / ``round`` sort
    keys), written **first**; only then is the domain doc driven to ``agentStatus: "idle"`` with the
    run's ``round`` / ``diagnostics`` / ``warnings`` / ``counts``. So an ``idle`` domain
    has its candidates present. Re-running a round overwrites the same ids, so a reclaim after
    a partial write is idempotent.
    """
    suggested = domain_ref.collection("suggested")
    for rank, suggestion in enumerate(result.suggestions):
        suggested.document(suggestion.id).set(_suggested_payload(suggestion, rank, round))
    domain_ref.update(
        {
            "agentStatus": "idle",
            "round": round,
            "diagnostics": result.diagnostics,
            "warnings": result.warnings,
            "counts": result.counts,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        }
    )


def _suggested_payload(suggestion: Any, rank: int, round: int) -> dict[str, Any]:
    """A ``SuggestedDoc`` dict for one candidate: the neutral item + its sort/group keys."""
    lens = suggestion.lens.value if suggestion.lens is not None else None
    doc = SuggestedDoc.model_validate(
        {**suggestion.item.to_dict(), "lens": lens, "rank": rank, "round": round}
    ).to_dict()
    doc["createdAt"] = firestore.SERVER_TIMESTAMP
    return doc


def write_refine_result(
    domain_ref: Any,
    refinement_ref: Any,
    result: DomainSearchResult,
    *,
    round: int,
    dismiss_ids: Sequence[str] = (),
) -> None:
    """Persist a completed refine run: append its round, retire the unwanted, settle both docs.

    Unlike a search (``write_search_result``), a refine **appends** — its candidate doc ids are
    qualified with ``round`` so this round's picks never clobber a prior round's (both the flight
    and activities agents reuse ids across runs, ``spec/agents.md``); the FE groups by ``round``.
    Order of writes mirrors a search: candidates first, then the disliked prior candidates hidden
    (``dismissed: true``, not deleted, ``spec/flows.md``), then the domain returns to
    ``agentStatus: "idle"`` at the new ``round`` with the latest run metadata, and finally the
    refinement doc is marked ``done``. So an ``idle`` domain always has the appended round present.
    """
    suggested = domain_ref.collection("suggested")
    for rank, suggestion in enumerate(result.suggestions):
        suggested.document(_refine_doc_id(suggestion.id, round)).set(
            _suggested_payload(suggestion, rank, round)
        )
    for suggestion_id in dismiss_ids:
        suggested.document(suggestion_id).update(
            {"dismissed": True, "updatedAt": firestore.SERVER_TIMESTAMP}
        )
    domain_ref.update(
        {
            "agentStatus": "idle",
            "round": round,
            "diagnostics": result.diagnostics,
            "warnings": result.warnings,
            "counts": result.counts,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        }
    )
    refinement_ref.update({"status": "done", "updatedAt": firestore.SERVER_TIMESTAMP})


def _refine_doc_id(suggestion_id: str, round: int) -> str:
    """A round-qualified ``suggested`` doc id, so an appended round never clobbers a prior one."""
    return f"{suggestion_id}::r{round}"


def write_run_error(doc_ref: Any, error: TripError, *, status_field: str = "status") -> None:
    """Write a run's terminal failure: its lifecycle field to ``"error"`` + ``lastError``.

    ``status_field`` is ``"agentStatus"`` for a domain search, ``"status"`` for a refinement.
    """
    doc_ref.update(
        {
            status_field: "error",
            "error": error.to_dict(),
            "lastError": error.message,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        }
    )
