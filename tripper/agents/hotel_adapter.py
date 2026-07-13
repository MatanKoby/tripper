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

from tripper.agents.base import Agent
from tripper.config import Settings
from tripper.contract import GeoPoint, HotelPayload, Room, TripInput


class HotelAdapter(Agent):
    """Wraps the hotel-finder agent as tripper's Accommodation agent (transport slot ``hotel``)."""

    name = "hotel"

    def __init__(self, settings: Settings) -> None:
        # Build the agent's Settings once from tripper's config (the two share env-var names, so
        # ``agent_env()`` already speaks the agent's vocabulary). Empty values are dropped there, so
        # the agent falls back to its own defaults (keyless ``mock`` provider + heuristic scorer).
        self._settings = _agent_settings(settings)

    def run(self, trip: TripInput) -> HotelPayload:
        """Map, call the agent, and map back. Raises only on a transport failure (import/call)."""
        request = _to_request(trip)
        response = search_sync(request, self._settings)
        return _to_payload(response)


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
