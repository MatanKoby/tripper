"""Flight-adapter contract tests (``spec/schema.md``, ``spec/agents.md``).

Non-e2e: the vendored flight agent runs on its keyless defaults (offline **simulated** pricing, no
LLM — tripper always passes a structured origin/destination), so nothing here needs a token or a
network round-trip. The module is skipped when the agent submodule is not installed
(``pip install -e vendor/agents/flight-finder-agent``).

Two directions are exercised: ``TripInput`` -> the agent's request dict (route + stay-dates-as-round
-trip + USD budget), and the agent's result -> tripper's neutral ``ResultItem`` candidates
(one per market offer, cheapest first). A full ``run`` and an orchestrator integration round it out.
"""

from __future__ import annotations

import pytest

pytest.importorskip("flight_finder", reason="flight-finder agent submodule not installed")

from tripper.agents.base import DomainSearchResult  # noqa: E402
from tripper.agents.flight_adapter import (  # noqa: E402
    FlightAdapter,
    _to_request,
    _to_result,
)
from tripper.config import Settings  # noqa: E402
from tripper.contract import Domain, PricePer, SelectionMode, TripInput  # noqa: E402
from tripper.orchestrator import fan_out, run_search  # noqa: E402

BASE_INPUT: dict = {
    "place": {"city": "New York", "country_code": "US"},
    "stay": {"check_in": "2026-09-10", "check_out": "2026-09-17", "currency": "USD"},
    "origin": "Tel Aviv",
    "flight_budget_usd": 900,
}


def _trip(**overrides) -> TripInput:
    return TripInput.from_dict({**BASE_INPUT, **overrides})


def _settings() -> Settings:
    return Settings(gcp_project="demo-tripper")


# --- static wiring ----------------------------------------------------------------------------


def test_domain_and_selection_mode() -> None:
    adapter = FlightAdapter(_settings())
    assert adapter.domain is Domain.flights
    assert adapter.selection_mode is SelectionMode.single


# --- request mapping --------------------------------------------------------------------------


def test_request_maps_route_dates_and_budget() -> None:
    request = _to_request(_trip())

    assert request == {
        "origin": "Tel Aviv",
        "destination": "New York",  # place.city
        "budget": 900,
        "departure_date": "2026-09-10",  # stay.check_in
        "return_date": "2026-09-17",  # stay.check_out -> round trip
    }


def test_destination_falls_back_to_place_text() -> None:
    request = _to_request(_trip(place={"text": "Paris, France"}))
    assert request is not None
    assert request["destination"] == "Paris, France"


def test_missing_origin_is_unroutable() -> None:
    # origin omitted -> the adapter can't build a valid structured request.
    assert _to_request(_trip(origin=None)) is None


def test_center_only_destination_is_unroutable() -> None:
    # A center-only place has no name/IATA the flight agent accepts.
    assert _to_request(_trip(place={"center": {"lat": 40.7, "lon": -74.0}})) is None


# --- result mapping ---------------------------------------------------------------------------


def _sample_result() -> dict:
    return {
        "ok": True,
        "query": {
            "origin": {"input": "Tel Aviv", "code": "TLV", "name": "Tel Aviv-Yafo"},
            "destination": {"input": "New York", "code": "NYC", "name": "New York"},
            "departure_date": "2026-09-10",
            "return_date": "2026-09-17",
            "trip_type": "round_trip",
            "budget_usd": 900,
        },
        "pricing_source": "simulated",
        "offers": [
            {
                "price_usd": 410.31,
                "country": "FR",
                "market": "fr",
                "departure_at": "2026-09-10",
                "return_at": "2026-09-17",
                "within_budget": True,
                "links": {"google_flights": "https://g/fr", "skyscanner": "https://s/fr"},
            },
            {
                "price_usd": 1200.0,
                "country": "US",
                "market": "us",
                "departure_at": "2026-09-10",
                "return_at": "2026-09-17",
                "within_budget": False,
                "links": {"google_flights": None, "skyscanner": "https://s/us"},
            },
        ],
        "best_offer": {"market": "fr"},
        "within_budget_count": 1,
        "pricing_unavailable_reason": None,
        "verify_links": None,
        "summary": "Cheapest simulated fare $410.31 via the FR market — within the $900.00 budget.",
        "llm_used": False,
    }


def test_result_maps_offers_to_neutral_suggestions() -> None:
    result = _to_result(_sample_result())

    assert isinstance(result, DomainSearchResult)
    assert [s.id for s in result.suggestions] == ["fr", "us"]  # market code, cheapest first

    cheapest = result.suggestions[0].item
    assert cheapest.title == "TLV → NYC · FR market"
    assert cheapest.subtitle == "2026-09-10 → 2026-09-17"
    assert cheapest.price.amount == 410.31
    assert cheapest.price.per is PricePer.total
    assert cheapest.price.currency == "USD"
    assert cheapest.url == "https://g/fr"  # prefers google_flights
    assert cheapest.badges == ["within budget"]
    assert cheapest.detail["offer"]["market"] == "fr"

    over = result.suggestions[1].item
    assert over.badges == ["over budget"]
    assert over.url == "https://s/us"  # falls back to skyscanner when google is null

    assert result.suggestions[0].lens is None  # flights have no lens
    assert result.counts == {"total": 2, "within_budget": 1}
    assert result.diagnostics["pricing_source"] == "simulated"
    assert result.diagnostics["within_budget_count"] == 1


def test_result_with_no_pricing_is_empty_with_a_warning() -> None:
    result = _to_result(
        {
            "query": {"origin": {"code": "TLV"}, "destination": {"code": "XXX"}},
            "offers": [],
            "pricing_unavailable_reason": "no cached fares for this route/dates",
            "summary": "No live fares available.",
        }
    )
    assert result.suggestions == []
    assert result.warnings == ["no cached fares for this route/dates"]
    assert result.counts["total"] == 0


# --- full run (offline simulated pricing) -----------------------------------------------------


def test_run_returns_offers_for_a_resolvable_route() -> None:
    result = FlightAdapter(_settings()).run(_trip())

    assert isinstance(result, DomainSearchResult)
    assert result.suggestions, "the simulated engine should yield market offers"
    first = result.suggestions[0].item
    assert first.price.currency == "USD"
    assert first.price.per is PricePer.total


def test_run_without_origin_is_a_clean_empty_outcome() -> None:
    result = FlightAdapter(_settings()).run(_trip(origin=None))
    assert result.suggestions == []
    assert result.warnings  # explains why flights were skipped


# --- fan-out + search integration (emulator-backed; skips without one) -------------------------


def test_fan_out_and_search_populate_flights(db) -> None:
    trip_ref = db.collection("users").document("u1").collection("trips").document()
    trip_ref.set({"input": BASE_INPUT, "status": "pending"})
    adapter = FlightAdapter(_settings())

    fan_out(db, trip_ref, agents=[adapter])
    domain_ref = trip_ref.collection("domains").document("flights")
    run_search(db, domain_ref, agents_by_domain={"flights": adapter})

    domain = domain_ref.get().to_dict()
    assert domain["agentStatus"] == "idle"
    assert domain["round"] == 1
    assert domain["selectionMode"] == "single"
    suggested = list(domain_ref.collection("suggested").stream())
    assert suggested, "search should write at least one market offer"
    first = suggested[0].to_dict()
    assert first["title"]
    assert first["round"] == 1
    assert first["price"]["currency"] == "USD"
