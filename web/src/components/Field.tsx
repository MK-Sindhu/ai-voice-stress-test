// The atmosphere behind the hero and the closing panel: a grainy dusk
// gradient crossed by two sets of rings, one spreading from the caller's
// corner and one from the agent's. Where they cross is where calls go wrong.
const RINGS = Array.from({ length: 16 }, (_, i) => 60 + i * 58);

export function Field({ quiet = false }: { quiet?: boolean }) {
  return (
    <div className={`field${quiet ? " field-quiet" : ""}`} aria-hidden="true">
      <div className="glow glow-a" />
      <div className="glow glow-b" />
      <div className="glow glow-c" />
      <svg className="rings" viewBox="0 0 1200 760" preserveAspectRatio="xMidYMid slice">
        <defs>
          <filter id="wobble" x="-20%" y="-20%" width="140%" height="140%">
            <feTurbulence type="fractalNoise" baseFrequency="0.006" numOctaves="2" seed="4" result="n" />
            <feDisplacementMap in="SourceGraphic" in2="n" scale="46" />
          </filter>
        </defs>
        <g filter="url(#wobble)" fill="none" strokeWidth="1">
          <g className="ring-set ring-caller">
            {RINGS.map((r) => <circle key={r} cx="150" cy="110" r={r} />)}
          </g>
          <g className="ring-set ring-agent">
            {RINGS.map((r) => <circle key={r} cx="1060" cy="660" r={r} />)}
          </g>
        </g>
      </svg>
      <div className="grain" />
    </div>
  );
}
