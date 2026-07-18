"""Activities-adapter contract tests (``spec/schema.md``, ``spec/agents.md``).

Non-e2e: the vendored travel-agent runs on its keyless **mock** provider (deterministic
recommendations + itinerary, no LLM/network), so nothing here needs a key. The module is skipped
when the agent submodule is not installed (``pip install -e vendor/agents/travel-agent``).

Covered: ``TripInput`` -> the agent's ``start`` trip dict (destination + dates + travelers +
budget default + interests + pace), the per-round collection of ``RecommendedActivity`` items into
neutral ``ResultItem`` candidates, a full stateless ``run`` driven to a completed itinerary, and an
orchestrator integration.
"""

from __future__ import annotations

import pytest

pytest.importorskip("travel_agent", reason="travel-agent submodule not installed")

from tripper.agents.activities_adapter import (  # noqa: E402
    DEFAULT_ACTIVITIES_BUDGET_USD,
    ActivitiesAdapter,
    _activity_to_item,
    _collect_round,
    _fold_feedback,
    _require_ok,
    _to_trip_request,
    _travelers,
)
from tripper.agents.base import DomainSearchResult, PriorCandidate, Suggestion  # noqa: E402
from tripper.config import Settings  # noqa: E402
from tripper.contract import (  # noqa: E402
    Domain,
    Feedback,
    PricePer,
    ResultItem,
    SelectionMode,
    TripInput,
)
from tripper.orchestrator import fan_out, run_refine, run_search  # noqa: E402

BASE_INPUT: dict = {
    "place": {"city": "Kyoto", "country_code": "JP"},
    "stay": {"check_in": "2026-09-10", "check_out": "2026-09-13", "currency": "USD"},
    "activities_budget_usd": 1200,
    "interests": ["culture", "food"],
    "travel_style": "packed",
}


def _trip(**overrides) -> TripInput:
    return TripInput.from_dict({**BASE_INPUT, **overrides})


def _settings() -> Settings:
    return Settings(gcp_project="demo-tripper")


# --- static wiring ----------------------------------------------------------------------------


def test_domain_and_selection_mode() -> None:
    adapter = ActivitiesAdapter(_settings())
    assert adapter.domain is Domain.activities
    assert adapter.selection_mode is SelectionMode.multi
    assert adapter.supports_refine is True  # refine = a fresh run with the feedback folded in


# --- request mapping --------------------------------------------------------------------------


def test_trip_request_maps_shared_context_and_activities_fields() -> None:
    request = _to_trip_request(_trip(guests={"adults": 3, "children_ages": [6]}))

    assert request == {
        "destination": "Kyoto",
        "start_date": "2026-09-10",
        "end_date": "2026-09-13",
        "budget_usd": 1200,
        "travelers": 4,  # 3 adults + 1 child
        "travel_style": "packed",
        "interests": ["culture", "food"],
    }


def test_budget_defaults_when_null() -> None:
    request = _to_trip_request(_trip(activities_budget_usd=None))
    assert request["budget_usd"] == DEFAULT_ACTIVITIES_BUDGET_USD


def test_interests_omitted_when_null_so_agent_defaults() -> None:
    request = _to_trip_request(_trip(interests=None))
    assert "interests" not in request  # agent applies its own default (culture, food)


def test_destination_falls_back_to_place_text() -> None:
    request = _to_trip_request(_trip(place={"text": "Kyoto, Japan"}))
    assert request is not None
    assert request["destination"] == "Kyoto, Japan"


def test_center_only_place_has_no_destination() -> None:
    assert _to_trip_request(_trip(place={"center": {"lat": 35.0, "lon": 135.7}})) is None


def test_travelers_clamped_to_agent_range() -> None:
    assert _travelers(_trip(guests={"adults": 2})) == 2
    big = _trip(guests={"adults": 20, "children_ages": list(range(5))})
    assert _travelers(big) == 20  # clamped to the agent's max


# --- per-round collection + item mapping ------------------------------------------------------


def test_collect_round_appends_suggestions_and_returns_names() -> None:
    response = {
        "recommendations": {
            "category": "culture",
            "round": 1,
            "recommendations": [
                {"name": "Kinkaku-ji", "estimated_cost_usd": 5.0, "reservation_required": True,
                 "description": "Golden Pavilion"},
                {"name": "Nijo Castle"},
            ],
        }
    }
    suggestions: list[Suggestion] = []
    per_category: dict[str, int] = {}

    category, names = _collect_round(response, suggestions, per_category)

    assert category == "culture"
    assert names == ["Kinkaku-ji", "Nijo Castle"]
    assert [s.id for s in suggestions] == ["culture-0", "culture-1"]
    assert per_category == {"culture": 2}

    top = suggestions[0].item
    assert top.title == "Kinkaku-ji"
    assert top.subtitle == "culture"
    assert top.price.amount == 5.0
    assert top.price.per is PricePer.person
    assert top.price.currency == "USD"
    assert top.badges == ["reservation required"]
    assert top.rationale == "Golden Pavilion"
    assert top.url is None  # RecommendedActivity carries no booking link
    assert top.detail["category"] == "culture"


def test_activity_without_cost_has_no_price() -> None:
    item = _activity_to_item({"name": "Free walk"}, "culture")
    assert item.price is None
    assert item.badges == []


def test_require_ok_raises_on_agent_error() -> None:
    with pytest.raises(RuntimeError, match="activities agent error"):
        _require_ok({"status": "error", "error": "boom"})


# --- full stateless run (mock provider) -------------------------------------------------------


def test_run_drives_to_completion_and_maps_activities() -> None:
    result = ActivitiesAdapter(_settings()).run(_trip())

    assert isinstance(result, DomainSearchResult)
    assert result.suggestions, "the mock provider should recommend activities"
    first = result.suggestions[0].item
    assert first.title
    assert first.subtitle  # its category
    # Driven to a completed itinerary, stored on diagnostics for rendering.
    assert result.diagnostics["status"] == "completed"
    assert "itinerary" in result.diagnostics
    assert result.counts["total"] == len(result.suggestions)
    assert sum(result.counts["per_category"].values()) == len(result.suggestions)


def test_run_without_destination_is_a_clean_empty_outcome() -> None:
    trip = _trip(place={"center": {"lat": 35.0, "lon": 135.7}})
    result = ActivitiesAdapter(_settings()).run(trip)
    assert result.suggestions == []
    assert result.warnings


# --- refine (feedback folded into a fresh start request) --------------------------------------


def _marked(title: str, category: str, feedback: Feedback) -> PriorCandidate:
    item = ResultItem(title=title, subtitle=category, detail={"category": category})
    return PriorCandidate(id=f"{category}-0", item=item, feedback=feedback)


def test_fold_feedback_adjusts_interests_and_notes() -> None:
    request = {"destination": "Kyoto", "interests": ["culture", "food"], "travel_style": "packed"}
    prior = [
        _marked("Kinkaku-ji", "culture", Feedback.disliked),
        _marked("Nishiki Market", "food", Feedback.liked),
        _marked("Arashiyama", "nature", Feedback.liked),  # gains a group not originally selected
    ]

    _fold_feedback(request, prior)

    # culture dropped (disliked), food kept (liked), nature added (liked); declaration order.
    assert request["interests"] == ["nature", "food"]
    assert "Prioritize activities like: Nishiki Market, Arashiyama." in request["notes"]
    assert "Avoid activities like: Kinkaku-ji." in request["notes"]


def test_fold_feedback_drops_interests_when_all_disliked() -> None:
    request = {"destination": "Kyoto", "interests": ["culture"]}
    _fold_feedback(request, [_marked("Kinkaku-ji", "culture", Feedback.disliked)])
    # Every interest dropped -> the key is omitted so the agent re-applies its own default.
    assert "interests" not in request
    assert "Avoid activities like: Kinkaku-ji." in request["notes"]


def test_fold_feedback_no_marks_is_a_noop() -> None:
    request = {"destination": "Kyoto", "interests": ["culture", "food"]}
    _fold_feedback(request, [])
    assert request == {"destination": "Kyoto", "interests": ["culture", "food"]}


def test_refine_drives_to_completion_with_feedback() -> None:
    adapter = ActivitiesAdapter(_settings())
    base = adapter.run(_trip())
    # Dislike everything culture, like everything food.
    prior = [
        PriorCandidate(
            id=s.id,
            item=s.item,
            feedback=Feedback.disliked if s.item.subtitle == "culture" else Feedback.liked,
        )
        for s in base.suggestions
    ]

    refined = adapter.refine(_trip(), prior)

    assert isinstance(refined, DomainSearchResult)
    assert refined.suggestions
    assert refined.diagnostics["status"] == "completed"
    # culture was disliked away, so the refined round should not recommend culture activities.
    assert "culture" not in {s.item.subtitle for s in refined.suggestions}


# --- fan-out + search integration (emulator-backed; skips without one) -------------------------


def test_fan_out_and_search_populate_activities(db) -> None:
    trip_ref = db.collection("users").document("u1").collection("trips").document()
    trip_ref.set({"input": BASE_INPUT, "status": "pending"})
    adapter = ActivitiesAdapter(_settings())

    fan_out(db, trip_ref, agents=[adapter])
    domain_ref = trip_ref.collection("domains").document("activities")
    run_search(db, domain_ref, agents_by_domain={"activities": adapter})

    domain = domain_ref.get().to_dict()
    assert domain["agentStatus"] == "idle"
    assert domain["round"] == 1
    assert domain["selectionMode"] == "multi"
    suggested = list(domain_ref.collection("suggested").stream())
    assert suggested, "search should write at least one recommended activity"
    first = suggested[0].to_dict()
    assert first["title"]
    assert first["round"] == 1


def test_fan_out_search_and_refine_append_round_two(db) -> None:
    # The full loop against the real agent + emulator: search, feedback, refine, append round 2.
    trip_ref = db.collection("users").document("u1").collection("trips").document()
    trip_ref.set({"input": BASE_INPUT, "status": "pending"})
    adapter = ActivitiesAdapter(_settings())

    fan_out(db, trip_ref, agents=[adapter])
    domain_ref = trip_ref.collection("domains").document("activities")
    run_search(db, domain_ref, agents_by_domain={"activities": adapter})

    # Dislike the round-1 culture picks so the refine drops the whole group (interests + notes).
    round_one = {s.id: s.to_dict() for s in domain_ref.collection("suggested").stream()}
    for sid, data in round_one.items():
        if data.get("subtitle") == "culture":
            domain_ref.collection("suggested").document(sid).update({"feedback": "disliked"})

    refine_ref = domain_ref.collection("refinements").document("rf1")
    refine_ref.set({"round": 2, "status": "pending"})
    run_refine(db, refine_ref, agents_by_domain={"activities": adapter})

    assert refine_ref.get().to_dict()["status"] == "done"
    domain = domain_ref.get().to_dict()
    assert domain["agentStatus"] == "idle"
    assert domain["round"] == 2

    all_docs = {s.id: s.to_dict() for s in domain_ref.collection("suggested").stream()}
    round_two = {sid: d for sid, d in all_docs.items() if d.get("round") == 2}
    assert round_two, "refine should append a round-2 batch"
    assert all(sid.endswith("::r2") for sid in round_two), "round 2 uses round-qualified ids"
    # The disliked round-1 culture picks are now hidden.
    culture_ids = [sid for sid, d in round_one.items() if d["subtitle"] == "culture"]
    assert culture_ids and all(all_docs[sid]["dismissed"] for sid in culture_ids)
    assert "culture" not in {d["subtitle"] for d in round_two.values()}
