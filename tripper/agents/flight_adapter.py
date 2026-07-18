"""The Flights agent: a tripper adapter around the vendored flight-finder agent.

The orchestrator sees only the :class:`~tripper.agents.base.Agent` seam and the contract
(``spec/schema.md``). This adapter is the one place that knows the flight agent's own API
(``vendor/agents/flight-finder-agent``): it maps tripper's :class:`~tripper.contract.TripInput`
(shared context + ``origin`` / ``flight_budget_usd``) to the agent's ``FlightRequest``, builds the
agent's ``Settings`` from tripper's :class:`~tripper.config.Settings`, calls the sync ``run`` entry
point, and maps the returned per-market offers to neutral :class:`~tripper.contract.ResultItem`
candidates (``spec/agents.md``).

The flight agent is a **pure function** (one request in, one result out, no state); there is no
dedicated refine entry point and none is needed — a refine run (Batch 13) re-runs ``run`` with the
feedback folded into the request (``spec/agents.md``). Because tripper always passes a structured
``origin`` + ``destination``, the agent's free-text / LLM path never runs and the search is fully
deterministic; with no pricing token configured it falls back to its offline simulated engine.

``vendor/agents/**`` is upstream-owned and read-only (``spec/agents.md``); an interface gap is fixed
here in the adapter, never by editing the submodule.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from flight_finder import BadRequest, run
from flight_finder.config import Settings as AgentSettings

from tripper.agents.base import Agent, DomainSearchResult, PriorCandidate, Suggestion
from tripper.config import Settings
from tripper.contract import (
    Domain,
    Feedback,
    Place,
    Price,
    PricePer,
    ResultItem,
    SelectionMode,
    TripInput,
)


class FlightAdapter(Agent):
    """Wraps the flight-finder agent as tripper's Flights agent (domain ``flights``)."""

    domain = Domain.flights
    selection_mode = SelectionMode.single
    supports_refine = True  # refine = re-run with the feedback folded in (``spec/agents.md``)

    def __init__(self, settings: Settings) -> None:
        # Build the agent's Settings from tripper's config; empty values are dropped so the agent
        # keeps its own keyless defaults (offline simulated pricing).
        self._settings = _agent_settings(settings)

    def run(self, trip: TripInput) -> DomainSearchResult:
        """Map, call the agent, map its offers to neutral candidates + run metadata.

        A missing ``origin`` or an unlocatable destination is a **data** outcome (empty candidates +
        a warning), not a transport failure; only a genuine call failure propagates so the
        orchestrator can mark the domain ``error`` (``spec/agents.md``).
        """
        return self._run(_to_request(trip))

    def refine(self, trip: TripInput, prior: Sequence[PriorCandidate]) -> DomainSearchResult:
        """Re-run search with the user's feedback folded into the fare budget (``spec/agents.md``).

        The flight agent is a pure function with no dedicated refine entry point, so a refine is
        just a search with an adjusted request: disliked offers pull the budget below the cheapest
        of them (steer toward cheaper fares), and liked offers hold the budget high enough to keep
        them in range. The route and dates are unchanged.
        """
        request = _to_request(trip)
        if request is not None:
            request["budget"] = _fold_budget(request.get("budget"), prior)
        return self._run(request)

    def _run(self, request: dict[str, Any] | None) -> DomainSearchResult:
        """Shared call + mapping for :meth:`run` and :meth:`refine` (``spec/agents.md``)."""
        if request is None:
            return DomainSearchResult(
                suggestions=[],
                warnings=["flights need an origin and a destination; skipped"],
            )
        try:
            result = run(request, self._settings)
        except BadRequest as exc:
            # Unresolvable origin/destination the agent couldn't match to a city/airport.
            return DomainSearchResult(suggestions=[], warnings=[str(exc)])
        return _to_result(result)


def _fold_budget(budget: float | None, prior: Sequence[PriorCandidate]) -> float | None:
    """Adjust the fare budget from the wanted/unwanted marks (``spec/agents.md``).

    Disliked fares cap the budget just below the cheapest disliked price (push toward cheaper);
    liked fares raise it to at least the priciest liked price (keep them affordable). With no priced
    marks the budget is unchanged.
    """
    disliked = [
        c.item.price.amount for c in prior if c.feedback is Feedback.disliked and c.item.price
    ]
    liked = [c.item.price.amount for c in prior if c.feedback is Feedback.liked and c.item.price]
    if disliked:
        cap = min(disliked) - 1.0
        budget = cap if budget is None else min(budget, cap)
    if liked:
        floor = max(liked)
        budget = floor if budget is None else max(budget, floor)
    return budget


def _agent_settings(settings: Settings) -> AgentSettings:
    """Build the flight agent's ``Settings`` from tripper's config (env-var names, lower-cased)."""
    env = settings.flight_agent_env()
    return AgentSettings(**{key.lower(): value for key, value in env.items()})


def _to_request(trip: TripInput) -> dict[str, Any] | None:
    """Map a :class:`TripInput` to the flight agent's request dict, or ``None`` when unroutable.

    The shared context supplies the route and dates (``spec/schema.md``): ``origin`` is the trip
    departure point, the destination is the trip's place, and the stay dates become a round trip
    (out on ``check_in``, back on ``check_out``). ``flight_budget_usd`` caps the fare in USD.
    """
    origin = (trip.origin or "").strip()
    destination = _destination(trip.place)
    if not origin or not destination:
        return None
    return {
        "origin": origin,
        "destination": destination,
        "budget": trip.flight_budget_usd,
        "departure_date": trip.stay.check_in.isoformat(),
        "return_date": trip.stay.check_out.isoformat(),
    }


def _destination(place: Place) -> str | None:
    """The destination as a name/IATA the flight agent can resolve (``city``, else free ``text``).

    A center-only place has no textual locator the flight agent accepts, so it yields ``None``.
    """
    if place.city and place.city.strip():
        return place.city.strip()
    if place.text and place.text.strip():
        return place.text.strip()
    return None


def _to_result(result: dict[str, Any]) -> DomainSearchResult:
    """Map the flight agent's result dict to neutral candidates + domain-doc run metadata.

    One :class:`~tripper.contract.ResultItem` per market ``offer`` (cheapest first), the offer's
    ``market`` code as the stable suggestion id (unique within a request); the run ``summary`` /
    ``within_budget_count`` / ``pricing_source`` and the resolved ``query`` go on ``diagnostics``
    (``spec/schema.md``). No pricing available is a valid empty outcome with the reason in
    ``warnings``.
    """
    query = result.get("query") or {}
    offers = result.get("offers") or []
    suggestions = [
        Suggestion(id=offer["market"], item=_offer_to_item(offer, query))
        for offer in offers
    ]

    warnings: list[str] = []
    reason = result.get("pricing_unavailable_reason")
    if not offers and reason:
        warnings.append(reason)

    diagnostics = {
        "summary": result.get("summary"),
        "pricing_source": result.get("pricing_source"),
        "within_budget_count": result.get("within_budget_count"),
        "llm_used": result.get("llm_used"),
        "query": query,
    }
    if reason:
        diagnostics["pricing_unavailable_reason"] = reason
    if result.get("verify_links"):
        diagnostics["verify_links"] = result["verify_links"]

    counts = {"total": len(suggestions), "within_budget": result.get("within_budget_count")}
    return DomainSearchResult(
        suggestions=suggestions,
        diagnostics=diagnostics,
        warnings=warnings,
        counts=counts,
    )


def _offer_to_item(offer: dict[str, Any], query: dict[str, Any]) -> ResultItem:
    """One market ``offer`` → the neutral :class:`ResultItem` + flight-specific ``detail``."""
    origin_code = (query.get("origin") or {}).get("code", "?")
    dest_code = (query.get("destination") or {}).get("code", "?")
    country = offer.get("country", "?")
    links = offer.get("links") or {}

    badges: list[str] = []
    within = offer.get("within_budget")
    if within is True:
        badges.append("within budget")
    elif within is False:
        badges.append("over budget")

    return ResultItem(
        title=f"{origin_code} → {dest_code} · {country} market",
        subtitle=_when(offer),
        price=Price(amount=offer["price_usd"], per=PricePer.total, currency="USD"),
        url=links.get("google_flights") or links.get("skyscanner"),
        badges=badges,
        detail={"offer": offer, "query": query},
    )


def _when(offer: dict[str, Any]) -> str | None:
    """A short date subtitle from the offer's departure (and return, when round trip)."""
    departure = offer.get("departure_at")
    if not departure:
        return None
    return f"{departure} → {offer['return_at']}" if offer.get("return_at") else departure
