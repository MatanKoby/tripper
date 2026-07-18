"""The trip orchestrator: fan a trip out to per-domain search runs (``spec/flows.md``).

This is the M2 flow, independent of the Cloud Functions trigger wiring (that lives in ``main.py``):

- :func:`fan_out` runs on a trip ``onCreate``. It marks the trip ``active`` and creates one
  ``domains/{domain}`` doc per active agent. Each create is the trigger for that domain's search.
- :func:`run_search` runs on a ``domains/{domain}`` ``onCreate``. It claims/leases the domain doc,
  runs that domain's adapter, writes the neutral candidates into ``suggested/*``, and drives the
  domain to ``agentStatus: "idle"``.
- :func:`run_refine` runs on a ``domains/{domain}/refinements/{id}`` ``onCreate``. It claims/leases
  the *refinement* doc, reads the current feedback marks off ``suggested/*``, runs the adapter's
  ``refine``, appends the picks as the next round, and settles the domain back to ``idle``.

All reuse the primitives in ``tripper.jobs`` and the ``tripper.agents.base.Agent`` seam.
Contract for a search run: nothing escapes. A duplicate delivery is skipped, a valid run drives the
domain to ``idle``, and any failure (agent raised, invalid output, bad input) drives it to
``error``. Only a hard crash leaves the domain ``running`` for the lease + sweeper. The M1
single-document ``results`` path this replaces is in ``spec/archive.md``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from typing import Any

from google.api_core.exceptions import AlreadyExists

from tripper.agents.base import Agent, PriorCandidate
from tripper.contract import DomainDoc, Feedback, LensName, ResultItem, TripError, TripInput
from tripper.jobs import (
    DEFAULT_MAX_ATTEMPTS,
    HEARTBEAT_INTERVAL,
    LEASE_BUDGET,
    Clock,
    claim_job,
    lease_heartbeat,
    utcnow,
    write_refine_result,
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

#: The refinement-doc lifecycle field the refine claim operates on (``spec/schema.md``, Refinement).
REFINE_STATUS_FIELD = "status"


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


def run_refine(
    db: Any,
    refinement_ref: Any,
    *,
    agents_by_domain: Mapping[str, Agent],
    clock: Clock = utcnow,
    lease_budget=LEASE_BUDGET,
    heartbeat_interval: float = HEARTBEAT_INTERVAL,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> None:
    """Drive one refine run to a terminal state (``spec/flows.md``). Never raises (guards trigger).

    A ``refinements/{id}`` ``onCreate`` fires this. It claims the **refinement** doc (its lifecycle
    is ``status``, distinct from the domain's ``agentStatus``), reads the current feedback marks off
    the domain's ``suggested/*``, sets the domain ``running`` (so the FE disables refine while it
    works), runs the adapter's :meth:`~tripper.agents.base.Agent.refine`, appends the returned picks
    as the next round, hides the disliked ones (``dismissed``), and settles the domain back to
    ``idle`` + the refinement to ``done``. A hotel refinement (no ``refine_sync`` yet) raises
    :class:`~tripper.agents.base.RefineNotSupported`, caught here as a clean refinement ``error``.
    """
    path = refinement_ref.path
    domain_ref = refinement_ref.parent.parent  # .../domains/{domain}/refinements/{id} -> the domain
    claimed = False
    try:
        outcome = claim_job(
            db,
            refinement_ref,
            status_field=REFINE_STATUS_FIELD,
            clock=clock,
            lease_budget=lease_budget,
            max_attempts=max_attempts,
        )
        if not outcome.claimed:
            logger.info("skipping refine %s (%s)", path, outcome.reason)
            return
        claimed = True
        logger.info("claimed refine %s (attempt %d)", path, outcome.attempts)

        agent = agents_by_domain.get(domain_ref.id)
        if agent is None:
            raise ValueError(f"no active agent for domain {domain_ref.id!r}")
        trip = _load_trip_input(domain_ref)
        prior = _load_prior_candidates(domain_ref)
        round_n = _next_round(domain_ref)

        # Mark the domain busy with a fresh lease so the domains-sweep leaves this refine-busy
        # domain alone, and heartbeat BOTH docs (the leased refinement and the borrowed domain).
        _mark_domain_running(domain_ref, clock=clock, lease_budget=lease_budget)
        with ExitStack() as stack:
            for ref in (refinement_ref, domain_ref):
                stack.enter_context(
                    lease_heartbeat(
                        ref, clock=clock, interval=heartbeat_interval, lease_budget=lease_budget
                    )
                )
            result = agent.refine(trip, prior)

        dismiss_ids = [c.id for c in prior if c.feedback is Feedback.disliked]
        write_refine_result(
            domain_ref, refinement_ref, result, round=round_n, dismiss_ids=dismiss_ids
        )
        logger.info(
            "completed refine %s (round %d, %d suggestions)", path, round_n, len(result.suggestions)
        )
    except Exception as exc:
        # Same contract as a search: a failed run never crashes the handler. We error the refinement
        # doc we hold and return the domain to idle (its earlier rounds stay viewable / refinable).
        logger.exception("refine failed for %s", path)
        if claimed:
            _fail_refine_safely(refinement_ref, domain_ref, exc)


def _next_round(domain_ref: Any) -> int:
    """The round to tag this refine with: one past the domain's highest completed round."""
    data = domain_ref.get().to_dict() or {}
    return int(data.get("round") or 1) + 1


def _load_prior_candidates(domain_ref: Any) -> list[PriorCandidate]:
    """Read the domain's ``suggested/*`` into :class:`PriorCandidate`s (item + feedback + keys).

    Only the neutral :class:`ResultItem` fields are validated back out of each stored doc (the
    ``lens`` / ``rank`` / ``round`` / ``dismissed`` / ``feedback`` keys and the server ``createdAt``
    are read or dropped separately), so the strict item model never trips on the run-written extras.
    """
    prior: list[PriorCandidate] = []
    for snapshot in domain_ref.collection("suggested").stream():
        data = snapshot.to_dict() or {}
        item = ResultItem.model_validate(
            {k: v for k, v in data.items() if k in ResultItem.model_fields}
        )
        feedback = Feedback(data["feedback"]) if data.get("feedback") else None
        lens = LensName(data["lens"]) if data.get("lens") else None
        prior.append(
            PriorCandidate(
                id=snapshot.id,
                item=item,
                feedback=feedback,
                lens=lens,
                round=int(data.get("round") or 1),
            )
        )
    return prior


def _mark_domain_running(domain_ref: Any, *, clock: Clock, lease_budget) -> None:
    """Flag the domain busy for a refine and refresh its lease (keeps the domains-sweep off it)."""
    domain_ref.update(
        {
            DOMAIN_STATUS_FIELD: "running",
            "leaseExpiresAt": clock() + lease_budget,
            "updatedAt": _SERVER_TIMESTAMP,
        }
    )


def _fail_refine_safely(refinement_ref: Any, domain_ref: Any, exc: BaseException) -> None:
    """Terminal error on the refinement doc + return the domain to ``idle``; failures are logged.

    The domain reset matters because the refine set it ``running``; without it a failed refine would
    strand the domain (and its earlier, still-valid rounds) as perpetually "thinking".
    """
    error = TripError(message=str(exc) or repr(exc), kind=type(exc).__name__)
    try:
        write_run_error(refinement_ref, error, status_field=REFINE_STATUS_FIELD)
    except Exception:
        logger.exception("failed to persist error state for %s", refinement_ref.path)
    try:
        domain_ref.update({DOMAIN_STATUS_FIELD: "idle", "updatedAt": _SERVER_TIMESTAMP})
    except Exception:
        logger.exception("failed to reset domain to idle for %s", domain_ref.path)
