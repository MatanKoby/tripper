"""The tripper/agent contract and job domain types (``spec/schema.md``).

Three groups of types, all Firestore-shaped (plain dicts of JSON-compatible primitives, with
dates as ISO strings and ``GeoPoint`` as a ``{lat, lon}`` dict):

- **Request** (``TripInput`` and children): the UI form and the job ``input``. Tripper hands this to
  the hotel agent via the adapter (Batch 10).
- **Response payload** (``HotelPayload`` and children): what the agent returns, before wrapping.
- **Transport wrapper** (``TripSuggestions``): orchestrator-owned; written as the job ``results``.

Every model rejects unknown fields, so a malformed payload fails fast. ``from_dict`` /``to_dict``
round-trip a model to and from a Firestore-shaped dict.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "Amenity",
    "LensName",
    "AgentStatus",
    "TransportStatus",
    "GeoPoint",
    "Room",
    "Place",
    "Stay",
    "Guests",
    "Filters",
    "TripInput",
    "Offer",
    "Pick",
    "Resolved",
    "Diagnostics",
    "HotelPayload",
    "TripError",
    "TripSuggestions",
]


# --- enumerations ---------------------------------------------------------------------------


class Amenity(StrEnum):
    wifi = "wifi"
    pool = "pool"
    gym = "gym"
    breakfast = "breakfast"
    parking = "parking"
    ac = "ac"
    spa = "spa"
    pet_friendly = "pet_friendly"
    kitchen = "kitchen"
    bar = "bar"
    restaurant = "restaurant"
    airport_shuttle = "airport_shuttle"


class LensName(StrEnum):
    stratified_best = "stratified_best"
    overall_standouts = "overall_standouts"
    hidden_gems = "hidden_gems"


class AgentStatus(StrEnum):
    """Data outcome reported by the agent (NOT transport)."""

    ok = "ok"
    empty = "empty"
    degraded = "degraded"


class TransportStatus(StrEnum):
    """Transport outcome: ``error`` means the call/import/timeout failed."""

    ok = "ok"
    error = "error"


# --- base -----------------------------------------------------------------------------------


class _Model(BaseModel):
    """Shared base: reject unknown fields and add Firestore round-trip helpers."""

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        """Validate a Firestore-shaped dict into a model (raises on invalid input)."""
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Dump to a Firestore-shaped dict (dates as ISO strings, enums as their values)."""
        return self.model_dump(mode="json")


# --- shared value types ---------------------------------------------------------------------


class GeoPoint(_Model):
    lat: float
    lon: float


class Room(_Model):
    adults: int = Field(ge=1)
    children_ages: list[int] = Field(default_factory=list)


# --- request: TripInput ---------------------------------------------------------------------


class Place(_Model):
    text: str | None = None
    country_code: str | None = None  # ISO-3166-1 alpha-2
    city: str | None = None
    center: GeoPoint | None = None
    radius_km: float = 5.0  # only meaningful with center
    desired_area: str | None = None  # soft neighborhood bias

    @model_validator(mode="after")
    def _require_locator(self) -> Place:
        has_text = bool(self.text and self.text.strip())
        has_city = bool(self.city and self.country_code)
        has_center = self.center is not None
        if not (has_text or has_city or has_center):
            raise ValueError(
                "place requires at least one of: text, city (+country_code), or center"
            )
        return self


class Stay(_Model):
    check_in: date
    check_out: date
    currency: str = "EUR"
    rooms: list[Room] | None = None  # null = derive 1 room from guests; if set, OVERRIDES guests

    @model_validator(mode="after")
    def _dates_ordered(self) -> Stay:
        if self.check_out <= self.check_in:
            raise ValueError("stay.check_out must be after check_in")
        return self


class Guests(_Model):
    adults: int = Field(default=2, ge=1)
    children_ages: list[int] = Field(default_factory=list)


class Filters(_Model):
    price_min: float | None = None  # per night
    price_max: float | None = None
    min_star: int | None = Field(default=None, ge=1, le=5)
    min_guest_rating: float | None = Field(default=None, ge=0, le=10)
    refundable: bool | None = None  # null = a cheapest-refundable AND a cheapest-non-refundable
    must_have_amenities: list[Amenity] = Field(default_factory=list)
    property_types: list[str] = Field(default_factory=list)  # empty = all lodging types


class TripInput(_Model):
    place: Place
    stay: Stay
    guests: Guests = Field(default_factory=Guests)  # used only when stay.rooms is null
    guest_nationality: str = "US"  # adapter maps it to the agent's stay.guest_nationality
    filters: Filters = Field(default_factory=Filters)
    lenses: list[LensName] | None = None  # null = all three
    picks_per_lens: int = Field(default=3, ge=1)


# --- response: hotel agent payload ----------------------------------------------------------


class Offer(_Model):
    total: float
    per_night: float | None = None
    currency: str
    board: str | None = None
    refundable: bool
    over_budget: bool = False


class Pick(_Model):
    """A flat, rendering-ready hotel pick."""

    name: str
    score: float = Field(ge=0, le=1)  # normalized, comparable across lenses
    rationale: str
    why: dict[str, float] = Field(default_factory=dict)  # free-form subscores, scorer-dependent
    area: str | None = None
    distance_to_desired_km: float | None = None  # null when no desired_area/center
    price_per_night: float | None = None
    currency: str | None = None
    rating: float | None = Field(default=None, ge=0, le=10)
    review_count: int | None = None
    star_rating: int | None = Field(default=None, ge=1, le=5)
    description: str | None = None
    amenities: list[Amenity] = Field(default_factory=list)
    coordinates: GeoPoint | None = None
    image_url: str | None = None
    url: str | None = None
    offers: list[Offer] = Field(default_factory=list)


class Resolved(_Model):
    city: str | None = None
    area: str | None = None
    center: GeoPoint | None = None
    check_in: date | None = None
    check_out: date | None = None
    currency: str | None = None


class Diagnostics(_Model):
    scorer: str
    providers_used: list[str] = Field(default_factory=list)
    candidates_found: int = 0
    candidates_after_filter: int = 0
    shortlisted: int = 0
    widened: bool = False


class HotelPayload(_Model):
    """The agent's response, before the transport wrapper. It never raises for a data outcome."""

    agent_status: AgentStatus
    warnings: list[str] = Field(default_factory=list)
    resolved: Resolved
    lenses: dict[LensName, list[Pick]] = Field(default_factory=dict)  # up to all three keys
    diagnostics: Diagnostics


# --- transport wrapper: TripSuggestions -----------------------------------------------------


class TripError(_Model):
    message: str
    kind: str


class TripSuggestions(_Model):
    """Orchestrator-owned wrapper written as the job ``results`` (and mirrored by the job doc)."""

    status: TransportStatus
    error: TripError | None = None  # only when status == "error"
    hotel: HotelPayload | None = None  # present when status == "ok"

    @model_validator(mode="after")
    def _consistency(self) -> TripSuggestions:
        if self.status is TransportStatus.error:
            if self.error is None:
                raise ValueError("status 'error' requires an error object")
            if self.hotel is not None:
                raise ValueError("status 'error' must not carry a hotel payload")
        else:  # ok
            if self.error is not None:
                raise ValueError("status 'ok' must not carry an error object")
            if self.hotel is None:
                raise ValueError("status 'ok' requires a hotel payload")
        return self
