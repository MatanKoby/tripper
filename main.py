"""Cloud Functions (Gen2) entrypoints for the tripper backend.

This module is the composition root: it initializes the Firebase Admin SDK, loads
:class:`~tripper.config.Settings`, builds the active agents, and hands each Firestore ``onCreate``
event to the orchestrator. The reliability machinery lives in ``tripper.orchestrator`` /
``tripper.jobs``; agent wiring is isolated in :func:`build_active_agents` so registering an adapter
never touches the orchestrator core.

Three create-triggered functions drive the M2 flow (``spec/flows.md``):

- :func:`orchestrate` — on a **trip** create, fan out to one ``domains/{domain}`` doc per active
  agent (and mark the trip ``active``).
- :func:`search` — on a **domain** create, run that domain's search and write its ``suggested``.
- :func:`refine` — on a **refinement** create, re-run that domain's agent with the feedback folded
  in and append the next round of ``suggested``.

There is **no scheduled function**. The sweeper (``spec/flows.md`` under *Sweeper*) runs at the head
of :func:`orchestrate` instead of on a Cloud Scheduler job, so it costs nothing while the app sits
idle (``spec/architecture.md`` under *Cost stance*); its logic lives in ``tripper.sweeper``.

Every trigger declares explicit ``memory`` / ``timeout_sec`` / ``max_instances`` / ``concurrency``
as a ceiling against a runaway, and none sets ``min_instances`` (0 is the default and the
discipline). Runs are **serialized**: one instance, one request at a time (``spec/flows.md`` under
*Fan-out concurrency*).
"""

from __future__ import annotations

import logging

from firebase_admin import firestore, initialize_app
from firebase_functions import firestore_fn, options

from tripper.agents.base import Agent
from tripper.config import Settings
from tripper.contract import TripError
from tripper.jobs import write_run_error
from tripper.orchestrator import fan_out, run_refine, run_search
from tripper.sweeper import sweep

# WARNING, not INFO: Cloud Logging's free allotment is per billing account, not per project
# (``spec/architecture.md`` under *Cost stance*).
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("tripper.main")

initialize_app()

#: One trigger covers every user via the ``{userId}`` wildcard (``spec/flows.md``).
TRIP_DOCUMENT = "users/{userId}/trips/{tripId}"

#: The per-domain search trigger: one ``domains/{domain}`` create fires that domain's run.
DOMAIN_DOCUMENT = "users/{userId}/trips/{tripId}/domains/{domain}"

#: The refine trigger: one ``refinements/{refineId}`` create fires that domain's refine run.
REFINEMENT_DOCUMENT = "users/{userId}/trips/{tripId}/domains/{domain}/refinements/{refineId}"

#: Region for every function (``spec/architecture.md``), matching Firestore's own location.
REGION = "us-central1"
#: Worst-case run budget: a Nebius cold start (2 to 3 min) plus the agent loop, capped at the
#: event-triggered Gen2 maximum (``spec/architecture.md`` under *Cold starts & long runs*). The
#: 15-min ``jobs.LEASE_BUDGET`` deliberately outlives it, so a timeout kill is always reapable.
RUN_TIMEOUT_SEC = 540
#: The fan-out itself runs no agent, only adapter construction plus the domain-doc writes.
FAN_OUT_TIMEOUT_SEC = 120
#: Memory every function runs at today (measured from billing: ~0.24 GiB per invocation).
FUNCTION_MEMORY = options.MemoryOption.MB_256
#: One instance, one request at a time, everywhere (``spec/architecture.md`` under *Cost stance*).
#: The pair matters: ``max_instances=1`` alone would still admit up to 80 concurrent requests into
#: the single container, so concurrent runs would contend for one 256 MB heap instead of queueing.
#: Together they serialize the work, which is why a busy moment costs latency and never an OOM.
MAX_INSTANCES = 1
CONCURRENCY = 1


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


@firestore_fn.on_document_created(
    document=TRIP_DOCUMENT,
    region=REGION,
    memory=FUNCTION_MEMORY,
    timeout_sec=FAN_OUT_TIMEOUT_SEC,
    max_instances=MAX_INSTANCES,
    concurrency=CONCURRENCY,
)
def orchestrate(event: firestore_fn.Event[firestore_fn.DocumentSnapshot | None]) -> None:
    """Fire the fan-out when a client creates a trip job under ``users/{userId}/trips``.

    This is also where the sweeper rides (``spec/flows.md`` under *Sweeper*): a trip create is the
    one moment stale runs start to matter, and it keeps the sweep off a Cloud Scheduler job.
    """
    snapshot = event.data
    if snapshot is None:
        logger.warning("trip onCreate event carried no snapshot; ignoring")
        return

    db = firestore.client()
    doc_ref = db.document(snapshot.reference.path)
    # Ahead of Settings(), so a config error cannot also block recovery of earlier stranded runs.
    _sweep_safely(db)
    settings = Settings()
    try:
        fan_out(db, doc_ref, agents=build_active_agents(settings))
    except Exception as exc:
        # The trip errors only if fan-out itself fails (``spec/flows.md``); a per-domain search
        # failure errors only that domain, not the trip.
        logger.exception("fan-out failed for %s", doc_ref.path)
        _mark_trip_error(doc_ref, exc)


@firestore_fn.on_document_created(
    document=DOMAIN_DOCUMENT,
    region=REGION,
    memory=FUNCTION_MEMORY,
    timeout_sec=RUN_TIMEOUT_SEC,
    max_instances=MAX_INSTANCES,
    concurrency=CONCURRENCY,
)
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


@firestore_fn.on_document_created(
    document=REFINEMENT_DOCUMENT,
    region=REGION,
    memory=FUNCTION_MEMORY,
    timeout_sec=RUN_TIMEOUT_SEC,
    max_instances=MAX_INSTANCES,
    concurrency=CONCURRENCY,
)
def refine(event: firestore_fn.Event[firestore_fn.DocumentSnapshot | None]) -> None:
    """Fire a domain's refine run when the client creates a ``refinements/{refineId}`` doc."""
    snapshot = event.data
    if snapshot is None:
        logger.warning("refinement onCreate event carried no snapshot; ignoring")
        return

    db = firestore.client()
    doc_ref = db.document(snapshot.reference.path)
    settings = Settings()
    run_refine(db, doc_ref, agents_by_domain=_agents_by_domain(build_active_agents(settings)))


def _sweep_safely(db: object) -> None:
    """Reap stranded runs ahead of a fan-out; a failure here never blocks the trip.

    The sweep is a backstop (``spec/flows.md`` under *Sweeper*), so it must not take down the work
    it runs in front of. Riding on the trip create is what makes it free: no Cloud Scheduler job,
    and no Firestore reads while the app sits idle (``spec/architecture.md`` under *Cost stance*).
    """
    try:
        report = sweep(db)
    except Exception:
        logger.exception("opportunistic sweep failed; continuing with fan-out")
        return
    if report.failed:
        logger.warning("sweep drove %d stranded run(s) to error", report.failed)


def _mark_trip_error(doc_ref: object, exc: BaseException) -> None:
    """Best-effort terminal trip error when fan-out fails; a failure here is logged, not raised."""
    error = TripError(message=str(exc) or repr(exc), kind=type(exc).__name__)
    try:
        write_run_error(doc_ref, error, status_field="status")
    except Exception:
        logger.exception("failed to persist trip error state for %s", getattr(doc_ref, "path", "?"))
