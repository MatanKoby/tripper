"""The Activities agent: a tripper adapter around the vendored travel-agent.

The orchestrator sees only the :class:`~tripper.agents.base.Agent` seam and the contract
(``spec/schema.md``). This adapter is the one place that knows the activities agent's own API
(``vendor/agents/travel-agent``): it maps tripper's :class:`~tripper.contract.TripInput` (shared
context + ``activities_budget_usd`` / ``interests`` / ``travel_style``) to the agent's ``start``
request, **drives the multi-turn conversation statelessly** to a completed itinerary, and maps the
recommended activities to neutral :class:`~tripper.contract.ResultItem` candidates (``agents.md``).

The travel-agent is natively a multi-turn LangGraph conversation with an in-process session
(``spec/agents.md``). We do **not** keep the tripper function alive for it: within one ``run`` we
``start`` the session, then relay ``feedback`` round by round (accepting each category, advancing)
until the graph reaches ``completed``, map the result, and **discard the instance** — no
``session_id`` is persisted, nothing survives the run. A refine run (Batch 13) is a fresh instance
with the feedback folded into a new ``start`` request, never a resume; the state lives in Firestore.

``vendor/agents/**`` is upstream-owned and read-only (``spec/agents.md``); an interface gap is fixed
here in the adapter, never by editing the submodule.
"""

from __future__ import annotations

from typing import Any

from travel_agent import ActivitiesAgent
from travel_agent import Settings as AgentSettings

from tripper.agents.base import Agent, DomainSearchResult, Suggestion
from tripper.config import Settings
from tripper.contract import Domain, Place, Price, PricePer, ResultItem, SelectionMode, TripInput

#: The agent requires a positive budget; tripper defaults it when the trip leaves it null
#: (``spec/schema.md``). Matches the agent's own free-text fallback so behavior is consistent.
DEFAULT_ACTIVITIES_BUDGET_USD = 1500.0

#: Safety cap on feedback rounds (one per category, plus slack) so a misbehaving graph can't loop.
MAX_FEEDBACK_TURNS = 25

_USD = "USD"


class ActivitiesAdapter(Agent):
    """Wraps the travel-agent as tripper's Activities agent (domain ``activities``)."""

    domain = Domain.activities
    selection_mode = SelectionMode.multi

    def __init__(self, settings: Settings) -> None:
        # Build the agent's Settings once from tripper's config; the ActivitiesAgent itself is
        # constructed fresh per run and discarded (stateless driving, ``spec/agents.md``).
        self._agent_settings = AgentSettings.from_env(env=settings.activities_agent_env())

    def run(self, trip: TripInput) -> DomainSearchResult:
        """Drive the agent statelessly to a completed itinerary and map its activities.

        Raises only on a transport failure (the agent reports ``status: "error"``); an unlocatable
        destination or a run that produced no activities is a valid empty outcome with a warning.
        """
        trip_request = _to_trip_request(trip)
        if trip_request is None:
            return DomainSearchResult(
                suggestions=[],
                warnings=["activities need a destination; skipped"],
            )

        agent = ActivitiesAgent(self._agent_settings)  # fresh session; discarded when run returns
        response = _require_ok(agent.handle({"action": "start", "trip": trip_request}))

        suggestions: list[Suggestion] = []
        per_category: dict[str, int] = {}
        turns = 0
        while response.get("status") == "awaiting_feedback" and turns < MAX_FEEDBACK_TURNS:
            turns += 1
            category, names = _collect_round(response, suggestions, per_category)
            # No user feedback in a round-1 search: accept the category's picks and advance. The
            # user's own wanted/unwanted loop is tripper's refine (Batch 13), not this conversation.
            response = _require_ok(
                agent.handle(
                    {
                        "action": "feedback",
                        "session_id": response["session_id"],
                        "feedback": {"selected": names, "approve": True},
                    }
                )
            )

        warnings = _run_warnings(response, suggestions, turns)
        return DomainSearchResult(
            suggestions=suggestions,
            diagnostics=_diagnostics(response),
            warnings=warnings,
            counts={"total": len(suggestions), "per_category": per_category},
        )


def _to_trip_request(trip: TripInput) -> dict[str, Any] | None:
    """Map a :class:`TripInput` to the agent's ``start`` trip dict, or ``None`` with no destination.

    Shared context supplies destination + dates + travelers (``spec/schema.md``); the activities
    fields supply budget / interests / pace. ``interests`` is omitted when null so the agent applies
    its own default (culture, food).
    """
    destination = _destination(trip.place)
    if destination is None:
        return None
    request: dict[str, Any] = {
        "destination": destination,
        "start_date": trip.stay.check_in.isoformat(),
        "end_date": trip.stay.check_out.isoformat(),
        "budget_usd": trip.activities_budget_usd or DEFAULT_ACTIVITIES_BUDGET_USD,
        "travelers": _travelers(trip),
        "travel_style": trip.travel_style.value,
    }
    if trip.interests:
        request["interests"] = [interest.value for interest in trip.interests]
    return request


def _destination(place: Place) -> str | None:
    """The destination the agent geocodes (``city``, else free ``text``); center-only → ``None``."""
    if place.city and place.city.strip():
        return place.city.strip()
    if place.text and place.text.strip():
        return place.text.strip()
    return None


def _travelers(trip: TripInput) -> int:
    """Party size for the agent (adults + children), clamped to the agent's 1..20 range."""
    total = trip.guests.adults + len(trip.guests.children_ages)
    return max(1, min(total, 20))


def _collect_round(
    response: dict[str, Any],
    suggestions: list[Suggestion],
    per_category: dict[str, int],
) -> tuple[str, list[str]]:
    """Append this round's recommended activities as suggestions; return (category, kept names).

    The awaiting response's ``recommendations`` is a ``RecommendationResponse``-shaped dict; its
    ``recommendations`` list is the round's :class:`RecommendedActivity` items (``spec/agents.md``).
    """
    block = response.get("recommendations") or {}
    category = block.get("category") or "activities"
    activities = block.get("recommendations") or []

    names: list[str] = []
    start_index = per_category.get(category, 0)
    for offset, activity in enumerate(activities):
        index = start_index + offset
        suggestions.append(
            Suggestion(id=f"{category}-{index}", item=_activity_to_item(activity, category))
        )
        if activity.get("name"):
            names.append(activity["name"])
    per_category[category] = start_index + len(activities)
    return category, names


def _activity_to_item(activity: dict[str, Any], category: str) -> ResultItem:
    """One :class:`RecommendedActivity` dict → the neutral :class:`ResultItem` + its raw ``detail``.

    ``RecommendedActivity`` carries no booking link, so ``url`` is ``None`` (``spec/agents.md``);
    the full activity is preserved in ``detail`` for the domain renderer.
    """
    cost = activity.get("estimated_cost_usd")
    badges = ["reservation required"] if activity.get("reservation_required") else []
    return ResultItem(
        title=activity.get("name") or "Activity",
        subtitle=category,
        price=None if cost is None else Price(amount=cost, per=PricePer.person, currency=_USD),
        badges=badges,
        rationale=activity.get("description"),
        detail={"activity": activity, "category": category},
    )


def _diagnostics(response: dict[str, Any]) -> dict[str, Any]:
    """The completed itinerary + reservation checklist for the domain doc (``spec/schema.md``)."""
    diagnostics: dict[str, Any] = {"status": response.get("status")}
    for key in ("itinerary", "reservation_checklist", "user_preferences"):
        if response.get(key) is not None:
            diagnostics[key] = response[key]
    return diagnostics


def _run_warnings(response: dict[str, Any], suggestions: list[Suggestion], turns: int) -> list[str]:
    """Explain a non-``completed`` outcome (empty results / non-convergence) as warnings."""
    warnings: list[str] = []
    status = response.get("status")
    if status != "completed":
        warnings.append(f"activities run ended as {status!r} without a completed itinerary")
    if turns >= MAX_FEEDBACK_TURNS and status == "awaiting_feedback":
        warnings.append("activities run did not converge within the feedback-round cap")
    if not suggestions:
        warnings.append("no activities were recommended")
    return warnings


def _require_ok(response: dict[str, Any]) -> dict[str, Any]:
    """Return the agent response, or raise on a reported error (a transport failure to the run)."""
    if response.get("status") == "error":
        raise RuntimeError(f"activities agent error: {response.get('error')}")
    return response
