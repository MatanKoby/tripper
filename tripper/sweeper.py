"""Recovery of runs stranded in ``running`` (``spec/flows.md`` under *Sweeper*).

A hard crash (OOM, timeout kill, deploy mid-flight) never runs the orchestrator's except block, so
the run's doc is left ``running`` with a lease that will simply expire. This sweep is the backstop
for exactly that case, over **both** run kinds (``spec/flows.md``):

- **domain** docs (round-1 search), lifecycle field ``agentStatus``; and
- **refinement** docs (a refine run), lifecycle field ``status``.

Every doc still ``running`` after its ``leaseExpiresAt`` has passed is driven straight to a terminal
``error``. The reap is deliberately terminal rather than a re-queue: nothing in this system can
re-fire a run (every trigger is an ``onCreate``, the stranded doc already exists, and the Firestore
trigger options in ``firebase-functions`` expose no ``retry``), so setting a doc back to ``pending``
would park it forever instead of recovering it. A dead run is therefore surfaced to the user, who
retries by resubmitting (``spec/flows.md``). A terminally-failed **refinement** also resets its
parent domain back to ``idle`` (the refine had set it ``running``), so a dead refine never strands
the domain, and its earlier still-valid rounds, as perpetually "thinking".

It is **not scheduled**: :func:`sweep` is called at the head of the trip fan-out, so it costs
nothing while the app is idle (``spec/architecture.md`` under *Cost stance*).

It operates through the Admin SDK (never the orchestrator internals) and reuses the claim/state
vocabulary in ``tripper.jobs``: the same ``_lease_expired`` predicate as ``claim_job`` and the same
``TripError`` terminal shape as ``write_run_error``. The per-doc mutation runs in a transaction that
re-checks the ``running`` + expired-lease guard, so a run the orchestrator reclaims between the
query and the write is left alone rather than clobbered.

Each collection-group query (``<status> ==`` plus a ``leaseExpiresAt`` range) needs its composite
index in ``firestore.indexes.json`` (both ``domains`` and ``refinements`` are indexed).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from firebase_admin import firestore
from google.cloud.firestore_v1 import FieldFilter

from tripper.contract import TripError
from tripper.jobs import Clock, _lease_expired, utcnow

logger = logging.getLogger("tripper.sweeper")

#: Collection group of the per-domain search-run docs (``.../trips/{tripId}/domains/{domain}``).
DOMAINS_COLLECTION = "domains"
#: The domain doc's lifecycle field the sweep reaps on (``spec/schema.md`` -> Domain).
RUN_STATUS_FIELD = "agentStatus"

#: Collection group of the refine-run docs (``.../domains/{domain}/refinements/{refineId}``).
REFINEMENTS_COLLECTION = "refinements"
#: The refinement doc's lifecycle field the sweep reaps on (``spec/schema.md`` -> Refinement).
REFINE_STATUS_FIELD = "status"


@dataclass(frozen=True)
class SweepReport:
    """Tally of one sweep pass. ``scanned`` counts stale hits; the rest partition their outcomes.

    ``scanned == failed + skipped``. ``skipped`` covers docs that the guard re-check found already
    moved on (reclaimed by the orchestrator or swept by an overlapping run). A pass sums the tallies
    of the domain and refinement groups.
    """

    scanned: int = 0
    failed: int = 0
    skipped: int = 0

    def __add__(self, other: SweepReport) -> SweepReport:
        return SweepReport(
            scanned=self.scanned + other.scanned,
            failed=self.failed + other.failed,
            skipped=self.skipped + other.skipped,
        )


def sweep(db: Any, *, clock: Clock = utcnow) -> SweepReport:
    """Reap stale ``running`` runs (domain searches + refines) once and tally the outcomes.

    Never raises for a single bad doc: a per-doc failure is logged and counted as skipped so one
    poison doc cannot stall the whole pass. Callers treat a sweep failure as non-fatal: it is a
    backstop and must never take down the work it runs ahead of.
    """
    now = clock()
    report = _sweep_group(db, DOMAINS_COLLECTION, RUN_STATUS_FIELD, now=now) + _sweep_group(
        db, REFINEMENTS_COLLECTION, REFINE_STATUS_FIELD, now=now, reset_domain=True
    )
    logger.info(
        "sweep pass: scanned=%d failed=%d skipped=%d",
        report.scanned,
        report.failed,
        report.skipped,
    )
    return report


def _sweep_group(
    db: Any,
    collection: str,
    status_field: str,
    *,
    now: datetime,
    reset_domain: bool = False,
) -> SweepReport:
    """Reap the stale ``running`` docs in one collection group and tally the outcomes."""
    query = (
        db.collection_group(collection)
        .where(filter=FieldFilter(status_field, "==", "running"))
        .where(filter=FieldFilter("leaseExpiresAt", "<", now))
    )
    # Materialize the refs before mutating, so we are not writing while the stream is still open.
    refs = [snapshot.reference for snapshot in query.stream()]

    scanned = failed = skipped = 0
    for doc_ref in refs:
        scanned += 1
        try:
            outcome = _reap_one(
                db, doc_ref, status_field=status_field, now=now, reset_domain=reset_domain
            )
        except Exception:
            logger.exception("sweep failed for %s", doc_ref.path)
            skipped += 1
            continue
        if outcome == "failed":
            failed += 1
        else:
            skipped += 1

    return SweepReport(scanned=scanned, failed=failed, skipped=skipped)


def _reap_one(
    db: Any,
    doc_ref: Any,
    *,
    status_field: str,
    now: datetime,
    reset_domain: bool = False,
) -> str:
    """Drive one stale run to terminal ``error`` in a transaction; returns the outcome tag.

    The transaction re-reads and re-applies the ``running`` + expired-lease guard, so a run the
    orchestrator reclaimed (or another sweep already handled) since the query is left untouched
    (``"skipped"``). When ``reset_domain`` (a refinement), the terminal error also returns the
    parent domain, if still ``running`` from this refine, to ``idle`` in the same transaction.
    """

    @firestore.transactional
    def _txn(transaction: Any) -> str:
        # All reads first (Firestore requires reads before writes in a transaction).
        snapshot = doc_ref.get(transaction=transaction)
        domain_ref = doc_ref.parent.parent if reset_domain else None
        domain_snapshot = (
            domain_ref.get(transaction=transaction) if domain_ref is not None else None
        )

        if not getattr(snapshot, "exists", False):
            return "skipped"
        data = snapshot.to_dict() or {}
        if data.get(status_field) != "running" or not _lease_expired(
            data.get("leaseExpiresAt"), now
        ):
            return "skipped"

        attempts = int(data.get("attempts") or 0)
        error = TripError(
            message=f"worker died or timed out on attempt {attempts}; run abandoned",
            kind="LeaseExpired",
        )
        transaction.update(
            doc_ref,
            {
                status_field: "error",
                "error": error.to_dict(),
                "lastError": error.message,
                "updatedAt": firestore.SERVER_TIMESTAMP,
            },
        )
        if (
            domain_ref is not None
            and domain_snapshot is not None
            and (domain_snapshot.to_dict() or {}).get("agentStatus") == "running"
        ):
            transaction.update(
                domain_ref,
                {"agentStatus": "idle", "updatedAt": firestore.SERVER_TIMESTAMP},
            )
        return "failed"

    return _txn(db.transaction())
