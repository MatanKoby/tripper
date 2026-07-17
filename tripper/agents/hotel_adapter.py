"""The Accommodation agent: a tripper adapter around the vendored hotel-finder agent.

The orchestrator sees only the :class:`~tripper.agents.base.Agent` seam and the contract
(``spec/schema.md``). This adapter is the one place that knows the hotel agent's own API
(``vendor/agents/hotel-finder-agent``): it maps tripper's :class:`~tripper.contract.TripInput` to
the agent's ``HotelSearchRequest``, builds the agent's ``Settings`` from tripper's
:class:`~tripper.config.Settings`, calls the agent's ``search_sync`` entry point, and maps the
returned ``HotelSearchResponse`` back to a :class:`~tripper.contract.HotelPayload`.

The two contracts are deliberately field-aligned (``spec/schema.md`` is the agreed shape), so the
request mapping is a direct field-by-field translation and the response is a structural echo we
re-validate against tripper's own contract at the boundary. Two things the mapping makes explicit:

- ``guests`` expands into a single room when ``stay.rooms`` is null (a set ``stay.rooms`` overrides
  ``guests``), matching the agent's own derivation but done here so the wire request is unambiguous.
- ``guest_nationality`` is a **trip-level** field on both sides
  (``HotelSearchRequest.guest_nationality``), not part of ``stay``.

``vendor/agents/**`` is upstream-owned and read-only (``spec/agents.md``); an interface gap is fixed
here in the adapter, never by editing the submodule.
"""

from __future__ import annotations

from hotel_finder import HotelSearchRequest, HotelSearchResponse, search_sync
from hotel_finder.config import Settings as AgentSettings
from hotel_finder.contracts import Filters as AgentFilters
from hotel_finder.contracts import LensName as AgentLensName
from hotel_finder.contracts import Occupancy as AgentOccupancy
from hotel_finder.contracts import Place as AgentPlace
from hotel_finder.contracts import Stay as AgentStay

from tripper.agents.base import Agent, DomainSearchResult, Suggestion
from tripper.config import Settings
from tripper.contract import (
    Domain,
    GeoPoint,
    HotelPayload,
    Offer,
    Pick,
    Price,
    PricePer,
    ResultItem,
    Room,
    SelectionMode,
    TripInput,
)


class HotelAdapter(Agent):
    """Wraps the hotel-finder agent as tripper's Accommodation agent (domain ``accommodations``)."""

    domain = Domain.accommodations
    selection_mode = SelectionMode.single

    def __init__(self, settings: Settings) -> None:
        # Build the agent's Settings once from tripper's config (the two share env-var names, so
        # ``agent_env()`` already speaks the agent's vocabulary). Empty values are dropped there, so
        # the agent falls back to its own defaults (keyless ``mock`` provider + heuristic scorer).
        self._settings = _agent_settings(settings)

    def run(self, trip: TripInput) -> DomainSearchResult:
        """Map, call the agent, map its payload to neutral candidates + run metadata.

        Raises only on a transport failure (import / call); an empty data outcome is a valid
        :class:`DomainSearchResult` with no suggestions.
        """
        request = _to_request(trip)
        response = search_sync(request, self._settings)
        return _to_result(_to_payload(response))


def _agent_settings(settings: Settings) -> AgentSettings:
    """Construct the agent's ``Settings`` from tripper's config.

    ``agent_env()`` yields the agent's env-var names (upper-case); the agent's field names are their
    lower-case forms, so we pass them as init kwargs (which take precedence over the process env).
    """
    return AgentSettings(**{key.lower(): value for key, value in settings.agent_env().items()})


def _to_request(trip: TripInput) -> HotelSearchRequest:
    """Map a :class:`TripInput` to the hotel agent's ``HotelSearchRequest`` (``spec/schema.md``)."""
    place = trip.place
    stay = trip.stay
    filters = trip.filters
    return HotelSearchRequest(
        place=AgentPlace(
            text=place.text,
            country_code=place.country_code,
            city=place.city,
            center=_geo(place.center),
            radius_km=place.radius_km,
            desired_area=place.desired_area,
        ),
        stay=AgentStay(
            check_in=stay.check_in,
            check_out=stay.check_out,
            currency=stay.currency,
            rooms=_rooms(trip),
        ),
        guests=AgentOccupancy(adults=trip.guests.adults, children_ages=trip.guests.children_ages),
        guest_nationality=trip.guest_nationality,
        filters=AgentFilters(
            price_min=filters.price_min,
            price_max=filters.price_max,
            min_star=filters.min_star,
            min_guest_rating=filters.min_guest_rating,
            refundable=filters.refundable,
            must_have_amenities={amenity.value for amenity in filters.must_have_amenities},
            property_types=set(filters.property_types),
        ),
        lenses=(
            None if trip.lenses is None else [AgentLensName(lens.value) for lens in trip.lenses]
        ),
        picks_per_lens=trip.picks_per_lens,
    )


def _rooms(trip: TripInput) -> list[AgentOccupancy]:
    """The request's occupancy rooms: the given ``stay.rooms``, or one room from ``guests``."""
    rooms = trip.stay.rooms if trip.stay.rooms is not None else [_room_from_guests(trip)]
    return [AgentOccupancy(adults=room.adults, children_ages=room.children_ages) for room in rooms]


def _room_from_guests(trip: TripInput) -> Room:
    """Derive one room from trip-level ``guests`` (used only when ``stay.rooms`` is null)."""
    return Room(adults=trip.guests.adults, children_ages=trip.guests.children_ages)


def _geo(point: GeoPoint | None) -> dict[str, float] | None:
    """The agent's ``GeoPoint`` is ``{lat, lon}`` too; pass a plain dict for pydantic to coerce."""
    return None if point is None else {"lat": point.lat, "lon": point.lon}


def _to_payload(response: HotelSearchResponse) -> HotelPayload:
    """Map the agent's ``HotelSearchResponse`` to tripper's :class:`HotelPayload`.

    The two envelopes are field-aligned (``spec/schema.md``); the only difference is the agent's
    ``request_id`` echo, which is transport bookkeeping tripper does not carry. We drop it and
    re-validate the rest against tripper's own contract, so any upstream drift fails loudly here.
    """
    data = response.model_dump(mode="json")
    data.pop("request_id", None)
    return HotelPayload.model_validate(data)


def _to_result(payload: HotelPayload) -> DomainSearchResult:
    """Map a :class:`HotelPayload` to neutral candidates + domain-doc run metadata (``schema.md``).

    Each lens's picks become :class:`~tripper.contract.ResultItem`s (``name``→``title``, ``area``→
    ``subtitle``, cheapest offer→``price``, ``amenities``→``badges``), hotel-specific rest in
    ``detail`` so the domain renderer can read it. The suggestion id is ``"{lens}-{i}"`` (stable
    within a run) until the agent exposes a stable ``Pick.id`` (``spec/agents.md``).
    """
    suggestions: list[Suggestion] = []
    for lens, picks in payload.lenses.items():
        for index, pick in enumerate(picks):
            suggestions.append(
                Suggestion(id=f"{lens.value}-{index}", item=_pick_to_item(pick), lens=lens)
            )
    diagnostics = {
        **payload.diagnostics.to_dict(),
        "resolved": payload.resolved.to_dict(),
        "agent_status": payload.agent_status.value,
    }
    counts = {
        "total": len(suggestions),
        "per_lens": {lens.value: len(picks) for lens, picks in payload.lenses.items()},
    }
    return DomainSearchResult(
        suggestions=suggestions,
        diagnostics=diagnostics,
        warnings=list(payload.warnings),
        counts=counts,
    )


def _pick_to_item(pick: Pick) -> ResultItem:
    """One hotel :class:`Pick` → the neutral :class:`ResultItem` + hotel-specific ``detail``."""
    offer = _cheapest_offer(pick.offers)
    badges = [amenity.value for amenity in pick.amenities]
    if offer is not None and offer.refundable:
        badges.append("refundable")
    return ResultItem(
        title=pick.name,
        subtitle=pick.area,
        score=pick.score,
        price=_price(pick, offer),
        rating=pick.rating,
        image_url=pick.image_url,
        url=pick.url,
        badges=badges,
        rationale=pick.rationale,
        detail={
            "offers": [o.to_dict() for o in pick.offers],
            "star_rating": pick.star_rating,
            "why": pick.why,
            "distance_to_desired_km": pick.distance_to_desired_km,
            "coordinates": pick.coordinates.to_dict() if pick.coordinates else None,
            "price_per_night": pick.price_per_night,
            "currency": pick.currency,
            "review_count": pick.review_count,
            "description": pick.description,
        },
    )


def _cheapest_offer(offers: list[Offer]) -> Offer | None:
    """The lowest-priced offer (by per-night, then total), or ``None`` when there are none."""
    if not offers:
        return None
    return min(offers, key=lambda o: o.per_night if o.per_night is not None else o.total)


def _price(pick: Pick, offer: Offer | None) -> Price | None:
    """The neutral :class:`Price` from the cheapest offer, or the pick's per-night as a fallback."""
    if offer is not None:
        if offer.per_night is not None:
            return Price(amount=offer.per_night, per=PricePer.night, currency=offer.currency)
        return Price(amount=offer.total, per=PricePer.total, currency=offer.currency)
    if pick.price_per_night is not None and pick.currency:
        return Price(amount=pick.price_per_night, per=PricePer.night, currency=pick.currency)
    return None
