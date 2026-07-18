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

from collections.abc import Sequence
from typing import Any

from travel_agent import ActivitiesAgent
from travel_agent import Settings as AgentSettings

from tripper.agents.base import Agent, DomainSearchResult, PriorCandidate, Suggestion
from tripper.config import Settings
from tripper.contract import (
    Domain,
    Feedback,
    InterestGroup,
    Place,
    Price,
    PricePer,
    ResultItem,
    SelectionMode,
    TripInput,
)

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
    supports_refine = True  # refine = a fresh stateless run with the feedback folded in (agents.md)

    def __init__(self, settings: Settings) -> None:
        # Build the agent's Settings once from tripper's config; the ActivitiesAgent itself is
        # constructed fresh per run and discarded (stateless driving, ``spec/agents.md``).
        self._agent_settings = AgentSettings.from_env(env=settings.activities_agent_env())

    def run(self, trip: TripInput) -> DomainSearchResult:
        """Drive the agent statelessly to a completed itinerary and map its activities.

        Raises only on a transport failure (the agent reports ``status: "error"``); an unlocatable
        destination or a run that produced no activities is a valid empty outcome with a warning.
        """
        return self._drive(_to_trip_request(trip))

    def refine(self, trip: TripInput, prior: Sequence[PriorCandidate]) -> DomainSearchResult:
        """A fresh stateless run with the wanted/unwanted marks folded in (``spec/agents.md``).

        Never a resume: a new ``start`` request whose ``interests`` gains the categories of liked
        activities and drops those of disliked ones, and whose ``notes`` name the liked/disliked
        activities. The state lives in Firestore, not the agent; the run is driven to completion and
        appended as the next round exactly like a search.
        """
        trip_request = _to_trip_request(trip)
        if trip_request is not None:
            _fold_feedback(trip_request, prior)
        return self._drive(trip_request)

    def _drive(self, trip_request: dict[str, Any] | None) -> DomainSearchResult:
        """Statelessly drive one ``start`` request to a completed itinerary and map it (agents.md).

        Shared by :meth:`run` and :meth:`refine`: a fresh ``ActivitiesAgent`` is started, its
        per-category feedback rounds are accepted to advance the graph to ``completed``, and the
        instance is discarded — no ``session_id`` is persisted. ``None`` (no destination) is a valid
        empty outcome with a warning.
        """
        if trip_request is None:
            return DomainSearchResult(
                suggestions=[],
                warnings=["activities need a destination; skipped"],
            )

        agent = ActivitiesAgent(self._agent_settings)  # fresh session; discarded when this returns
        response = _require_ok(agent.handle({"action": "start", "trip": trip_request}))

        suggestions: list[Suggestion] = []
        per_category: dict[str, int] = {}
        turns = 0
        while response.get("status") == "awaiting_feedback" and turns < MAX_FEEDBACK_TURNS:
            turns += 1
            category, names = _collect_round(response, suggestions, per_category)
            # The wanted/unwanted marks were folded into the ``start`` request up front (refine) or
            # are absent (search); here we just accept each category's picks to advance the graph.
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


def _fold_feedback(trip_request: dict[str, Any], prior: Sequence[PriorCandidate]) -> None:
    """Fold the wanted/unwanted marks into a fresh ``start`` request, in place (``spec/agents.md``).

    ``interests`` gains the categories of liked activities and drops those of disliked ones (only
    categories that are known :class:`InterestGroup`s; the agent groups by these). ``notes`` names
    the liked/disliked activities in free text, which the agent reads even when a category is not a
    mappable group. If every interest is dropped the key is omitted so the agent re-defaults.
    """
    liked_names = [c.item.title for c in prior if c.feedback is Feedback.liked]
    disliked_names = [c.item.title for c in prior if c.feedback is Feedback.disliked]
    if not liked_names and not disliked_names:
        return

    interests = {InterestGroup(i) for i in trip_request.get("interests", [])}
    interests |= {g for c in prior if c.feedback is Feedback.liked and (g := _as_interest(c))}
    interests -= {g for c in prior if c.feedback is Feedback.disliked and (g := _as_interest(c))}
    if interests:
        # Keep a stable order (the InterestGroup declaration order) for a deterministic request.
        trip_request["interests"] = [g.value for g in InterestGroup if g in interests]
    else:
        trip_request.pop("interests", None)

    notes = [trip_request["notes"]] if trip_request.get("notes") else []
    if liked_names:
        notes.append("Prioritize activities like: " + ", ".join(liked_names) + ".")
    if disliked_names:
        notes.append("Avoid activities like: " + ", ".join(disliked_names) + ".")
    trip_request["notes"] = " ".join(notes)


def _as_interest(candidate: PriorCandidate) -> InterestGroup | None:
    """The candidate's category as an :class:`InterestGroup`, or ``None`` when it maps to none.

    The category is stored on the candidate's ``subtitle`` (the adapter set it there), falling back
    to ``detail.category``; a value that is not one of the 8 groups yields ``None`` (notes still
    carry its name).
    """
    category = candidate.item.subtitle or candidate.item.detail.get("category")
    try:
        return InterestGroup(category)
    except ValueError:
        return None


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
