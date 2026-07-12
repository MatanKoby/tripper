"""Cloud Functions (Gen2) entrypoints for the tripper backend.

This module is the composition root: it initializes the Firebase Admin SDK, loads
:class:`~tripper.config.Settings`, builds the active agents, and hands each Firestore ``onCreate``
event to the orchestrator. The reliability machinery lives in ``tripper.orchestrator`` /
``tripper.jobs``; agent wiring is isolated in :func:`build_active_agents` so registering the hotel
adapter (Batch 10) never touches the orchestrator core.

It also registers the scheduled sweeper (``spec/flows.md`` under *Sweeper*), which recovers jobs
stranded in ``running`` after a hard crash; its recovery logic lives in ``tripper.sweeper``.
"""

from __future__ import annotations

import logging

from firebase_admin import firestore, initialize_app
from firebase_functions import firestore_fn, scheduler_fn

from tripper.agents.base import Agent
from tripper.config import Settings
from tripper.orchestrator import run_job
from tripper.sweeper import sweep

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tripper.main")

initialize_app()

#: One trigger covers every user via the ``{userId}`` wildcard (``spec/flows.md``).
TRIP_DOCUMENT = "users/{userId}/trips/{tripId}"

#: How often the sweeper reaps stale ``running`` jobs (``spec/flows.md``: "every minute or few").
#: Well inside the 15-min lease budget, so recovery latency stays a few minutes at most.
SWEEP_SCHEDULE = "every 5 minutes"


def build_active_agents(settings: Settings) -> list[Agent]:
    """The domain agents the orchestrator runs for each trip.

    Empty in Batch 4: the adapter interface ships without a concrete agent. Batch 10 registers the
    hotel adapter here (built from ``settings``). Isolated from the reliability machinery so agent
    wiring changes never reach into the orchestrator.
    """
    return []


@firestore_fn.on_document_created(document=TRIP_DOCUMENT)
def orchestrate(event: firestore_fn.Event[firestore_fn.DocumentSnapshot | None]) -> None:
    """Fire the orchestrator when a client creates a trip job under ``users/{userId}/trips``."""
    snapshot = event.data
    if snapshot is None:
        logger.warning("onCreate event carried no snapshot; ignoring")
        return

    db = firestore.client()
    doc_ref = db.document(snapshot.reference.path)
    settings = Settings()
    run_job(db, doc_ref, agents=build_active_agents(settings))


@scheduler_fn.on_schedule(schedule=SWEEP_SCHEDULE)
def sweep_stuck_jobs(event: scheduler_fn.ScheduledEvent) -> None:
    """Scheduled backstop: recover jobs stranded in ``running`` past their lease (``flows.md``).

    Region defaults to ``us-central1`` (``spec/architecture.md``), matching the orchestrator and
    the rest of the GCP footprint; the Cloud Scheduler job is created by the deploy (Batch 8).
    """
    db = firestore.client()
    report = sweep(db)
    logger.info("sweep_stuck_jobs done: %s", report)
