"""Orchestrator + claim/lease tests, driven against the Firestore emulator (``spec/flows.md``).

The agent is a test double (an in-test fake, not a shipped mock agent): the orchestrator only sees
the ``Agent`` interface, so a fake exercises the whole reliability path without any real agent.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from tripper.agents.base import Agent
from tripper.contract import HotelPayload, TripInput
from tripper.jobs import claim_job, lease_heartbeat
from tripper.orchestrator import run_job

VALID_INPUT: dict = {
    "place": {"city": "Porto", "country_code": "PT"},
    "stay": {"check_in": "2026-09-10", "check_out": "2026-09-12"},
}

SAMPLE_PAYLOAD: dict = {
    "agent_status": "ok",
    "resolved": {"city": "Porto", "currency": "EUR"},
    "diagnostics": {"scorer": "heuristic", "providers_used": ["mock"]},
    "lenses": {"stratified_best": [{"name": "Hotel Porto", "score": 0.9, "rationale": "great"}]},
}


class FakeHotelAgent(Agent):
    """A hotel agent stand-in that records its calls and returns/raises what it's told to."""

    name = "hotel"

    def __init__(self, *, payload: object = None, error: Exception | None = None) -> None:
        self._payload = payload if payload is not None else HotelPayload.from_dict(SAMPLE_PAYLOAD)
        self._error = error
        self.calls = 0

    def run(self, trip: TripInput) -> HotelPayload:
        self.calls += 1
        assert isinstance(trip, TripInput)
        if self._error is not None:
            raise self._error
        return self._payload  # type: ignore[return-value]


def _now() -> datetime:
    return datetime.now(UTC)


def _make_trip(db, data: dict) -> object:
    ref = db.collection("users").document("u1").collection("trips").document()
    ref.set(data)
    return ref


def _pending(db, *, input_data: dict | None = None) -> object:
    return _make_trip(db, {"input": input_data or VALID_INPUT, "status": "pending", "attempts": 0})


# --- happy path -------------------------------------------------------------------------------


def test_pending_job_drives_to_done(db) -> None:
    ref = _pending(db)
    agent = FakeHotelAgent()

    run_job(db, ref, agents=[agent])

    data = ref.get().to_dict()
    assert agent.calls == 1
    assert data["status"] == "done"
    assert data["attempts"] == 1
    assert data["results"]["status"] == "ok"
    assert data["results"]["hotel"]["lenses"]["stratified_best"][0]["name"] == "Hotel Porto"
    assert data.get("error") is None


# --- idempotency ------------------------------------------------------------------------------


def test_duplicate_delivery_does_not_double_run(db) -> None:
    ref = _pending(db)
    agent = FakeHotelAgent()

    run_job(db, ref, agents=[agent])
    run_job(db, ref, agents=[agent])  # at-least-once redelivery of the same create

    assert agent.calls == 1  # the second delivery finds the job already done and skips
    assert ref.get().to_dict()["status"] == "done"


def test_running_job_with_live_lease_is_skipped(db) -> None:
    ref = _make_trip(
        db,
        {
            "input": VALID_INPUT,
            "status": "running",
            "attempts": 1,
            "leaseExpiresAt": _now() + timedelta(minutes=10),
        },
    )
    agent = FakeHotelAgent()

    run_job(db, ref, agents=[agent])

    assert agent.calls == 0
    assert ref.get().to_dict()["status"] == "running"


def test_expired_lease_is_reclaimed(db) -> None:
    ref = _make_trip(
        db,
        {
            "input": VALID_INPUT,
            "status": "running",
            "attempts": 1,
            "leaseExpiresAt": _now() - timedelta(minutes=1),
        },
    )
    agent = FakeHotelAgent()

    run_job(db, ref, agents=[agent])

    data = ref.get().to_dict()
    assert agent.calls == 1
    assert data["status"] == "done"
    assert data["attempts"] == 2  # the reclaim counts as another attempt


# --- failure handling -------------------------------------------------------------------------


def test_agent_exception_yields_error(db) -> None:
    ref = _pending(db)
    agent = FakeHotelAgent(error=RuntimeError("boom"))

    run_job(db, ref, agents=[agent])

    data = ref.get().to_dict()
    assert data["status"] == "error"
    assert data["attempts"] == 1
    assert data["error"] == {"message": "boom", "kind": "RuntimeError"}
    assert data["lastError"] == "boom"
    assert "results" not in data


def test_invalid_agent_output_yields_error(db) -> None:
    ref = _pending(db)
    agent = FakeHotelAgent(payload={"agent_status": "ok"})  # missing resolved/diagnostics

    run_job(db, ref, agents=[agent])

    data = ref.get().to_dict()
    assert data["status"] == "error"
    assert data["error"]["kind"] == "ValidationError"


def test_malformed_input_yields_error(db) -> None:
    ref = _pending(db, input_data={"place": {"desired_area": "downtown"}})  # no locator, no stay
    agent = FakeHotelAgent()

    run_job(db, ref, agents=[agent])

    data = ref.get().to_dict()
    assert data["status"] == "error"
    assert agent.calls == 0  # input is parsed before any agent runs


# --- claim + lease primitives -----------------------------------------------------------------


def test_claim_seeds_reliability_fields(db) -> None:
    ref = _pending(db)

    outcome = claim_job(db, ref)

    assert outcome.claimed is True
    assert outcome.attempts == 1
    data = ref.get().to_dict()
    assert data["status"] == "running"
    assert data["maxAttempts"] == 3
    assert data["startedAt"] is not None
    assert data["leaseExpiresAt"] > _now()


def test_claim_of_missing_doc_is_not_claimed(db) -> None:
    ref = db.collection("users").document("u1").collection("trips").document("nope")

    outcome = claim_job(db, ref)

    assert outcome.claimed is False
    assert outcome.reason == "missing"


def test_lease_heartbeat_bumps_the_lease(db) -> None:
    ref = _pending(db)
    ref.update({"status": "running", "leaseExpiresAt": _now()})
    before = ref.get().to_dict()["leaseExpiresAt"]

    with lease_heartbeat(ref, interval=0.05, lease_budget=timedelta(minutes=5)):
        time.sleep(0.25)

    after = ref.get().to_dict()["leaseExpiresAt"]
    assert after > before
