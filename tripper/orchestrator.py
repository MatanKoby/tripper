"""The trip orchestrator: fan a trip out to per-domain search runs (``spec/flows.md``).

This is the M2 flow, independent of the Cloud Functions trigger wiring (that lives in ``main.py``):

- :func:`fan_out` runs on a trip ``onCreate``. It marks the trip ``active`` and creates one
  ``domains/{domain}`` doc per active agent. Each create is the trigger for that domain's search.
- :func:`run_search` runs on a ``domains/{domain}`` ``onCreate``. It claims/leases the domain doc,
  runs that domain's adapter, writes the neutral candidates into ``suggested/*``, and drives the
  domain to ``agentStatus: "idle"``.

Both reuse the primitives in ``tripper.jobs`` and the ``tripper.agents.base.Agent`` seam.
Contract for a search run: nothing escapes. A duplicate delivery is skipped, a valid run drives the
domain to ``idle``, and any failure (agent raised, invalid output, bad input) drives it to
``error``. Only a hard crash leaves the domain ``running`` for the lease + sweeper. The M1
single-document ``results`` path this replaces is in ``spec/archive.md``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from google.api_core.exceptions import AlreadyExists

from tripper.agents.base import Agent
from tripper.contract import DomainDoc, TripError, TripInput
from tripper.jobs import (
    DEFAULT_MAX_ATTEMPTS,
    HEARTBEAT_INTERVAL,
    LEASE_BUDGET,
    Clock,
    claim_job,
    lease_heartbeat,
    utcnow,
    write_run_error,
    write_search_result,
)

try:  # firebase-admin at runtime; the emulator-backed tests import it too.
    from firebase_admin import firestore

    _SERVER_TIMESTAMP = firestore.SERVER_TIMESTAMP
except Exception:  # pragma: no cover - firestore always present where this runs
    _SERVER_TIMESTAMP = None

logger = logging.getLogger("tripper.orchestrator")

#: The domain-doc lifecycle field the search claim operates on (``spec/schema.md`` → Domain).
DOMAIN_STATUS_FIELD = "agentStatus"


def fan_out(db: Any, trip_ref: Any, *, agents: Sequence[Agent], clock: Clock = utcnow) -> None:
    """Trip ``onCreate``: mark the trip ``active`` and create one domain doc per active agent.

    Idempotent: it fans out only from ``pending`` (a redelivery finds ``active`` and returns), and
    each domain doc is a create that is skipped if it already exists — so a duplicate delivery never
    re-triggers a domain's search. Raises only on an infra failure; the trigger turns that into a
    terminal trip ``error`` (``spec/flows.md``: the trip errors only if fan-out itself fails).
    """
    snapshot = trip_ref.get()
    if not getattr(snapshot, "exists", False):
        logger.warning("fan-out: trip %s missing; ignoring", trip_ref.path)
        return
    data = snapshot.to_dict() or {}
    if data.get("status") != "pending":
        logger.info("fan-out: skip %s (status=%s)", trip_ref.path, data.get("status"))
        return

    trip_ref.update({"status": "active", "updatedAt": _SERVER_TIMESTAMP})
    for agent in agents:
        _create_domain_doc(trip_ref, agent)
    logger.info("fan-out: %s active over %d domain(s)", trip_ref.path, len(agents))


def _create_domain_doc(trip_ref: Any, agent: Agent) -> None:
    """Create the ``domains/{domain}`` doc that triggers ``agent``'s search (id = domain value)."""
    domain_ref = trip_ref.collection("domains").document(agent.domain.value)
    payload = DomainDoc(domain=agent.domain, selectionMode=agent.selection_mode).to_dict()
    payload["createdAt"] = _SERVER_TIMESTAMP
    payload["updatedAt"] = _SERVER_TIMESTAMP
    try:
        domain_ref.create(payload)
    except AlreadyExists:
        logger.info("fan-out: domain %s already exists; skipping", domain_ref.path)


def run_search(
    db: Any,
    domain_ref: Any,
    *,
    agents_by_domain: Mapping[str, Agent],
    clock: Clock = utcnow,
    lease_budget=LEASE_BUDGET,
    heartbeat_interval: float = HEARTBEAT_INTERVAL,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> None:
    """Drive one domain's round-1 search to a terminal state. Never raises (guards the trigger)."""
    path = domain_ref.path
    claimed = False
    try:
        outcome = claim_job(
            db,
            domain_ref,
            status_field=DOMAIN_STATUS_FIELD,
            clock=clock,
            lease_budget=lease_budget,
            max_attempts=max_attempts,
        )
        if not outcome.claimed:
            logger.info("skipping search %s (%s)", path, outcome.reason)
            return
        claimed = True
        logger.info("claimed search %s (attempt %d)", path, outcome.attempts)

        agent = agents_by_domain.get(domain_ref.id)
        if agent is None:
            raise ValueError(f"no active agent for domain {domain_ref.id!r}")
        trip = _load_trip_input(domain_ref)

        with lease_heartbeat(
            domain_ref, clock=clock, interval=heartbeat_interval, lease_budget=lease_budget
        ):
            result = agent.run(trip)
        write_search_result(domain_ref, result, round=1)
        logger.info("completed search %s (%d suggestions)", path, len(result.suggestions))
    except Exception as exc:
        # Catch-all: a failed run must not crash the handler (which would trigger redelivery). We
        # persist the error on the domain doc we hold; a claim/infra failure just logs and lets the
        # lease + sweeper recover.
        logger.exception("search failed for %s", path)
        if claimed:
            _fail_domain_safely(domain_ref, exc)


def _load_trip_input(domain_ref: Any) -> TripInput:
    """Parse the parent trip's ``input`` (``domains/{domain}`` sits under the trip doc)."""
    trip_ref = domain_ref.parent.parent
    snapshot = trip_ref.get()
    data = snapshot.to_dict() if getattr(snapshot, "exists", False) else None
    return TripInput.from_dict((data or {}).get("input") or {})


def _fail_domain_safely(domain_ref: Any, exc: BaseException) -> None:
    """Best-effort terminal error on the domain doc; a failure here is logged, not raised."""
    error = TripError(message=str(exc) or repr(exc), kind=type(exc).__name__)
    try:
        write_run_error(domain_ref, error, status_field=DOMAIN_STATUS_FIELD)
    except Exception:
        logger.exception("failed to persist error state for %s", domain_ref.path)
