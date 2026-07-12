"""The adapter interface between the orchestrator and a domain agent.

The orchestrator (``tripper.orchestrator``) knows only this interface and the contract
(``spec/schema.md``). Each concrete adapter wraps its agent's clean API, supplies the agent's
config built from tripper's :class:`~tripper.config.Settings`, and maps the agent's result to a
contract payload (``spec/architecture.md`` under *Agent contract + adapters*). Keeping the agent
call behind this seam lets the reliability machinery be exercised with an in-test fake, and lets
the real hotel adapter land later (Batch 10) without touching the orchestrator.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from tripper.contract import HotelPayload, TripInput


class Agent(ABC):
    """A domain agent as seen by the orchestrator.

    ``name`` is the slot the agent fills in the transport wrapper (``spec/schema.md``); M1 has a
    single agent whose name is ``"hotel"``.
    """

    #: Slot this agent fills in :class:`~tripper.contract.TripSuggestions`, e.g. ``"hotel"``.
    name: str

    @abstractmethod
    def run(self, trip: TripInput) -> HotelPayload:
        """Run the agent for ``trip`` and return its contract payload.

        Raise on a transport failure (import / call / timeout); the orchestrator turns that into a
        terminal ``error``. A *data* outcome with no results is not an exception: it is a valid
        payload with ``agent_status`` ``empty`` or ``degraded`` (``spec/schema.md``).
        """
        raise NotImplementedError
