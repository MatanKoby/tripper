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
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from tripper.contract import Domain, Feedback, LensName, ResultItem, SelectionMode, TripInput


class RefineNotSupported(NotImplementedError):
    """Raised by :meth:`Agent.refine` when a domain has no refine path yet.

    The hotel agent's refine (``hotel_finder.refine_sync``) is upstream WIP (``spec/agents.md`` /
    ``spec/roadmap.md``), so the accommodations adapter inherits this guard: a hotel refinement doc
    fails cleanly (its ``status`` -> ``error``) instead of the run crashing. Flights and activities
    override :attr:`Agent.supports_refine` + :meth:`Agent.refine`, so this never fires for them.
    """


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
class PriorCandidate:
    """A prior-round candidate plus the user's feedback, fed into a refine run (``spec/flows.md``).

    The orchestrator reads these off the domain's ``suggested/*`` docs (id, the neutral item, the
    wanted/unwanted ``feedback`` mark, and the ``lens`` / ``round`` group keys) and hands them to
    the adapter's :meth:`Agent.refine`, which folds the marks into its agent's request
    (``spec/agents.md``). ``id`` is the stored doc id (so the orchestrator can later dismiss it).
    """

    id: str
    item: ResultItem
    feedback: Feedback | None = None
    lens: LensName | None = None
    round: int = 1


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
    #: Whether this domain supports the wanted/unwanted refine loop. ``False`` (the default) means
    #: :meth:`refine` raises :class:`RefineNotSupported`; flights/activities set it ``True``. The
    #: hotel agent keeps ``False`` until ``refine_sync`` lands upstream (``spec/agents.md``).
    supports_refine: bool = False

    @abstractmethod
    def run(self, trip: TripInput) -> DomainSearchResult:
        """Run the agent for ``trip`` and return its neutral candidates + run metadata.

        Raise on a transport failure (import / call / timeout); the orchestrator turns that into a
        terminal ``agentStatus: "error"`` on the domain doc. A *data* outcome with no results is not
        an exception: it is a valid :class:`DomainSearchResult` with an empty ``suggestions`` list
        and any explanation in ``warnings`` (``spec/schema.md``).
        """
        raise NotImplementedError

    def refine(self, trip: TripInput, prior: Sequence[PriorCandidate]) -> DomainSearchResult:
        """Re-run the agent with the user's wanted/unwanted marks folded in (``spec/flows.md``).

        The result shape is identical to :meth:`run` (the orchestrator appends it as the next
        round); the same transport-failure-vs-empty-outcome contract applies. Flights and activities
        fold the marks into their request and re-run search (no dedicated agent refine entry point,
        ``spec/agents.md``); the default here raises :class:`RefineNotSupported` so a domain with no
        refine path (hotel, until ``refine_sync``) fails cleanly rather than silently doing nothing.
        """
        raise RefineNotSupported(f"{self.domain.value} refine is not available yet")
