export function PlaceholderPage({ eyebrow, title, description }: { eyebrow: string; title: string; description: string }) {
  return (
    <section className="page-view page-enter">
      <header className="page-hero">
        <div>
          <span className="eyebrow">{eyebrow}</span>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
        <span className="status-chip muted">V2 FOUNDATION</span>
      </header>
      <div className="surface placeholder-surface">
        <div className="placeholder-glow" />
        <strong>Ny visning under opbygning</strong>
        <p>Denne side bliver bygget som en selvstændig modulvisning i den nye shell — uden legacy navigation, iframe eller duplicate event handlers.</p>
      </div>
    </section>
  );
}
