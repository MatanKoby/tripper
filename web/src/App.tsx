const sections = [
  { id: "flights", label: "Flights" },
  { id: "accommodation", label: "Accommodation" },
  { id: "activities", label: "Activities" },
];

export default function App() {
  return (
    <div className="layout">
      <nav className="left">
        <h1>Tripper</h1>
        <ul>
          {sections.map((s) => (
            <li key={s.id}>
              <a href={`#${s.id}`}>{s.label}</a>
            </li>
          ))}
        </ul>
      </nav>

      <main className="center">
        {sections.map((s) => (
          <section key={s.id} id={s.id} className="section">
            <h2>{s.label}</h2>
            <p className="placeholder">Coming soon.</p>
          </section>
        ))}
      </main>

      <aside className="right">
        <h2>Plan a trip</h2>
        <p className="placeholder">Trip input form and job status go here.</p>
      </aside>
    </div>
  );
}
