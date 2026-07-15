import { useEffect, useRef, useState } from "react";

// ---------- mock data (stands in for results.hotel.lenses) ----------
const MOCK_LENSES = [
  {
    lens: "Best value",
    hotels: [
      { name: "Hotel Curious", area: "El Raval", price: 112, rating: 8.7, note: "Compact rooms, great location, free late checkout on weekdays." },
      { name: "Acta Voraport", area: "Poblenou", price: 98, rating: 8.4, note: "Rooftop pool, 5 min walk to the beach, quiet at night." },
    ],
  },
  {
    lens: "Boutique",
    hotels: [
      { name: "Casa Bonay", area: "Eixample", price: 178, rating: 8.9, note: "1898 building, in-house coffee bar, strong design identity." },
      { name: "Praktik Vinoteca", area: "Eixample", price: 155, rating: 8.8, note: "Wine-themed, nightly tastings included." },
    ],
  },
  {
    lens: "Family-friendly",
    hotels: [
      { name: "Aparthotel Bcn Montjuic", area: "Sants", price: 141, rating: 8.5, note: "Kitchenettes, cribs on request, near metro L3." },
    ],
  },
];

const PRESETS = [
  { label: "Barcelona · next weekend", dest: "Barcelona", nights: 2, adults: 2, budget: 180 },
  { label: "Lisbon · 4 nights", dest: "Lisbon", nights: 4, adults: 2, budget: 150 },
  { label: "Rome · family week", dest: "Rome", nights: 7, adults: 2, budget: 220 },
];

function futureDate(offsetDays) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

// ---------- root ----------
export default function TripperApp() {
  const [form, setForm] = useState({ dest: "", checkin: futureDate(10), checkout: futureDate(12), adults: 2, budget: "" });
  const [job, setJob] = useState({ status: "idle" }); // idle | pending | running | done | error
  const [active, setActive] = useState("stay");
  const sections = { flights: useRef(null), stay: useRef(null), activities: useRef(null) };

  const jump = (key) => {
    setActive(key);
    sections[key].current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const applyPreset = (p) =>
    setForm({ dest: p.dest, checkin: futureDate(9), checkout: futureDate(9 + p.nights), adults: p.adults, budget: p.budget });

  const submit = () => {
    if (!form.dest) { setJob({ status: "error", msg: "Destination is required." }); return; }
    setJob({ status: "pending" });
    jump("stay");
    // demo of the async job lifecycle: pending -> running -> done
    setTimeout(() => setJob({ status: "running" }), 900);
    setTimeout(() => setJob({ status: "done", results: MOCK_LENSES }), 3400);
  };

  return (
    <div className="trp-root">
      <style>{CSS}</style>

      <header className="trp-header">
        <div className="trp-wordmark">
          Tripper<span className="trp-dot">.</span>
        </div>
        <div className="trp-user">
          <span className="trp-avatar">N</span> Signed in as Nadav
        </div>
      </header>

      <div className="trp-frame">
        {/* left: tab nav */}
        <nav className="trp-nav">
          <NavTab k="flights" label="Flights" active={active} onClick={jump} soon />
          <NavTab k="stay" label="Accommodation" active={active} onClick={jump} />
          <NavTab k="activities" label="Activities" active={active} onClick={jump} soon />
        </nav>

        {/* center: stacked results */}
        <main className="trp-main">
          <Section refEl={sections.flights} title="Flights" soon>
            <ComingSoon what="Flight suggestions" />
          </Section>

          <Section refEl={sections.stay} title="Accommodation">
            <StayResults job={job} dest={form.dest} />
          </Section>

          <Section refEl={sections.activities} title="Activities" soon>
            <ComingSoon what="Activity suggestions" />
          </Section>
        </main>

        {/* right: trip input + job status */}
        <aside className="trp-side">
          <div className="trp-quick">
            <div className="trp-label">Quick fill</div>
            <div className="trp-chips">
              {PRESETS.map((p) => (
                <button key={p.label} className="trp-chip" onClick={() => applyPreset(p)}>{p.label}</button>
              ))}
            </div>
          </div>

          <div className="trp-form">
            <div className="trp-label">Plan a trip</div>
            <Field label="Destination">
              <input value={form.dest} placeholder="Where to?" onChange={(e) => setForm({ ...form, dest: e.target.value })} />
            </Field>
            <div className="trp-row2">
              <Field label="Check-in"><input type="date" value={form.checkin} onChange={(e) => setForm({ ...form, checkin: e.target.value })} /></Field>
              <Field label="Check-out"><input type="date" value={form.checkout} onChange={(e) => setForm({ ...form, checkout: e.target.value })} /></Field>
            </div>
            <div className="trp-row2">
              <Field label="Adults"><input type="number" min="1" value={form.adults} onChange={(e) => setForm({ ...form, adults: e.target.value })} /></Field>
              <Field label="Budget / night (€)"><input type="number" min="0" value={form.budget} placeholder="Any" onChange={(e) => setForm({ ...form, budget: e.target.value })} /></Field>
            </div>
            <button className="trp-submit" onClick={submit} disabled={job.status === "pending" || job.status === "running"}>
              {job.status === "pending" || job.status === "running" ? "Searching…" : "Find my trip"}
            </button>
            <StatusPill job={job} />
          </div>
        </aside>
      </div>
    </div>
  );
}

// ---------- pieces ----------
function NavTab({ k, label, active, onClick, soon }) {
  return (
    <button className={"trp-tab" + (active === k ? " is-active" : "")} onClick={() => onClick(k)}>
      <span>{label}</span>
      {soon && <span className="trp-soon-dot" title="Coming soon" />}
    </button>
  );
}

function Section({ refEl, title, soon, children }) {
  return (
    <section ref={refEl} className="trp-section">
      <div className="trp-section-head">
        <h2>{title}</h2>
        {soon && <span className="trp-badge">Coming soon</span>}
      </div>
      {children}
    </section>
  );
}

function ComingSoon({ what }) {
  return (
    <div className="trp-empty">
      <div className="trp-empty-art" aria-hidden>✈</div>
      <p>{what} arrive with their agent. For now, start with a place to stay.</p>
    </div>
  );
}

function StayResults({ job, dest }) {
  if (job.status === "idle")
    return (
      <div className="trp-empty">
        <div className="trp-empty-art" aria-hidden>🏨</div>
        <p>Fill in the trip on the right (or tap a Quick fill) and Tripper will suggest places to stay.</p>
      </div>
    );

  if (job.status === "pending" || job.status === "running")
    return (
      <div className="trp-thinking">
        <div className="trp-spinner" aria-hidden />
        <div>
          <div className="trp-thinking-title">{job.status === "pending" ? "Warming up…" : "Thinking…"}</div>
          <div className="trp-thinking-sub">The first search can take a few minutes on a cold start.</div>
        </div>
        <div className="trp-skeletons">{[0, 1, 2].map((i) => <div key={i} className="trp-skel" style={{ animationDelay: `${i * 0.15}s` }} />)}</div>
      </div>
    );

  if (job.status === "error")
    return <div className="trp-error"><strong>Something went wrong.</strong> {job.msg || "Try submitting again."}</div>;

  return (
    <div className="trp-lenses">
      {job.results.map((group) => (
        <div key={group.lens} className="trp-lens">
          <div className="trp-lens-head">
            <span className="trp-lens-name">{group.lens}</span>
            <span className="trp-lens-count">{group.hotels.length} option{group.hotels.length > 1 ? "s" : ""}{dest ? ` in ${dest}` : ""}</span>
          </div>
          <div className="trp-cards">
            {group.hotels.map((h) => <HotelCard key={h.name} h={h} />)}
          </div>
        </div>
      ))}
    </div>
  );
}

function HotelCard({ h }) {
  return (
    <article className="trp-card">
      <div className="trp-card-main">
        <h3>{h.name}</h3>
        <div className="trp-card-area">{h.area}</div>
        <p>{h.note}</p>
      </div>
      <div className="trp-card-side">
        <div className="trp-rating">{h.rating}</div>
        <div className="trp-price">€{h.price}<span>/night</span></div>
      </div>
    </article>
  );
}

function StatusPill({ job }) {
  const map = {
    idle: null,
    pending: { cls: "warm", text: "Job queued — warming up" },
    running: { cls: "warm", text: "Agent running…" },
    done: { cls: "ok", text: "Done — results below" },
    error: { cls: "err", text: job.msg || "Error" },
  };
  const s = map[job.status];
  if (!s) return null;
  return <div className={`trp-status trp-status--${s.cls}`}><span className="trp-status-dot" />{s.text}</div>;
}

function Field({ label, children }) {
  return (
    <label className="trp-field">
      <span>{label}</span>
      {children}
    </label>
  );
}

// ---------- styles ----------
const CSS = `
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Inter:wght@400;500;600&display=swap');

.trp-root {
  --ink: #16292F;
  --teal: #0F6B70;
  --teal-deep: #0A474B;
  --sun: #E8A13D;
  --mist: #F2F6F6;
  --card: #FFFFFF;
  --line: #DBE6E6;
  --slate: #557075;
  min-height: 100vh;
  background:
    radial-gradient(1200px 400px at 80% -10%, rgba(15,107,112,0.08), transparent 60%),
    var(--mist);
  color: var(--ink);
  font-family: 'Inter', system-ui, sans-serif;
  font-size: 14px;
}
.trp-root * { box-sizing: border-box; }
.trp-root button { font: inherit; cursor: pointer; }
.trp-root button:focus-visible, .trp-root input:focus-visible { outline: 2px solid var(--teal); outline-offset: 2px; }

/* header */
.trp-header { display: flex; justify-content: space-between; align-items: center; padding: 16px 28px; }
.trp-wordmark { font-family: 'Fraunces', serif; font-weight: 600; font-size: 26px; letter-spacing: -0.02em; color: var(--teal-deep); }
.trp-dot { color: var(--sun); }
.trp-user { display: flex; align-items: center; gap: 8px; color: var(--slate); font-size: 13px; }
.trp-avatar { width: 26px; height: 26px; border-radius: 50%; background: var(--teal); color: #fff; display: grid; place-items: center; font-weight: 600; font-size: 12px; }

/* frame: nav | results | form */
.trp-frame { display: grid; grid-template-columns: 170px minmax(0,1fr) 330px; gap: 24px; padding: 8px 28px 48px; max-width: 1240px; margin: 0 auto; }

/* left nav */
.trp-nav { position: sticky; top: 20px; align-self: start; display: flex; flex-direction: column; gap: 4px; }
.trp-tab { display: flex; align-items: center; justify-content: space-between; gap: 8px; text-align: left; padding: 10px 12px; border: 0; border-left: 3px solid transparent; border-radius: 0 8px 8px 0; background: transparent; color: var(--slate); font-weight: 500; transition: background .15s, color .15s; }
.trp-tab:hover { background: rgba(15,107,112,0.07); color: var(--teal-deep); }
.trp-tab.is-active { border-left-color: var(--sun); background: #fff; color: var(--teal-deep); box-shadow: 0 1px 4px rgba(22,41,47,0.06); }
.trp-soon-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--line); }

/* center */
.trp-main { display: flex; flex-direction: column; gap: 28px; min-width: 0; }
.trp-section { scroll-margin-top: 16px; }
.trp-section-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 12px; }
.trp-section-head h2 { font-family: 'Fraunces', serif; font-weight: 600; font-size: 21px; margin: 0; }
.trp-badge { font-size: 11px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: var(--slate); background: #fff; border: 1px solid var(--line); border-radius: 999px; padding: 3px 9px; }

/* empty / coming soon */
.trp-empty { background: var(--card); border: 1px dashed var(--line); border-radius: 14px; padding: 28px; text-align: center; color: var(--slate); }
.trp-empty-art { font-size: 22px; margin-bottom: 6px; opacity: .7; }
.trp-empty p { margin: 0 auto; max-width: 380px; line-height: 1.5; }

/* thinking */
.trp-thinking { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 22px; display: grid; grid-template-columns: auto 1fr; gap: 6px 14px; align-items: center; }
.trp-spinner { width: 26px; height: 26px; border-radius: 50%; border: 3px solid rgba(15,107,112,.2); border-top-color: var(--teal); animation: trp-spin 0.9s linear infinite; }
.trp-thinking-title { font-weight: 600; color: var(--teal-deep); }
.trp-thinking-sub { color: var(--slate); font-size: 13px; }
.trp-skeletons { grid-column: 1 / -1; display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }
.trp-skel { height: 52px; border-radius: 10px; background: linear-gradient(90deg, #EDF3F3 25%, #E2ECEC 45%, #EDF3F3 65%); background-size: 200% 100%; animation: trp-shimmer 1.4s ease infinite; }
@keyframes trp-spin { to { transform: rotate(360deg); } }
@keyframes trp-shimmer { to { background-position: -200% 0; } }
@media (prefers-reduced-motion: reduce) { .trp-spinner, .trp-skel { animation: none; } }

/* results */
.trp-lenses { display: flex; flex-direction: column; gap: 20px; }
.trp-lens-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 8px; }
.trp-lens-name { font-weight: 600; color: var(--teal-deep); font-size: 15px; }
.trp-lens-name::before { content: ""; display: inline-block; width: 8px; height: 8px; border-radius: 2px; background: var(--sun); margin-right: 8px; transform: rotate(45deg) translateY(-1px); }
.trp-lens-count { color: var(--slate); font-size: 12px; }
.trp-cards { display: flex; flex-direction: column; gap: 10px; }
.trp-card { display: flex; justify-content: space-between; gap: 16px; background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 16px 18px; transition: box-shadow .15s, transform .15s; }
.trp-card:hover { box-shadow: 0 6px 18px rgba(10,71,75,0.10); transform: translateY(-1px); }
.trp-card h3 { margin: 0; font-size: 15px; font-weight: 600; }
.trp-card-area { color: var(--teal); font-size: 12px; font-weight: 500; margin: 2px 0 6px; }
.trp-card p { margin: 0; color: var(--slate); line-height: 1.45; }
.trp-card-side { text-align: right; display: flex; flex-direction: column; align-items: flex-end; gap: 6px; border-left: 1px dashed var(--line); padding-left: 16px; min-width: 92px; justify-content: center; }
.trp-rating { background: var(--teal); color: #fff; border-radius: 8px; padding: 3px 8px; font-weight: 600; font-size: 13px; }
.trp-price { font-family: 'Fraunces', serif; font-size: 19px; font-weight: 600; color: var(--ink); }
.trp-price span { font-family: 'Inter', sans-serif; font-size: 11px; color: var(--slate); font-weight: 500; margin-left: 2px; }

/* right column */
.trp-side { position: sticky; top: 20px; align-self: start; display: flex; flex-direction: column; gap: 14px; }
.trp-label { font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--slate); margin-bottom: 8px; }
.trp-quick { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px; }
.trp-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.trp-chip { border: 1px solid rgba(232,161,61,.5); background: rgba(232,161,61,.12); color: #8A5A14; border-radius: 999px; padding: 5px 11px; font-size: 12.5px; font-weight: 500; transition: background .15s; }
.trp-chip:hover { background: rgba(232,161,61,.25); }
.trp-form { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
.trp-field { display: flex; flex-direction: column; gap: 4px; flex: 1; }
.trp-field span { font-size: 12px; font-weight: 500; color: var(--slate); }
.trp-field input { border: 1px solid var(--line); border-radius: 9px; padding: 8px 10px; font: inherit; background: #FBFDFD; color: var(--ink); width: 100%; }
.trp-field input::placeholder { color: #9FB4B7; }
.trp-row2 { display: flex; gap: 10px; }
.trp-submit { margin-top: 4px; border: 0; border-radius: 10px; padding: 11px; background: var(--teal); color: #fff; font-weight: 600; transition: background .15s; }
.trp-submit:hover:not(:disabled) { background: var(--teal-deep); }
.trp-submit:disabled { opacity: .6; cursor: default; }

/* status pill */
.trp-status { display: flex; align-items: center; gap: 8px; border-radius: 10px; padding: 9px 12px; font-size: 13px; font-weight: 500; }
.trp-status-dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
.trp-status--warm { background: rgba(232,161,61,.14); color: #8A5A14; }
.trp-status--warm .trp-status-dot { animation: trp-pulse 1.1s ease infinite; }
.trp-status--ok { background: rgba(15,107,112,.12); color: var(--teal-deep); }
.trp-status--err { background: rgba(196,74,58,.12); color: #A03A2C; }
@keyframes trp-pulse { 50% { opacity: .35; } }

.trp-error { background: rgba(196,74,58,.08); border: 1px solid rgba(196,74,58,.3); color: #A03A2C; border-radius: 14px; padding: 16px 18px; }

/* responsive */
@media (max-width: 980px) {
  .trp-frame { grid-template-columns: 1fr; }
  .trp-nav { position: static; flex-direction: row; }
  .trp-tab { border-left: 0; border-bottom: 3px solid transparent; border-radius: 8px 8px 0 0; }
  .trp-tab.is-active { border-bottom-color: var(--sun); }
  .trp-side { position: static; order: -1; }
}
`;
