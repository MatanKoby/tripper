"""Cloud Functions (Gen2) entrypoints for the tripper backend.

This module is the composition root: it initializes the Firebase Admin SDK, loads
:class:`~tripper.config.Settings`, builds the active agents, and hands each Firestore ``onCreate``
event to the orchestrator. The reliability machinery lives in ``tripper.orchestrator`` /
``tripper.jobs``; agent wiring is isolated in :func:`build_active_agents` so registering an adapter
never touches the orchestrator core.

Two create-triggered functions drive the M2 fan-out (``spec/flows.md``):

- :func:`orchestrate` — on a **trip** create, fan out to one ``domains/{domain}`` doc per active
  agent (and mark the trip ``active``).
- :func:`search` — on a **domain** create, run that domain's search and write its ``suggested``.

It also registers the scheduled sweeper (``spec/flows.md`` under *Sweeper*), which recovers domain
search runs stranded in ``running`` after a hard crash; its recovery logic lives in
``tripper.sweeper``.
"""

from __future__ import annotations

import logging

from firebase_admin import firestore, initialize_app
from firebase_functions import firestore_fn, scheduler_fn

from tripper.agents.base import Agent
from tripper.config import Settings
from tripper.contract import TripError
from tripper.jobs import write_run_error
from tripper.orchestrator import fan_out, run_search
from tripper.sweeper import sweep

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tripper.main")

initialize_app()

#: One trigger covers every user via the ``{userId}`` wildcard (``spec/flows.md``).
TRIP_DOCUMENT = "users/{userId}/trips/{tripId}"

#: The per-domain search trigger: one ``domains/{domain}`` create fires that domain's run.
DOMAIN_DOCUMENT = "users/{userId}/trips/{tripId}/domains/{domain}"

#: How often the sweeper reaps stale ``running`` runs (``spec/flows.md``: "every minute or few").
#: Well inside the 15-min lease budget, so recovery latency stays a few minutes at most.
SWEEP_SCHEDULE = "every 5 minutes"


def build_active_agents(settings: Settings) -> list[Agent]:
    """The domain agents the orchestrator runs for each trip.

    M2 fans out to all three domains: accommodations, flights, and activities. The imports are
    function-local so importing this module never requires a vendored agent submodule
    (``spec/agents.md``); they are resolved at trigger time, where the deploy has vendored them.
    Isolated from the reliability machinery so agent wiring never reaches into the orchestrator.
    """
    from tripper.agents.activities_adapter import ActivitiesAdapter
    from tripper.agents.flight_adapter import FlightAdapter
    from tripper.agents.hotel_adapter import HotelAdapter

    return [HotelAdapter(settings), FlightAdapter(settings), ActivitiesAdapter(settings)]


def _agents_by_domain(agents: list[Agent]) -> dict[str, Agent]:
    """Index the active agents by their domain value, for the search trigger to dispatch on."""
    return {agent.domain.value: agent for agent in agents}


@firestore_fn.on_document_created(document=TRIP_DOCUMENT)
def orchestrate(event: firestore_fn.Event[firestore_fn.DocumentSnapshot | None]) -> None:
    """Fire the fan-out when a client creates a trip job under ``users/{userId}/trips``."""
    snapshot = event.data
    if snapshot is None:
        logger.warning("trip onCreate event carried no snapshot; ignoring")
        return

    db = firestore.client()
    doc_ref = db.document(snapshot.reference.path)
    settings = Settings()
    try:
        fan_out(db, doc_ref, agents=build_active_agents(settings))
    except Exception as exc:
        # The trip errors only if fan-out itself fails (``spec/flows.md``); a per-domain search
        # failure errors only that domain, not the trip.
        logger.exception("fan-out failed for %s", doc_ref.path)
        _mark_trip_error(doc_ref, exc)


@firestore_fn.on_document_created(document=DOMAIN_DOCUMENT)
def search(event: firestore_fn.Event[firestore_fn.DocumentSnapshot | None]) -> None:
    """Fire a domain's search run when the fan-out creates its ``domains/{domain}`` doc."""
    snapshot = event.data
    if snapshot is None:
        logger.warning("domain onCreate event carried no snapshot; ignoring")
        return

    db = firestore.client()
    doc_ref = db.document(snapshot.reference.path)
    settings = Settings()
    run_search(db, doc_ref, agents_by_domain=_agents_by_domain(build_active_agents(settings)))


@scheduler_fn.on_schedule(schedule=SWEEP_SCHEDULE)
def sweep_stuck_jobs(event: scheduler_fn.ScheduledEvent) -> None:
    """Scheduled backstop: recover domain search runs stranded in ``running`` past their lease.

    Region defaults to ``us-central1`` (``spec/architecture.md``), matching the orchestrator and the
    rest of the GCP footprint; the Cloud Scheduler job is created by the deploy (Batch 8).
    """
    db = firestore.client()
    report = sweep(db)
    logger.info("sweep_stuck_jobs done: %s", report)


def _mark_trip_error(doc_ref: object, exc: BaseException) -> None:
    """Best-effort terminal trip error when fan-out fails; a failure here is logged, not raised."""
    error = TripError(message=str(exc) or repr(exc), kind=type(exc).__name__)
    try:
        write_run_error(doc_ref, error, status_field="status")
    except Exception:
        logger.exception("failed to persist trip error state for %s", getattr(doc_ref, "path", "?"))
