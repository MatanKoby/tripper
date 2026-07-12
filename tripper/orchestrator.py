"""The trip orchestrator: claim a job, run its agents, write a terminal result.

This is the flow from ``spec/flows.md`` (*M1 job lifecycle*), independent of the Cloud Functions
trigger wiring (that lives in ``main.py``). The reliability primitives it composes are in
``tripper.jobs``; the agents it runs are reached through the ``tripper.agents.base.Agent`` seam.

Contract for the whole run: nothing escapes. A duplicate delivery is skipped, a valid run drives the
doc to ``done``, and any failure (agent raised, invalid output, bad input) drives it to ``error``.
Only a hard crash leaves the doc ``running`` for the lease + sweeper to recover.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from tripper.agents.base import Agent
from tripper.contract import (
    HotelPayload,
    TransportStatus,
    TripError,
    TripInput,
    TripSuggestions,
)
from tripper.jobs import (
    DEFAULT_MAX_ATTEMPTS,
    HEARTBEAT_INTERVAL,
    LEASE_BUDGET,
    Clock,
    claim_job,
    lease_heartbeat,
    utcnow,
    write_done,
    write_error,
)

logger = logging.getLogger("tripper.orchestrator")


def run_job(
    db: Any,
    doc_ref: Any,
    *,
    agents: Sequence[Agent],
    clock: Clock = utcnow,
    lease_budget=LEASE_BUDGET,
    heartbeat_interval: float = HEARTBEAT_INTERVAL,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> None:
    """Drive one trip job to a terminal state. Never raises (the catch-all guards the trigger)."""
    path = doc_ref.path
    claimed = False
    try:
        outcome = claim_job(
            db, doc_ref, clock=clock, lease_budget=lease_budget, max_attempts=max_attempts
        )
        if not outcome.claimed:
            logger.info("skipping %s (%s)", path, outcome.reason)
            return
        claimed = True
        logger.info("claimed %s (attempt %d)", path, outcome.attempts)

        with lease_heartbeat(
            doc_ref, clock=clock, interval=heartbeat_interval, lease_budget=lease_budget
        ):
            results = _run_agents(outcome.input, agents)
        write_done(doc_ref, results)
        logger.info("completed %s", path)
    except Exception as exc:
        # Catch-all: a failed run must not crash the handler (which would trigger redelivery). We
        # persist the error on the doc we hold; a claim/infra failure just logs and lets the lease
        # + sweeper recover.
        logger.exception("job failed for %s", path)
        if claimed:
            _write_error_safely(doc_ref, exc)


def _run_agents(input_data: dict[str, Any] | None, agents: Sequence[Agent]) -> TripSuggestions:
    """Parse the input, run each agent, and assemble the validated transport wrapper."""
    trip = TripInput.from_dict(input_data or {})
    payloads = {agent.name: _as_hotel_payload(agent.run(trip)) for agent in agents}
    return TripSuggestions(status=TransportStatus.ok, hotel=payloads.get("hotel"))


def _as_hotel_payload(value: Any) -> HotelPayload:
    """Validate an agent's output against the contract (accepts a model or a raw dict)."""
    return value if isinstance(value, HotelPayload) else HotelPayload.model_validate(value)


def _write_error_safely(doc_ref: Any, exc: BaseException) -> None:
    """Best-effort terminal error write; a failure here is logged, never re-raised."""
    error = TripError(message=str(exc) or repr(exc), kind=type(exc).__name__)
    try:
        write_error(doc_ref, error)
    except Exception:
        logger.exception("failed to persist error state for %s", doc_ref.path)
