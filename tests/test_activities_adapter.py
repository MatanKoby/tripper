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
    _require_ok,
    _to_trip_request,
    _travelers,
)
from tripper.agents.base import DomainSearchResult, Suggestion  # noqa: E402
from tripper.config import Settings  # noqa: E402
from tripper.contract import Domain, PricePer, SelectionMode, TripInput  # noqa: E402
from tripper.orchestrator import fan_out, run_search  # noqa: E402

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
