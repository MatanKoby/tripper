"""The tripper/agent contract and job domain types (``spec/schema.md``).

Types, all Firestore-shaped (plain dicts of JSON-compatible primitives, with dates as ISO strings
and ``GeoPoint`` as a ``{lat, lon}`` dict):

- **Request** (``TripInput`` and children): the UI form and the job ``input``. Tripper hands this to
  the hotel agent via the adapter.
- **Response payload** (``HotelPayload`` and children): what the hotel agent returns, before the
  adapter maps it.
- **Storage** (``ResultItem`` + the per-domain ``DomainDoc`` / ``SuggestedDoc`` / ``SelectedDoc`` /
  ``RefinementDoc``): tripper's neutral, per-domain Firestore shapes (``spec/schema.md`` -> the
  Firestore data model). One trip fans out to a ``domains/{domain}`` subtree; each domain holds its
  own ``suggested`` candidates, ``selected`` choices, and ``refinements``. These model the durable
  *content* of each doc; the lease / claim reliability fields and server timestamps are written
  imperatively by the run machinery (``tripper.jobs``, ``spec/flows.md``), not modeled here.
- **Legacy M1 transport wrapper** (``TripSuggestions``): the superseded single-document ``results``
  model (``spec/archive.md``); still used by the M1 orchestrator until the fan-out batch replaces
  it.

Every model rejects unknown fields, so a malformed payload fails fast. ``from_dict`` / ``to_dict``
round-trip a model to and from a Firestore-shaped dict.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    # enums
    "Amenity",
    "LensName",
    "TravelStyle",
    "InterestGroup",
    "AgentStatus",
    "TransportStatus",
    "Domain",
    "DomainAgentStatus",
    "SelectionMode",
    "SelectionStatus",
    "RefinementStatus",
    "Feedback",
    "SelectedStatus",
    "PricePer",
    # shared value types
    "GeoPoint",
    "Room",
    # request: TripInput
    "Place",
    "Stay",
    "Guests",
    "Filters",
    "TripInput",
    # response: hotel agent payload
    "Offer",
    "Pick",
    "Resolved",
    "Diagnostics",
    "HotelPayload",
    # storage: neutral item + per-domain Firestore docs
    "Price",
    "ResultItem",
    "DomainDoc",
    "SuggestedDoc",
    "SelectedDoc",
    "RefinementDoc",
    # legacy M1 transport wrapper (spec/archive.md)
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


class TravelStyle(StrEnum):
    """Activities pace (``spec/schema.md``); maps to the activities agent's ``travel_style``."""

    relaxed = "relaxed"
    balanced = "balanced"
    packed = "packed"


class InterestGroup(StrEnum):
    """The activities agent's 8 category groups (``spec/schema.md``); each selects the whole group.

    Values are the group names the activities agent accepts as ``interests`` (``spec/agents.md``).
    """

    nature = "nature"
    food = "food"
    culture = "culture"
    adventure = "adventure"
    nightlife = "nightlife"
    family = "family"
    shopping = "shopping"
    beach = "beach"


class AgentStatus(StrEnum):
    """Data outcome reported by the agent (NOT transport)."""

    ok = "ok"
    empty = "empty"
    degraded = "degraded"


class TransportStatus(StrEnum):
    """Transport outcome: ``error`` means the call/import/timeout failed."""

    ok = "ok"
    error = "error"


class Domain(StrEnum):
    """A per-domain agent slot; each is a ``domains/{domain}`` doc (``spec/schema.md``)."""

    accommodations = "accommodations"
    activities = "activities"
    flights = "flights"


class DomainAgentStatus(StrEnum):
    """Claim/run lifecycle of a domain's current round (the domain doc's ``agentStatus``).

    Distinct from :class:`AgentStatus` (the hotel payload's *data* outcome). ``idle`` = a round
    completed, ready to view / refine; it cycles ``idle`` -> ``running`` -> ``idle`` each round.
    """

    pending = "pending"
    running = "running"
    idle = "idle"
    error = "error"


class SelectionMode(StrEnum):
    """How many items a domain lets the user select (accommodations: ``single``)."""

    single = "single"
    multi = "multi"


class SelectionStatus(StrEnum):
    """A domain's selection progress."""

    none = "none"
    partial = "partial"
    confirmed = "confirmed"


class RefinementStatus(StrEnum):
    """Lifecycle of a refine request/run (the refinement doc's ``status``)."""

    pending = "pending"
    running = "running"
    done = "done"
    error = "error"


class Feedback(StrEnum):
    """The client's wanted/unwanted mark on a suggestion (the refine loop's input)."""

    liked = "liked"
    disliked = "disliked"


class SelectedStatus(StrEnum):
    """Lifecycle of a chosen item."""

    selected = "selected"
    confirmed = "confirmed"


class PricePer(StrEnum):
    """The basis a :class:`Price` amount is quoted per."""

    night = "night"
    total = "total"
    person = "person"


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
    # --- flights (spec/agents.md); the flight adapter maps these + shared context ---
    origin: str | None = None  # departure point: city name or 3-letter IATA
    flight_budget_usd: float | None = None  # max airfare in USD (flight offers are USD-only)
    # --- activities (spec/agents.md); the activities adapter maps these + shared context ---
    activities_budget_usd: float | None = None  # USD budget (ex-lodging); adapter defaults if null
    interests: list[InterestGroup] | None = None  # null = the agent's default (culture, food)
    travel_style: TravelStyle = TravelStyle.balanced  # activities pace


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


# --- storage: neutral ResultItem + per-domain Firestore docs --------------------------------
#
# Tripper's own, per-domain storage shapes (``spec/schema.md`` -> Firestore data model). Each
# agent's adapter maps its payload to neutral ``ResultItem`` docs so one save seam writes them and
# the FE list is domain-agnostic. These model the durable *content* of each doc; the lease/claim
# reliability fields (``startedAt`` / ``leaseExpiresAt`` / ``attempts`` / ``maxAttempts`` /
# ``lastError``) and server timestamps (``createdAt`` / ``updatedAt``) are written imperatively by
# the run machinery (``tripper.jobs``, ``spec/flows.md``), as they are for the M1 job doc.


class Price(_Model):
    amount: float
    per: PricePer
    currency: str


class ResultItem(_Model):
    """The neutral, rendering-ready suggestion shape shared by all domains (``spec/schema.md``).

    Domain-specific fields the neutral shape does not cover live in the opaque ``detail`` blob that
    the domain's own renderer reads. This is also what ``SelectedDoc.snapshot`` copies, so a
    selection renders with the same renderer as a suggestion.
    """

    title: str
    subtitle: str | None = None
    score: float | None = Field(default=None, ge=0, le=1)  # comparable within a domain
    price: Price | None = None
    rating: float | None = None
    image_url: str | None = None
    url: str | None = None
    badges: list[str] = Field(default_factory=list)  # short chips (amenities, refundable, ...)
    rationale: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)  # domain-specific passthrough


class DomainDoc(_Model):
    """``.../domains/{domain}`` durable per-domain state (backend-owned, ``spec/access.md``).

    Its ``onCreate`` is the round-1 search trigger; the reliability fields live alongside these on
    the stored doc but are managed by the claim machinery (see module note).
    """

    domain: Domain
    agentStatus: DomainAgentStatus = DomainAgentStatus.pending
    selectionMode: SelectionMode
    selectionStatus: SelectionStatus = SelectionStatus.none
    round: int = 0  # highest completed round (0 = none yet, 1 = initial search)
    warnings: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)  # latest run, from the agent
    counts: dict[str, Any] = Field(default_factory=dict)


class SuggestedDoc(ResultItem):
    """``.../suggested/{suggestionId}`` one candidate: a :class:`ResultItem` plus sort/group keys.

    Backend-written except ``feedback`` (the only client-writable field, ``spec/access.md``). The
    ``suggestionId`` is the agent's stable item id (hotel: ``Pick.id``, ``spec/agents.md``).
    """

    lens: LensName | None = None  # hotel grouping; null for domains without lenses
    rank: int
    round: int
    dismissed: bool = False  # superseded / removed from view without deleting
    feedback: Feedback | None = None  # client-written; the wanted/unwanted input a refine reads


class SelectedDoc(_Model):
    """``.../selected/{itemId}`` a chosen item (client-written, ``spec/access.md``)."""

    suggestionId: str  # the suggested doc it came from (back-reference)
    snapshot: ResultItem  # copy at selection time, so the choice survives the agent re-running
    meta: dict[str, Any] = Field(default_factory=dict)  # per-agent selection metadata
    status: SelectedStatus = SelectedStatus.selected


class RefinementDoc(_Model):
    """``.../refinements/{refineId}`` a refine request + its run (``spec/schema.md``).

    Client-creates ``{ round, status: "pending" }``; the backend transitions the run (reliability
    fields managed by the claim machinery, see module note).
    """

    round: int
    status: RefinementStatus = RefinementStatus.pending


# --- legacy M1 transport wrapper: TripSuggestions (superseded, spec/archive.md) --------------
#
# The single-document ``results`` model. Superseded by the per-domain storage docs above; still
# imported by the M1 orchestrator (``tripper.orchestrator`` / ``tripper.jobs``) until the fan-out
# batch replaces that path, at which point this wrapper is removed.


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
