"""The adapter interface between the orchestrator and a domain agent (``spec/architecture.md``).

The orchestrator (``tripper.orchestrator``) knows only this interface and the neutral storage shape
(``spec/schema.md``). Each concrete adapter wraps its agent's clean API, supplies the agent's config
built from tripper's :class:`~tripper.config.Settings`, and maps the agent's result to a list of
neutral :class:`~tripper.contract.ResultItem` candidates plus per-domain run metadata
(:class:`DomainSearchResult`). Keeping the call behind this seam lets the reliability machinery
be exercised with an in-test fake, and lets each domain adapter map its own payload without the
orchestrator ever learning an agent-specific shape.

M2 fans out to one ``domains/{domain}`` doc per active agent (``spec/flows.md``); this is the seam
each domain's search run drives. A refine run (Batch 13) reuses it with the feedback folded in.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from tripper.contract import Domain, LensName, ResultItem, SelectionMode, TripInput


@dataclass(frozen=True)
class Suggestion:
    """One candidate the adapter produces: its stable id, the neutral item, and an optional lens.

    ``id`` is unique within a run and becomes the ``suggested`` doc id (``spec/schema.md``); the
    adapter owns it (hotel: derived per pick until the agent exposes a stable ``Pick.id``,
    ``spec/agents.md``). ``lens`` is the hotel grouping key and ``None`` for domains without lenses.
    """

    id: str
    item: ResultItem
    lens: LensName | None = None


@dataclass(frozen=True)
class DomainSearchResult:
    """An adapter's neutral output for one run: the candidates plus the domain-doc run metadata.

    ``diagnostics`` / ``warnings`` / ``counts`` land on the ``domains/{domain}`` doc (``schema.md``
    → Domain); the orchestrator writes ``suggestions`` into ``suggested/*`` and never inspects their
    domain-specific ``detail``.
    """

    suggestions: list[Suggestion]
    diagnostics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, Any] = field(default_factory=dict)


class Agent(ABC):
    """A domain agent as seen by the orchestrator.

    ``domain`` is the slot the agent fills and ``selection_mode`` how many items
    the user may select there (``spec/schema.md``). The orchestrator reads both to fan out and to
    seed each domain doc; it otherwise only calls :meth:`run`.
    """

    #: The domain this agent fills, e.g. :attr:`~tripper.contract.Domain.accommodations`.
    domain: Domain
    #: How many items this domain lets the user select (accommodations: ``single``).
    selection_mode: SelectionMode

    @abstractmethod
    def run(self, trip: TripInput) -> DomainSearchResult:
        """Run the agent for ``trip`` and return its neutral candidates + run metadata.

        Raise on a transport failure (import / call / timeout); the orchestrator turns that into a
        terminal ``agentStatus: "error"`` on the domain doc. A *data* outcome with no results is not
        an exception: it is a valid :class:`DomainSearchResult` with an empty ``suggestions`` list
        and any explanation in ``warnings`` (``spec/schema.md``).
        """
        raise NotImplementedError
