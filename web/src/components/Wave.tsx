// A call drawn as one waveform: the caller's voice rises above the centre
// line, the agent's hangs below it. Where both have bars in the same column,
// they were talking at the same time.
import type { Failure } from "@/lib/arena";

// Rounded so the server and the browser print exactly the same numbers.
const r = (n: number) => Math.round(n * 100) / 100;

// The recordings are not analysed in the browser, so bar heights are a fixed
// pattern; what is real is *when* each side was making sound.
const height = (i: number, salt: number) => {
  const v = Math.sin(i * 12.9898 + salt * 78.233) * 43758.5453;
  return 0.3 + 0.7 * (v - Math.floor(v));
};

export function Wave({ call, at, big = false, onSeek }: {
  call: Failure; at: number | null; big?: boolean; onSeek?: (seconds: number) => void;
}) {
  const duration = Math.max(call.duration, 1);
  // The landing-page card is narrow, so it gets fewer, fatter bars.
  const WAVE_W = big ? 520 : 1000, BINS = big ? 58 : 132;
  const H = big ? 170 : 132, mid = H / 2, reach = mid - 20;
  const slot = WAVE_W / BINS, bar = r(slot * 0.46);
  const x = (t: number) => r((Math.min(Math.max(t, 0), duration) / duration) * WAVE_W);
  const active = (lane: number, t: number) => call.spans.find((s) => s.lane === lane && t >= s.start && t <= s.end);
  const step = duration <= 60 ? 5 : 10;
  const labelled: number[] = [];

  return (
    <svg className={`wave${onSeek ? " seekable" : ""}`} viewBox={`0 0 ${WAVE_W} ${H + 22}`} role="img"
         aria-label={`Waveform of the call. ${call.reasons.join("; ")}.`}
         onClick={onSeek && ((e) => {
           const box = e.currentTarget.getBoundingClientRect();
           onSeek(Math.max(0, Math.min(1, (e.clientX - box.left) / box.width)) * duration);
         })}>
      <line className="w-mid" x1="0" y1={mid} x2={WAVE_W} y2={mid} />
      {Array.from({ length: BINS }, (_, i) => {
        const t = ((i + 0.5) / BINS) * duration;
        const caller = active(0, t), agent = active(1, t);
        const played = at === null || t <= at;
        const cx = r(i * slot + (slot - bar) / 2);
        const up = caller && caller.kind !== "gap" ? r(height(i, 1) * reach) : 0;
        const down = agent ? r(height(i, 2) * reach) : 0;
        return (
          <g key={i} className={played ? undefined : "w-ahead"}>
            {up > 0
              ? <rect className={`w-caller${caller!.kind === "turn" ? "" : " w-cut"}`} x={cx} y={r(mid - 3 - up)} width={bar} height={up} rx={r(bar / 2)} />
              : <circle className={caller ? "w-pause" : "w-rest"} cx={r(cx + bar / 2)} cy={mid - 7} r={big ? 1.4 : 1.6} />}
            {down > 0
              ? <rect className="w-agent" x={cx} y={mid + 3} width={bar} height={down} rx={r(bar / 2)} />
              : <circle className="w-rest" cx={r(cx + bar / 2)} cy={mid + 7} r={big ? 1.4 : 1.6} />}
          </g>
        );
      })}
      {call.marks.map((m, i) => {
        const repeat = labelled.some((px) => x(m.t) - px < WAVE_W * 0.23);
        if (!repeat) labelled.push(x(m.t));
        const end = x(m.t) > WAVE_W * 0.6;
        return (
          <g key={i} className="w-mark">
            <line x1={x(m.t)} y1="14" x2={x(m.t)} y2={H - 6} />
            {!repeat && <text x={x(m.t) + (end ? -8 : 8)} y="13" textAnchor={end ? "end" : "start"}>{m.label}</text>}
          </g>
        );
      })}
      {at !== null && <line className="w-head" x1={x(at)} y1="6" x2={x(at)} y2={H - 2} />}
      {Array.from({ length: Math.floor(duration / step) + 1 }, (_, i) => i * step).map((s) => (
        <text key={s} className="w-tick" x={Math.min(Math.max(x(s), 10), WAVE_W - 14)} y={H + 16}>{s}s</text>
      ))}
    </svg>
  );
}

export function WaveKey() {
  return (
    <ul className="legend">
      <li><i className="k-caller" />caller speaking (above the line)</li>
      <li><i className="k-cut" />caller interrupting or saying a filler word</li>
      <li><i className="k-agent" />agent speaking (below the line)</li>
      <li><i className="k-mark" />where it went wrong</li>
    </ul>
  );
}
