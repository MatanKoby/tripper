# UI (frontend layout)

The frontend is an unstyled wireframe: correct layout and a working end-to-end flow, no visual
design (styling deferred, `roadmap.md`). Built with Vite + React (`architecture.md`). Input shape is
in `schema.md`; the per-domain data model and the lifecycle it drives are in `schema.md` / `flows.md`;
sign-in and access in `access.md`. Each domain renders with its **own** renderer (its own flair) over
the neutral `ResultItem` + `detail`, so the sections don't share one generic card.

## Layout

A single scrolling page with three domain sections, in a three-column frame:

- **Left**: a vertical tab nav with **Flights**, **Accommodation**, **Activities**. Clicking a tab
  scroll-jumps to that section. It is navigation, not separate pages.
- **Center**: one results container per section, stacked in the same order. **Accommodation** is
  populated first (M2, from the hotel agent); **Flights** and **Activities** show "coming soon" until
  their agents integrate onto the same schema (`roadmap.md`).
- **Right** (proposed, flagged): the **trip-input form** (`schema.md` under Trip input) + a submit
  button, plus the **job status** indicator ("thinking / warming up", and errors). This is where the
  user enters parameters and starts a job. Alternative under consideration: move the form to a top
  bar instead of the right column.

## Behavior

- The user must be signed in (`access.md`). On submit, the FE creates the trip doc and listens on it
  plus each domain's `suggested` (`flows.md`).
- A **Quick fill** row above the form offers premade trips (e.g. Barcelona next weekend, 2 adults)
  that one-click populate every field (`schema.md` under Trip input); the fields stay editable
  before submit. Preset dates are relative to today, so a preset is always a future-valid query. A
  dev/demo convenience for exercising the flow, not a product feature.
- Each section is driven by its own `domains/{domain}.agentStatus` (`flows.md`): `pending` /
  `running` shows the "thinking / warming up" state (a first request can take a few minutes on a cold
  start, `architecture.md`); `idle` renders `suggested`; `error` shows the message.
- **Rendering:** the domain's own renderer draws each `suggested` card from `ResultItem` + `detail`;
  accommodations groups by `lens` and hides `dismissed` candidates.
- **Feedback & refine:** each suggestion card has like / dislike controls that write `feedback`
  (`schema.md`); a per-section **Refine** button, enabled only when the domain is `idle`, creates a
  `refinements` doc to fetch more that fit the marks (`flows.md`).
- **Selection:** selecting a card writes a `selected` doc; accommodations is single-select and shows
  the chosen hotel in a selected slot.
