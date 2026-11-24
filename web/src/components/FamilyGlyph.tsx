// A small drawing of what the caller does in each kind of scenario, in the
// same two lanes as the recorded calls: caller on top, agent below.
type Bar = [cls: string, x: number, w: number, lane: 0 | 1];

const GLYPHS: Record<string, { bars: Bar[]; mark?: number; noise?: boolean }> = {
  mid_thought_pause: { bars: [["caller", 0, 62, 0], ["gap", 66, 50, 0], ["caller", 120, 50, 0], ["agent", 92, 108, 1]], mark: 92 },
  barge_in: { bars: [["caller", 0, 44, 0], ["agent", 54, 146, 1], ["caller", 104, 70, 0]], mark: 104 },
  backchannel: { bars: [["caller", 0, 44, 0], ["agent", 54, 62, 1], ["caller", 100, 12, 0]], mark: 116 },
  numbers_details: { bars: [...[0, 16, 32, 48, 64, 80].map((x): Bar => ["caller", x, 13, 0]), ["agent", 108, 92, 1]] },
  background_noise: { bars: [["caller", 64, 78, 0], ["agent", 152, 48, 1]], noise: true },
  change_of_mind: { bars: [["old", 0, 52, 0], ["caller", 58, 58, 0], ["agent", 126, 74, 1]] },
  long_silence: { bars: [["caller", 0, 30, 0], ["agent", 36, 26, 1], ["gap", 34, 122, 0], ["agent", 104, 14, 1], ["caller", 160, 40, 0]] },
};

export function FamilyGlyph({ family }: { family: string }) {
  const glyph = GLYPHS[family];
  if (!glyph) return null;
  return (
    <svg className="glyph" viewBox="0 0 200 44" aria-hidden="true">
      <rect className="g-track" x="0" y="4" width="200" height="14" rx="7" />
      <rect className="g-track" x="0" y="26" width="200" height="14" rx="7" />
      {glyph.noise && Array.from({ length: 40 }, (_, i) => 3 + i * 5).map((x) => (
        <line key={x} className="g-noise" x1={x} y1={7 + ((x * 7) % 5)} x2={x} y2={15 - ((x * 3) % 4)} />
      ))}
      {glyph.bars.map(([cls, x, w, lane], i) => (
        <rect key={i} className={`g-${cls}`} x={x} y={lane === 0 ? 4 : 26} width={w} height="14" rx="7" />
      ))}
      {glyph.mark !== undefined && <line className="g-mark" x1={glyph.mark} y1="0" x2={glyph.mark} y2="44" />}
    </svg>
  );
}
