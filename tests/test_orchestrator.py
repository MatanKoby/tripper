"""Fan-out + per-domain search-run tests, driven against the Firestore emulator (``spec/flows.md``).

The agent is a test double (an in-test fake, not a shipped mock agent): the orchestrator only sees
the ``Agent`` interface, so a fake exercises the whole reliability path without any real agent.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from tripper.agents.base import Agent, DomainSearchResult, Suggestion
from tripper.contract import Domain, ResultItem, SelectionMode, TripInput
from tripper.jobs import claim_job, lease_heartbeat
from tripper.orchestrator import fan_out, run_search

VALID_INPUT: dict = {
    "place": {"city": "Porto", "country_code": "PT"},
    "stay": {"check_in": "2026-09-10", "check_out": "2026-09-12"},
}


def _sample_result(n: int = 2) -> DomainSearchResult:
    return DomainSearchResult(
        suggestions=[
            Suggestion(id=f"s{i}", item=ResultItem(title=f"Item {i}", score=0.5), lens=None)
            for i in range(n)
        ],
        diagnostics={"scorer": "fake"},
        warnings=["heads up"],
        counts={"total": n},
    )


class FakeAgent(Agent):
    """An accommodations agent stand-in that records its calls and returns/raises what it's told."""

    domain = Domain.accommodations
    selection_mode = SelectionMode.single

    def __init__(self, *, result: DomainSearchResult | None = None, error: Exception | None = None):
        self._result = result if result is not None else _sample_result()
        self._error = error
        self.calls = 0

    def run(self, trip: TripInput) -> DomainSearchResult:
        self.calls += 1
        assert isinstance(trip, TripInput)
        if self._error is not None:
            raise self._error
        return self._result


def _now() -> datetime:
    return datetime.now(UTC)


def _make_trip(db, data: dict) -> object:
    ref = db.collection("users").document("u1").collection("trips").document()
    ref.set(data)
    return ref


def _pending_trip(db, *, input_data: dict | None = None) -> object:
    return _make_trip(db, {"input": input_data or VALID_INPUT, "status": "pending"})


def _domain_ref(trip_ref: object, domain: str = "accommodations") -> object:
    return trip_ref.collection("domains").document(domain)


# --- fan-out ----------------------------------------------------------------------------------


def test_fan_out_activates_trip_and_creates_domain_docs(db) -> None:
    trip_ref = _pending_trip(db)

    fan_out(db, trip_ref, agents=[FakeAgent()])

    assert trip_ref.get().to_dict()["status"] == "active"
    domain = _domain_ref(trip_ref).get().to_dict()
    assert domain["domain"] == "accommodations"
    assert domain["agentStatus"] == "pending"
    assert domain["selectionMode"] == "single"
    assert domain["round"] == 0


def test_fan_out_skips_when_not_pending(db) -> None:
    trip_ref = _make_trip(db, {"input": VALID_INPUT, "status": "active"})

    fan_out(db, trip_ref, agents=[FakeAgent()])

    assert not _domain_ref(trip_ref).get().exists  # already fanned out; nothing created


def test_fan_out_does_not_reset_an_existing_domain(db) -> None:
    trip_ref = _pending_trip(db)
    fan_out(db, trip_ref, agents=[FakeAgent()])
    _domain_ref(trip_ref).update({"agentStatus": "running"})

    # A duplicate trip delivery (still "active") must not re-create / reset the domain doc.
    fan_out(db, trip_ref, agents=[FakeAgent()])

    assert _domain_ref(trip_ref).get().to_dict()["agentStatus"] == "running"


# --- search run: happy path -------------------------------------------------------------------


def test_search_drives_domain_to_idle_with_suggestions(db) -> None:
    trip_ref = _pending_trip(db)
    agent = FakeAgent()
    fan_out(db, trip_ref, agents=[agent])
    domain_ref = _domain_ref(trip_ref)

    run_search(db, domain_ref, agents_by_domain={"accommodations": agent})

    assert agent.calls == 1
    domain = domain_ref.get().to_dict()
    assert domain["agentStatus"] == "idle"
    assert domain["round"] == 1
    assert domain["attempts"] == 1
    assert domain["diagnostics"]["scorer"] == "fake"
    assert domain["warnings"] == ["heads up"]
    assert domain["counts"]["total"] == 2

    suggested = {s.id: s.to_dict() for s in domain_ref.collection("suggested").stream()}
    assert set(suggested) == {"s0", "s1"}
    assert suggested["s0"]["title"] == "Item 0"
    assert suggested["s0"]["round"] == 1
    assert suggested["s0"]["rank"] == 0
    assert suggested["s0"]["feedback"] is None


# --- search run: idempotency ------------------------------------------------------------------


def test_duplicate_delivery_does_not_double_run(db) -> None:
    trip_ref = _pending_trip(db)
    agent = FakeAgent()
    fan_out(db, trip_ref, agents=[agent])
    domain_ref = _domain_ref(trip_ref)

    run_search(db, domain_ref, agents_by_domain={"accommodations": agent})
    run_search(db, domain_ref, agents_by_domain={"accommodations": agent})  # redelivery

    assert agent.calls == 1  # the second delivery finds the domain idle and skips
    assert domain_ref.get().to_dict()["agentStatus"] == "idle"


def test_running_search_with_live_lease_is_skipped(db) -> None:
    trip_ref = _pending_trip(db)
    domain_ref = _domain_ref(trip_ref)
    domain_ref.set(
        {
            "domain": "accommodations",
            "agentStatus": "running",
            "attempts": 1,
            "leaseExpiresAt": _now() + timedelta(minutes=10),
        }
    )
    agent = FakeAgent()

    run_search(db, domain_ref, agents_by_domain={"accommodations": agent})

    assert agent.calls == 0
    assert domain_ref.get().to_dict()["agentStatus"] == "running"


def test_expired_lease_is_reclaimed(db) -> None:
    trip_ref = _pending_trip(db)
    domain_ref = _domain_ref(trip_ref)
    domain_ref.set(
        {
            "domain": "accommodations",
            "agentStatus": "running",
            "attempts": 1,
            "leaseExpiresAt": _now() - timedelta(minutes=1),
        }
    )
    agent = FakeAgent()

    run_search(db, domain_ref, agents_by_domain={"accommodations": agent})

    data = domain_ref.get().to_dict()
    assert agent.calls == 1
    assert data["agentStatus"] == "idle"
    assert data["attempts"] == 2  # the reclaim counts as another attempt


# --- search run: failure handling -------------------------------------------------------------


def test_agent_exception_yields_error(db) -> None:
    trip_ref = _pending_trip(db)
    agent = FakeAgent(error=RuntimeError("boom"))
    fan_out(db, trip_ref, agents=[agent])
    domain_ref = _domain_ref(trip_ref)

    run_search(db, domain_ref, agents_by_domain={"accommodations": agent})

    data = domain_ref.get().to_dict()
    assert data["agentStatus"] == "error"
    assert data["attempts"] == 1
    assert data["error"] == {"message": "boom", "kind": "RuntimeError"}
    assert data["lastError"] == "boom"


def test_unknown_domain_yields_error(db) -> None:
    trip_ref = _pending_trip(db)
    fan_out(db, trip_ref, agents=[FakeAgent()])
    domain_ref = _domain_ref(trip_ref)

    run_search(db, domain_ref, agents_by_domain={})  # no agent registered for this domain

    data = domain_ref.get().to_dict()
    assert data["agentStatus"] == "error"
    assert data["error"]["kind"] == "ValueError"


def test_malformed_input_yields_error(db) -> None:
    trip_ref = _make_trip(
        db, {"input": {"place": {"desired_area": "downtown"}}, "status": "pending"}
    )
    agent = FakeAgent()
    fan_out(db, trip_ref, agents=[agent])
    domain_ref = _domain_ref(trip_ref)

    run_search(db, domain_ref, agents_by_domain={"accommodations": agent})

    data = domain_ref.get().to_dict()
    assert data["agentStatus"] == "error"
    assert agent.calls == 0  # input is parsed before the agent runs


# --- claim + lease primitives -----------------------------------------------------------------


def test_claim_seeds_reliability_fields_on_agent_status(db) -> None:
    trip_ref = _pending_trip(db)
    domain_ref = _domain_ref(trip_ref)
    domain_ref.set({"domain": "accommodations", "agentStatus": "pending"})

    outcome = claim_job(db, domain_ref, status_field="agentStatus")

    assert outcome.claimed is True
    assert outcome.attempts == 1
    data = domain_ref.get().to_dict()
    assert data["agentStatus"] == "running"
    assert data["maxAttempts"] == 3
    assert data["startedAt"] is not None
    assert data["leaseExpiresAt"] > _now()


def test_claim_of_missing_doc_is_not_claimed(db) -> None:
    ref = db.collection("users").document("u1").collection("trips").document("nope")

    outcome = claim_job(db, ref, status_field="agentStatus")

    assert outcome.claimed is False
    assert outcome.reason == "missing"


def test_lease_heartbeat_bumps_the_lease(db) -> None:
    trip_ref = _pending_trip(db)
    domain_ref = _domain_ref(trip_ref)
    domain_ref.set({"agentStatus": "running", "leaseExpiresAt": _now()})
    before = domain_ref.get().to_dict()["leaseExpiresAt"]

    with lease_heartbeat(domain_ref, interval=0.05, lease_budget=timedelta(minutes=5)):
        time.sleep(0.25)

    after = domain_ref.get().to_dict()["leaseExpiresAt"]
    assert after > before
