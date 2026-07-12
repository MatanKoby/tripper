"""Round-trip and validation tests for the tripper/agent contract (spec/schema.md)."""

import pytest
from pydantic import ValidationError

from tripper.contract import (
    Guests,
    HotelPayload,
    TripInput,
    TripSuggestions,
)

# A fully-populated TripInput as it lands in Firestore (dates as ISO strings, GeoPoint as a dict).
FULL_TRIP_INPUT: dict = {
    "place": {
        "text": "central Lisbon",
        "country_code": "PT",
        "city": "Lisbon",
        "center": {"lat": 38.72, "lon": -9.14},
        "radius_km": 3.0,
        "desired_area": "Alfama",
    },
    "stay": {
        "check_in": "2026-08-01",
        "check_out": "2026-08-05",
        "currency": "EUR",
        "rooms": [{"adults": 2, "children_ages": [4, 9]}],
    },
    "guests": {"adults": 2, "children_ages": [4, 9]},
    "guest_nationality": "PT",
    "filters": {
        "price_min": 80.0,
        "price_max": 250.0,
        "min_star": 3,
        "min_guest_rating": 8.0,
        "refundable": True,
        "must_have_amenities": ["wifi", "breakfast"],
        "property_types": ["hotel"],
    },
    "lenses": ["stratified_best", "hidden_gems"],
    "picks_per_lens": 4,
}

# A fully-populated agent payload with one pick under one lens.
FULL_HOTEL_PAYLOAD: dict = {
    "agent_status": "ok",
    "warnings": ["dropped a stale offer"],
    "resolved": {
        "city": "Lisbon",
        "area": "Alfama",
        "center": {"lat": 38.72, "lon": -9.14},
        "check_in": "2026-08-01",
        "check_out": "2026-08-05",
        "currency": "EUR",
    },
    "lenses": {
        "stratified_best": [
            {
                "name": "Hotel Alfama View",
                "score": 0.91,
                "rationale": "great value near the castle",
                "why": {"price": 0.8, "location": 0.95},
                "area": "Alfama",
                "distance_to_desired_km": 0.4,
                "price_per_night": 140.0,
                "currency": "EUR",
                "rating": 9.1,
                "review_count": 812,
                "star_rating": 4,
                "description": "Boutique stay with rooftop views.",
                "amenities": ["wifi", "breakfast"],
                "coordinates": {"lat": 38.71, "lon": -9.13},
                "image_url": "https://img.example/alfama.jpg",
                "url": "https://book.example/alfama",
                "offers": [
                    {
                        "total": 560.0,
                        "per_night": 140.0,
                        "currency": "EUR",
                        "board": "breakfast",
                        "refundable": True,
                        "over_budget": False,
                    }
                ],
            }
        ]
    },
    "diagnostics": {
        "scorer": "heuristic",
        "providers_used": ["mock"],
        "candidates_found": 40,
        "candidates_after_filter": 12,
        "shortlisted": 4,
        "widened": False,
    },
}


def test_trip_input_round_trips() -> None:
    assert TripInput.from_dict(FULL_TRIP_INPUT).to_dict() == FULL_TRIP_INPUT


def test_hotel_payload_round_trips() -> None:
    assert HotelPayload.from_dict(FULL_HOTEL_PAYLOAD).to_dict() == FULL_HOTEL_PAYLOAD


def test_trip_suggestions_ok_round_trips() -> None:
    doc = {"status": "ok", "error": None, "hotel": FULL_HOTEL_PAYLOAD}
    assert TripSuggestions.from_dict(doc).to_dict() == doc


def test_trip_suggestions_error_round_trips() -> None:
    doc = {
        "status": "error",
        "error": {"message": "agent import failed", "kind": "ImportError"},
        "hotel": None,
    }
    assert TripSuggestions.from_dict(doc).to_dict() == doc


def test_minimal_trip_input_applies_defaults() -> None:
    ti = TripInput.from_dict(
        {
            "place": {"city": "Porto", "country_code": "PT"},
            "stay": {"check_in": "2026-09-10", "check_out": "2026-09-12"},
        }
    )
    assert ti.guests == Guests(adults=2, children_ages=[])
    assert ti.guest_nationality == "US"
    assert ti.stay.currency == "EUR"
    assert ti.picks_per_lens == 3
    assert ti.lenses is None
    assert ti.place.radius_km == 5.0


def test_place_requires_a_locator() -> None:
    with pytest.raises(ValidationError):
        TripInput.from_dict(
            {"place": {"desired_area": "downtown"}, "stay": {"check_in": "2026-09-10",
             "check_out": "2026-09-12"}}
        )


def test_city_without_country_code_is_not_a_locator() -> None:
    with pytest.raises(ValidationError):
        TripInput.from_dict(
            {"place": {"city": "Porto"}, "stay": {"check_in": "2026-09-10",
             "check_out": "2026-09-12"}}
        )


def test_check_out_must_follow_check_in() -> None:
    with pytest.raises(ValidationError):
        TripInput.from_dict(
            {"place": {"city": "Porto", "country_code": "PT"},
             "stay": {"check_in": "2026-09-12", "check_out": "2026-09-10"}}
        )


@pytest.mark.parametrize(
    "filters",
    [
        {"min_star": 6},
        {"min_star": 0},
        {"min_guest_rating": 11},
    ],
)
def test_out_of_range_filters_rejected(filters: dict) -> None:
    with pytest.raises(ValidationError):
        TripInput.from_dict(
            {"place": {"city": "Porto", "country_code": "PT"},
             "stay": {"check_in": "2026-09-10", "check_out": "2026-09-12"}, "filters": filters}
        )


def test_unknown_field_rejected() -> None:
    with pytest.raises(ValidationError):
        TripInput.from_dict(
            {"place": {"city": "Porto", "country_code": "PT"},
             "stay": {"check_in": "2026-09-10", "check_out": "2026-09-12"}, "surprise": 1}
        )


def test_unknown_enum_values_rejected() -> None:
    bad = {**FULL_HOTEL_PAYLOAD, "lenses": {"not_a_lens": []}}
    with pytest.raises(ValidationError):
        HotelPayload.from_dict(bad)


def test_pick_score_out_of_range_rejected() -> None:
    bad = {
        "agent_status": "ok",
        "resolved": {},
        "diagnostics": {"scorer": "heuristic"},
        "lenses": {"hidden_gems": [{"name": "X", "score": 1.5, "rationale": "r"}]},
    }
    with pytest.raises(ValidationError):
        HotelPayload.from_dict(bad)


def test_ok_suggestions_require_a_hotel() -> None:
    with pytest.raises(ValidationError):
        TripSuggestions.from_dict({"status": "ok", "hotel": None})


def test_error_suggestions_require_an_error() -> None:
    with pytest.raises(ValidationError):
        TripSuggestions.from_dict({"status": "error", "error": None, "hotel": None})


def test_error_suggestions_reject_a_hotel_payload() -> None:
    with pytest.raises(ValidationError):
        TripSuggestions.from_dict(
            {"status": "error", "error": {"message": "x", "kind": "Y"}, "hotel": FULL_HOTEL_PAYLOAD}
        )
