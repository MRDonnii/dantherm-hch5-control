import { Flame, Gauge, Leaf, Wind } from "lucide-react";

export function OverviewPage() {
  return (
    <section className="page-view page-enter">
      <header className="page-hero overview-hero">
        <div>
          <span className="eyebrow">OVERBLIK</span>
          <h1>Ventilation, samlet ét sted</h1>
          <p>Rolig daglig styring øverst. Teknisk dybde findes længere nede — uden at blande de to oplevelser sammen.</p>
        </div>
        <div className="hero-status-grid">
          <div><span>Master</span><strong>Raspberry Pi</strong></div>
          <div><span>Bus</span><strong className="ok-text">Sund</strong></div>
          <div><span>Mode</span><strong>Smart Auto</strong></div>
        </div>
      </header>

      <div className="overview-grid-v2">
        <article className="surface airflow-card-v2">
          <div className="section-head">
            <div><span className="eyebrow">LUFTSTRØM</span><h2>HCH5 varmegenvinding</h2></div>
            <span className="status-chip"><span className="live-dot" /> Normal drift</span>
          </div>

          <div className="airflow-stage" aria-label="Animeret ventilationsoverblik">
            <svg viewBox="0 0 980 420" role="img">
              <defs>
                <linearGradient id="supplyGradient" x1="0" x2="1"><stop offset="0" stopColor="#67b6ef"/><stop offset="1" stopColor="#57c79d"/></linearGradient>
                <linearGradient id="extractGradient" x1="0" x2="1"><stop offset="0" stopColor="#efa75f"/><stop offset="1" stopColor="#7f94a3"/></linearGradient>
                <filter id="flowGlow"><feGaussianBlur stdDeviation="3" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
              </defs>
              <rect className="unit-shell" x="302" y="74" width="376" height="272" rx="34" />
              <text className="unit-title" x="490" y="104" textAnchor="middle">HCH5</text>

              <path className="duct-bg" d="M40 280 H330 L435 185" />
              <path className="duct-bg" d="M540 235 L650 138 H940" />
              <path className="duct-bg" d="M940 138 H650 L540 235" />
              <path className="duct-bg" d="M435 185 L330 280 H40" />

              <path className="flow-line supply-line" d="M40 280 H330 L435 185" pathLength="100" />
              <path className="flow-line supply-line" d="M540 235 L650 138 H940" pathLength="100" />
              <path className="flow-line extract-line" d="M940 138 H650 L540 235" pathLength="100" />
              <path className="flow-line extract-line" d="M435 185 L330 280 H40" pathLength="100" />

              <g className="exchanger" transform="translate(488 211) rotate(45)">
                <rect x="-72" y="-72" width="144" height="144" rx="25" />
                <path d="M-48 -31 H48 M-48 -10 H48 M-48 11 H48 M-48 32 H48" />
              </g>

              <g className="fan-v2 fan-left" transform="translate(210 280)"><circle r="31"/><path d="M0-20c17 0 22 12 11 20C4 5-2 0 0-20Zm18 11c8 15-1 25-14 20-8-3-4-10 14-20Zm-18 18c-16 2-23-10-13-20 7-7 12-1 13 20Z" /></g>
              <g className="fan-v2 fan-right" transform="translate(770 138)"><circle r="31"/><path d="M0-20c17 0 22 12 11 20C4 5-2 0 0-20Zm18 11c8 15-1 25-14 20-8-3-4-10 14-20Zm-18 18c-16 2-23-10-13-20 7-7 12-1 13 20Z" /></g>

              <g className="air-label"><text x="40" y="236">UDELUFT</text><text className="temp" x="40" y="260">8,4°</text></g>
              <g className="air-label"><text x="940" y="96" textAnchor="end">UDSUGNING</text><text className="temp" x="940" y="120" textAnchor="end">22,1°</text></g>
              <g className="air-label"><text x="40" y="330">AFKAST</text><text className="temp" x="40" y="354">11,0°</text></g>
              <g className="air-label"><text x="940" y="188" textAnchor="end">INDBLÆSNING</text><text className="temp" x="940" y="212" textAnchor="end">19,7°</text></g>
              <text className="recovery-label" x="488" y="207" textAnchor="middle">82%</text>
              <text className="recovery-sub" x="488" y="226" textAnchor="middle">GENVINDING</text>
            </svg>
          </div>

          <div className="airflow-footer">
            <span><i className="legend-dot supply" /> Indblæsning 1.340 RPM</span>
            <span><i className="legend-dot extract" /> Udsugning 1.420 RPM</span>
            <span><i className="legend-dot neutral" /> Bypass faktisk lukket</span>
          </div>
        </article>

        <aside className="control-column">
          <article className="surface control-card-v2">
            <div className="section-head compact"><div><span className="eyebrow">DAGLIG STYRING</span><h2>Ventilation</h2></div><Gauge size={21} /></div>
            <div className="segmented-v2"><button className="active">Local Auto</button><button>Smart Auto</button><button>Manuel</button></div>
            <div className="level-row"><span>Niveau</span><div>{[1,2,3,4,5,6].map(level => <button key={level} className={level===3?"active":""}>{level}</button>)}</div></div>
            <div className="control-summary"><span>Aktiv beslutning</span><strong>Normal ventilation · trin 3</strong><small>CO₂, fugt og rumtemperatur er inden for målområdet.</small></div>
          </article>

          <article className="surface quick-card">
            <div className="quick-icon"><Wind size={20}/></div><div><span>Quick Boost</span><strong>15 · 30 · 60 min</strong></div><button>Start</button>
          </article>
          <article className="surface quick-card">
            <div className="quick-icon warm"><Flame size={20}/></div><div><span>Eftervarme</span><strong>20° setpunkt</strong></div><button>Juster</button>
          </article>
          <article className="surface quick-card">
            <div className="quick-icon green"><Leaf size={20}/></div><div><span>Frikøling</span><strong>Standby</strong></div><button>Detaljer</button>
          </article>
        </aside>
      </div>

      <div className="metrics-row-v2">
        <article className="surface metric-v2"><span>CO₂</span><strong>742 <small>ppm</small></strong><em className="good-pill">God</em></article>
        <article className="surface metric-v2"><span>Luftfugtighed</span><strong>41 <small>%</small></strong><em>Stabil</em></article>
        <article className="surface metric-v2"><span>Filter</span><strong>78 <small>%</small></strong><div className="mini-meter"><i style={{width:"78%"}}/></div></article>
        <article className="surface metric-v2"><span>Eftervarme</span><strong>Aktiv</strong><em>19,8° efter flade</em></article>
      </div>
    </section>
  );
}
