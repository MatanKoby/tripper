# UI (frontend layout)

M1 is an unstyled wireframe: correct layout and a working end-to-end flow, no visual design. Built
with Vite + React (`architecture.md`). Input shape is in `schema.md`; the job lifecycle it drives is
in `flows.md`; sign-in and access in `access.md`.

## Layout

A single scrolling page with three domain sections, in a three-column frame:

- **Left**: a vertical tab nav with **Flights**, **Accommodation**, **Activities**. Clicking a tab
  scroll-jumps to that section. It is navigation, not separate pages.
- **Center**: one results container per section, stacked in the same order. In M1 only
  **Accommodation** is populated (from the hotel agent); **Flights** and **Activities** show
  "coming soon" placeholders (they arrive with their agents: `roadmap.md`).
- **Right** (proposed, flagged): the **trip-input form** (`schema.md` under Trip input) + a submit
  button, plus the **job status** indicator ("thinking / warming up", and errors). This is where the
  user enters parameters and starts a job. Alternative under consideration: move the form to a top
  bar instead of the right column.

## Behavior

- The user must be signed in (`access.md`). On submit, the FE writes the job doc and listens on it
  (`flows.md`).
- While `pending` / `running`, the Accommodation container shows the "thinking / warming up" state
  (the first request can take a few minutes on a cold start: `architecture.md`).
- On `done`, it renders `results.hotel.lenses` (the three lens groups; flatten to a single list if
  we keep the wireframe minimal). On `error`, it shows the message.
