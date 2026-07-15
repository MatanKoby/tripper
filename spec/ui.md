# UI (frontend layout + visual design)

M1 shipped as an unstyled wireframe. This file now also specifies the **visual design**: apply it
on top of the existing layout without changing behavior, data flow, or component boundaries. Built
with Vite + React (`architecture.md`). Input shape is in `schema.md`; the job lifecycle it drives is
in `flows.md`; sign-in and access in `access.md`.

## Layout

A single scrolling page with three domain sections, in a three-column frame
(`170px | 1fr | 330px`, max-width 1240px, centered, 24px column gap):

- **Left**: a vertical tab nav with **Flights**, **Accommodation**, **Activities**. Clicking a tab
  scroll-jumps (smooth) to that section. It is navigation, not separate pages. Sticky
  (`top: 20px`).
- **Center**: one results container per section, stacked in the same order. In M1 only
  **Accommodation** is populated (from the hotel agent); **Flights** and **Activities** show
  "coming soon" placeholders (they arrive with their agents: `roadmap.md`).
- **Right**: the **trip-input form** (`schema.md` under Trip input) + a submit button, plus the
  **job status** indicator. Sticky (`top: 20px`).
- **Header** above the frame: the "Tripper" wordmark on the left, the signed-in user (avatar
  initial + name) on the right.
- **Responsive** (≤ 980px): collapse to a single column; the nav becomes a horizontal tab row;
  the form column moves to the top (this implements the "top bar" alternative previously under
  consideration).

## Behavior (unchanged)

- The user must be signed in (`access.md`). On submit, the FE writes the job doc and listens on it
  (`flows.md`).
- A **Quick fill** row above the form offers premade trips (e.g. Barcelona next weekend, 2 adults)
  that one-click populate every field (`schema.md` under Trip input); the fields stay editable
  before submit. Preset dates are relative to today, so a preset is always a future-valid query. A
  dev/demo convenience, not a product feature.
- While `pending` / `running`, the Accommodation container shows the "thinking / warming up" state
  (the first request can take a few minutes on a cold start: `architecture.md`).
- On `done`, it renders `results.hotel.lenses` grouped by lens. On `error`, it shows the message.
- Submitting scroll-jumps to the Accommodation section and disables the submit button until the
  job resolves.

## Design system

Modern and calm, not loud. One primary color (petrol teal), one warm accent (amber) used only for
attention points, everything else neutral. Implement as CSS variables in a single global
stylesheet (or CSS module) scoped under a root class; no UI framework, no Tailwind.

### Tokens

```css
--ink:       #16292F;  /* primary text */
--teal:      #0F6B70;  /* primary: buttons, ratings, links, spinner */
--teal-deep: #0A474B;  /* hover / headings-on-teal / wordmark */
--sun:       #E8A13D;  /* accent: active-tab marker, quick-fill chips, lens markers, warm status */
--mist:      #F2F6F6;  /* page background */
--card:      #FFFFFF;  /* card surfaces */
--line:      #DBE6E6;  /* borders */
--slate:     #557075;  /* secondary text */
```

Page background: `--mist` plus one subtle radial teal wash in the top-right:
`radial-gradient(1200px 400px at 80% -10%, rgba(15,107,112,0.08), transparent 60%)`.

### Typography

- **Display** (wordmark, section headings, prices): `Fraunces` (Google Fonts), weights 500/600,
  slight negative letter-spacing on the wordmark.
- **Body / UI**: `Inter`, weights 400/500/600, base 14px.
- Import both via one Google Fonts `@import` in the stylesheet.
- Wordmark: "Tripper" in Fraunces 600, 26px, `--teal-deep`, with the final period in `--sun`.

### Components

- **Nav tabs**: borderless buttons, `--slate` text; hover = faint teal tint background. Active tab:
  white background, soft shadow, `--teal-deep` text, and a 3px `--sun` bar on the left edge (bottom
  edge in the responsive horizontal variant). Not-yet-available tabs (Flights, Activities) carry a
  small muted dot.
- **Section headings**: Fraunces 600, 21px, with an uppercase pill badge ("Coming soon") next to
  placeholder sections — 11px, `--slate` text, white background, `--line` border, fully rounded.
- **Cards** (shared surface style): white, 1px `--line` border, 14px radius. Hotel cards get a
  hover lift: `translateY(-1px)` + soft teal-tinted shadow.
- **Hotel card**: name (Inter 600, 15px), area (`--teal`, 12px), one-line note (`--slate`). Right
  side, separated by a **dashed** `--line` vertical divider (ticket-stub nod): rating in a
  `--teal` filled rounded chip (white text), then price in Fraunces 600 19px with a small
  "/night" suffix in Inter `--slate`.
- **Lens groups**: results render grouped by lens, in order. Each group header: lens name in
  `--teal-deep` 600 preceded by a small `--sun` diamond (8px square rotated 45°), plus a muted
  count ("2 options in Barcelona").
- **Quick fill chips**: pill buttons in translucent amber — `rgba(232,161,61,.12)` background,
  `rgba(232,161,61,.5)` border, dark-amber text (#8A5A14); darker amber tint on hover.
- **Form**: one white card. Labels 12px `--slate`; inputs with `--line` borders, 9px radius,
  near-white (#FBFDFD) background. Check-in/check-out and adults/budget as two-up rows. Submit
  button: full-width, `--teal` filled, white 600 text, `--teal-deep` on hover, reduced opacity
  when disabled.
- **Small uppercase labels** ("Quick fill", "Plan a trip"): 11px, 600, letter-spacing .06em,
  `--slate`.

### States (Accommodation container)

- **Idle**: dashed-border card, centered muted copy inviting the user to fill the form or use a
  Quick fill.
- **Pending / running** ("thinking / warming up"): white card with a teal ring spinner
  (~0.9s rotation); title "Warming up…" while `pending`, "Thinking…" while `running`; subtitle
  notes the cold-start wait. Below: 3 shimmer skeleton rows (light teal-grey gradient sweep,
  staggered delays).
- **Done**: lens groups + hotel cards as above.
- **Error**: red-tinted card — `rgba(196,74,58,.08)` background, matching border, #A03A2C text —
  showing the job's error message.
- **Job status pill** (under the submit button): dot + short text. Warm amber tint while
  `pending`/`running` (dot pulses), teal tint on `done`, red tint on `error`. Hidden when idle.
- **Coming-soon placeholders** (Flights, Activities): dashed-border card, small muted glyph, one
  line of copy pointing the user to Accommodation for now.

### Quality floor

- Visible keyboard focus: 2px `--teal` outline with 2px offset on all interactive elements.
- `prefers-reduced-motion: reduce` disables the spinner, shimmer, and pulse animations.
- All transitions short (~150ms) and limited to background, color, shadow, and 1px lifts.

## Editing convention

Reference implementation of this design (mock data, all states clickable): `tripper-ui.jsx` from
the design pass — match its rendered result, not its component structure; keep the project's
existing components and wire the styles into them.
