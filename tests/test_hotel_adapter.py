"""Hotel-adapter contract tests (``spec/schema.md``, ``spec/agents.md``).

Non-e2e: the vendored agent runs on its keyless defaults (``mock`` provider + ``heuristic`` scorer),
so nothing here needs an API key or an LLM round-trip. The module is skipped when the agent
submodule is not installed (``pip install -e vendor/agents/hotel-finder-agent``), the same way the
emulator-backed tests skip when no emulator is reachable.

Two directions are exercised: ``TripInput`` -> the agent's ``HotelSearchRequest`` (the mapping the
adapter owns, incl. the guests->room expansion and trip-level ``guest_nationality``), and the
agent's ``HotelSearchResponse`` -> tripper's ``HotelPayload``. A full ``run`` and an orchestrator
integration round out the coverage.
"""

from __future__ import annotations

import pytest

pytest.importorskip("hotel_finder", reason="hotel-finder agent submodule not installed")

from hotel_finder.contracts import (  # noqa: E402 - after importorskip
    Diagnostics,
    HotelSearchResponse,
    LensName,
    Pick,
    RateOffer,
    ResolvedQuery,
)
from hotel_finder.models import Amenity  # noqa: E402

from tripper.agents.hotel_adapter import (  # noqa: E402
    HotelAdapter,
    _agent_settings,
    _to_payload,
    _to_request,
)
from tripper.config import Settings  # noqa: E402
from tripper.contract import AgentStatus, HotelPayload, TripInput  # noqa: E402
from tripper.contract import Amenity as TripperAmenity  # noqa: E402
from tripper.contract import LensName as TripperLens  # noqa: E402
from tripper.orchestrator import run_job  # noqa: E402

BASE_INPUT: dict = {
    "place": {"city": "Barcelona", "country_code": "ES", "desired_area": "Eixample"},
    "stay": {"check_in": "2026-09-01", "check_out": "2026-09-04", "currency": "EUR"},
}


def _trip(**overrides) -> TripInput:
    return TripInput.from_dict({**BASE_INPUT, **overrides})


def _settings() -> Settings:
    # Keyless defaults: the agent uses the mock provider + heuristic scorer, no LLM.
    return Settings(gcp_project="demo-tripper", enabled_providers=["mock"], scorer="heuristic")


# --- request mapping --------------------------------------------------------------------------


def test_name_is_the_hotel_slot() -> None:
    assert HotelAdapter(_settings()).name == "hotel"


def test_guests_expand_into_a_single_room_when_rooms_is_null() -> None:
    trip = _trip(guests={"adults": 3, "children_ages": [4, 8]})
    assert trip.stay.rooms is None

    request = _to_request(trip)

    assert len(request.stay.rooms) == 1
    assert request.stay.rooms[0].adults == 3
    assert request.stay.rooms[0].children_ages == [4, 8]


def test_explicit_rooms_override_guests() -> None:
    trip = _trip(
        guests={"adults": 2},
        stay={**BASE_INPUT["stay"], "rooms": [{"adults": 1}, {"adults": 2, "children_ages": [5]}]},
    )

    request = _to_request(trip)

    assert [r.adults for r in request.stay.rooms] == [1, 2]
    assert request.stay.rooms[1].children_ages == [5]


def test_guest_nationality_is_trip_level_not_on_stay() -> None:
    request = _to_request(_trip(guest_nationality="GB"))

    assert request.guest_nationality == "GB"
    assert not hasattr(request.stay, "guest_nationality")


def test_place_filters_and_lenses_are_mapped() -> None:
    trip = _trip(
        place={"center": {"lat": 41.39, "lon": 2.16}, "radius_km": 3.0, "desired_area": "Gothic"},
        filters={
            "price_min": 80,
            "price_max": 200,
            "min_star": 4,
            "min_guest_rating": 8.5,
            "refundable": True,
            "must_have_amenities": ["wifi", "pool"],
            "property_types": ["hotel"],
        },
        lenses=["hidden_gems", "overall_standouts"],
        picks_per_lens=5,
    )

    request = _to_request(trip)

    assert request.place.center.lat == 41.39 and request.place.center.lon == 2.16
    assert request.place.radius_km == 3.0
    assert request.place.desired_area == "Gothic"
    assert request.filters.price_min == 80 and request.filters.price_max == 200
    assert request.filters.min_star == 4 and request.filters.min_guest_rating == 8.5
    assert request.filters.refundable is True
    assert request.filters.must_have_amenities == {Amenity.WIFI, Amenity.POOL}
    assert request.filters.property_types == {"hotel"}
    assert request.lenses == [LensName.HIDDEN_GEMS, LensName.OVERALL_STANDOUTS]
    assert request.picks_per_lens == 5


def test_lenses_none_passes_through_as_all_three() -> None:
    assert _to_request(_trip()).lenses is None


# --- response mapping -------------------------------------------------------------------------


def _sample_response() -> HotelSearchResponse:
    return HotelSearchResponse(
        request_id="req-123",
        agent_status="degraded",
        warnings=["provider mock partial"],
        resolved=ResolvedQuery(city="Barcelona", area="Eixample", currency="EUR"),
        diagnostics=Diagnostics(scorer="heuristic", providers_used=["mock"], candidates_found=12),
        lenses={
            LensName.STRATIFIED_BEST: [
                Pick(
                    name="Casa Eixample",
                    score=0.82,
                    rationale="central + quiet",
                    why={"location": 0.9},
                    amenities={Amenity.WIFI, Amenity.AC},
                    rating=8.7,
                    star_rating=4,
                    offers=[
                        RateOffer(total=264.0, currency="EUR", per_night=88.0, refundable=True)
                    ],
                )
            ]
        },
    )


def test_response_maps_to_payload_and_drops_request_id() -> None:
    payload = _to_payload(_sample_response())

    assert isinstance(payload, HotelPayload)
    assert payload.agent_status is AgentStatus.degraded
    assert payload.warnings == ["provider mock partial"]
    assert payload.resolved.city == "Barcelona"
    assert payload.diagnostics.scorer == "heuristic"
    assert payload.diagnostics.candidates_found == 12
    pick = payload.lenses[TripperLens.stratified_best][0]
    assert pick.name == "Casa Eixample"
    assert pick.score == 0.82
    assert set(pick.amenities) == {TripperAmenity.wifi, TripperAmenity.ac}
    assert pick.offers[0].per_night == 88.0
    # request_id is transport bookkeeping the tripper contract does not carry.
    assert "request_id" not in payload.to_dict()


# --- settings ---------------------------------------------------------------------------------


def test_agent_settings_built_from_tripper_config() -> None:
    agent_settings = _agent_settings(_settings())

    assert agent_settings.enabled_providers == ["mock"]
    assert agent_settings.scorer == "heuristic"
    # Empty tripper values are dropped, so the agent keeps its own defaults (no key leaked in).
    assert agent_settings.liteapi_api_key == ""


# --- full run (mock provider + heuristic scorer) ----------------------------------------------


def test_run_returns_a_valid_populated_payload() -> None:
    payload = HotelAdapter(_settings()).run(_trip())

    assert isinstance(payload, HotelPayload)
    assert payload.agent_status in set(AgentStatus)
    assert any(payload.lenses.values()), "the mock provider should yield at least one pick"
    # Every pick already satisfies the tripper contract (HotelPayload validated it on construction).
    a_pick = next(pick for picks in payload.lenses.values() for pick in picks)
    assert a_pick.name and 0.0 <= a_pick.score <= 1.0


# --- orchestrator integration (emulator-backed; skips without one) ----------------------------


def test_orchestrator_produces_trip_suggestions_hotel(db) -> None:
    ref = db.collection("users").document("u1").collection("trips").document()
    ref.set({"input": BASE_INPUT, "status": "pending", "attempts": 0})

    run_job(db, ref, agents=[HotelAdapter(_settings())])

    data = ref.get().to_dict()
    assert data["status"] == "done"
    assert data["results"]["status"] == "ok"
    hotel = data["results"]["hotel"]
    assert hotel is not None
    assert any(hotel["lenses"].values()), "orchestrator should carry the hotel picks through"
