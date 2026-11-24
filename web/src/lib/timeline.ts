// Geometry shared by the drawings of a call. A call is drawn in two lanes on
// a 1000-unit-wide canvas: the caller above, the agent below.
export const W = 1000;
export const L = 74;
export const R = 10;
export const LANE = W - L - R;

export const scale = (duration: number) => (t: number) => L + (Math.min(Math.max(t, 0), duration) / duration) * LANE;
export const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
export const ticks = (duration: number) => {
  const step = duration <= 60 ? 5 : 10;
  return Array.from({ length: Math.floor(duration / step) + 1 }, (_, i) => i * step);
};
