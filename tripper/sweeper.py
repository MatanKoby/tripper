"""Scheduled recovery of jobs stranded in ``running`` (``spec/flows.md`` under *Sweeper*).

A hard crash (OOM, timeout kill, deploy mid-flight) never runs the orchestrator's except block, so
the job doc is left in ``running`` with a lease that will simply expire. This sweep is the backstop
for exactly that case: it finds every job that is still ``running`` after its ``leaseExpiresAt`` has
passed and either **re-queues** it (``status="pending"``) for another attempt, or, once
``maxAttempts`` is spent, drives it to a terminal ``status="error"`` so a poison job stops looping
and burning spend.

It operates through the Admin SDK on job docs only (never the orchestrator internals) and reuses
the claim/state vocabulary in ``tripper.jobs``: the same ``_lease_expired`` predicate as
``claim_job``, the same ``DEFAULT_MAX_ATTEMPTS`` fallback, the same ``TripError`` terminal shape as
``write_error``. The per-doc mutation runs in a transaction that re-checks the ``running`` +
expired-lease guard, so a job the orchestrator reclaims between the query and the write is left
alone rather than clobbered.

The query (``status ==`` equality plus a ``leaseExpiresAt`` range, collection-group scope) needs the
composite index in ``firestore.indexes.json``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from firebase_admin import firestore
from google.cloud.firestore_v1 import FieldFilter

from tripper.contract import TripError
from tripper.jobs import DEFAULT_MAX_ATTEMPTS, Clock, _lease_expired, utcnow

logger = logging.getLogger("tripper.sweeper")

#: Firestore token for the collection every job doc lives in (``users/{uid}/trips/{tripId}``).
TRIPS_COLLECTION = "trips"


@dataclass(frozen=True)
class SweepReport:
    """Tally of one sweep pass. ``scanned`` counts stale hits; the rest partition their outcomes.

    ``scanned == requeued + failed + skipped``. ``skipped`` covers docs that the guard re-check
    found already moved on (reclaimed by the orchestrator or swept by an overlapping run).
    """

    scanned: int = 0
    requeued: int = 0
    failed: int = 0
    skipped: int = 0


def sweep(
    db: Any, *, clock: Clock = utcnow, max_attempts: int = DEFAULT_MAX_ATTEMPTS
) -> SweepReport:
    """Reap stale ``running`` jobs once and return the outcome tally (``spec/flows.md``).

    ``max_attempts`` is only the fallback for a doc missing ``maxAttempts`` (the claim seeds it, so
    in practice each doc carries its own). Never raises for a single bad doc: a per-doc failure is
    logged and counted as skipped so one poison doc cannot stall the whole pass.
    """
    now = clock()
    query = (
        db.collection_group(TRIPS_COLLECTION)
        .where(filter=FieldFilter("status", "==", "running"))
        .where(filter=FieldFilter("leaseExpiresAt", "<", now))
    )
    # Materialize the refs before mutating, so we are not writing while the stream is still open.
    refs = [snapshot.reference for snapshot in query.stream()]

    scanned = requeued = failed = skipped = 0
    for doc_ref in refs:
        scanned += 1
        try:
            outcome = _reap_one(db, doc_ref, now=now, max_attempts=max_attempts)
        except Exception:
            logger.exception("sweep failed for %s", doc_ref.path)
            skipped += 1
            continue
        if outcome == "requeued":
            requeued += 1
        elif outcome == "failed":
            failed += 1
        else:
            skipped += 1

    report = SweepReport(scanned=scanned, requeued=requeued, failed=failed, skipped=skipped)
    logger.info(
        "sweep pass: scanned=%d requeued=%d failed=%d skipped=%d",
        report.scanned,
        report.requeued,
        report.failed,
        report.skipped,
    )
    return report


def _reap_one(db: Any, doc_ref: Any, *, now: datetime, max_attempts: int) -> str:
    """Re-queue or fail one stale job in a transaction; returns the outcome tag.

    The transaction re-reads and re-applies the ``running`` + expired-lease guard, so a job the
    orchestrator reclaimed (or another sweep already handled) since the query is left untouched
    (``"skipped"``). Otherwise it re-queues when attempts remain, else writes the terminal error.
    """

    @firestore.transactional
    def _txn(transaction: Any) -> str:
        snapshot = doc_ref.get(transaction=transaction)
        if not getattr(snapshot, "exists", False):
            return "skipped"
        data = snapshot.to_dict() or {}
        if data.get("status") != "running" or not _lease_expired(data.get("leaseExpiresAt"), now):
            return "skipped"

        attempts = int(data.get("attempts") or 0)
        limit = int(data.get("maxAttempts") or max_attempts)
        if attempts < limit:
            transaction.update(
                doc_ref, {"status": "pending", "updatedAt": firestore.SERVER_TIMESTAMP}
            )
            return "requeued"

        error = TripError(
            message=f"worker died or timed out; gave up after {attempts} attempt(s)",
            kind="LeaseExpired",
        )
        transaction.update(
            doc_ref,
            {
                "status": "error",
                "error": error.to_dict(),
                "lastError": error.message,
                "updatedAt": firestore.SERVER_TIMESTAMP,
            },
        )
        return "failed"

    return _txn(db.transaction())
