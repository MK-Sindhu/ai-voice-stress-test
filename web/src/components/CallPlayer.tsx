"use client";

// One recorded call, drawn as two lanes (caller above, agent below) with a
// play button. A line moves across the drawing as the recording plays.
import { useEffect, useRef, useState } from "react";
import type { Failure } from "@/lib/arena";
import { L, LANE, W, clock, scale, ticks as tickMarks } from "@/lib/timeline";

let current: HTMLAudioElement | null = null;   // only one recording plays at a time

export function CallPlayer({ call }: { call: Failure }) {
  const duration = Math.max(call.duration, 1);
  const x = scale(duration);
  const audio = useRef<HTMLAudioElement | null>(null);
  const frame = useRef(0);
  const [playing, setPlaying] = useState(false);
  const [at, setAt] = useState<number | null>(null);

  useEffect(() => () => { cancelAnimationFrame(frame.current); audio.current?.pause(); }, []);

  const load = () => {
    if (audio.current || !call.audio) return audio.current;
    const el = new Audio(`/audio/${call.audio}`);
    const tick = () => { setAt(el.currentTime); if (!el.paused) frame.current = requestAnimationFrame(tick); };
    el.addEventListener("play", () => { setPlaying(true); tick(); });
    el.addEventListener("pause", () => setPlaying(false));
    el.addEventListener("ended", () => setPlaying(false));
    audio.current = el;
    return el;
  };
  const play = () => {
    const el = load();
    if (!el) return;
    if (current && current !== el) current.pause();
    current = el;
    void el.play();
  };
  const toggle = () => {
    const el = load();
    if (!el) return;
    if (el.paused) play(); else el.pause();
  };
  const seek = (event: React.MouseEvent<SVGSVGElement>) => {
    const el = load();
    if (!el) return;
    const box = event.currentTarget.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * W;
    el.currentTime = Math.max(0, Math.min(1, (px - L) / LANE)) * duration;
    setAt(el.currentTime);
    play();
  };

  const ticks = tickMarks(duration);
  // The same label twice close together is drawn once.
  const labelled: { at: number; label: string }[] = [];
  const marks = call.marks.map((m) => {
    const repeat = labelled.some((o) => o.label === m.label && x(m.t) - o.at < 220);
    if (!repeat) labelled.push({ at: x(m.t), label: m.label });
    return { ...m, repeat };
  });

  return (
    <div className={`call${playing ? " is-playing" : ""}`}>
      <div className="lanes">
        <svg viewBox={`0 0 ${W} 126`} role="img" aria-label="Timeline of the call" onClick={seek}
             className={call.audio ? "seekable" : undefined}>
          <text className="t-label" x="0" y="48">CALLER</text>
          <text className="t-label" x="0" y="86">AGENT</text>
          <rect className="t-track" x={L} y="30" width={LANE} height="26" />
          <rect className="t-track" x={L} y="68" width={LANE} height="26" />
          {ticks.map((t) => (
            <g key={t}>
              <line className="t-axis" x1={x(t)} y1="100" x2={x(t)} y2="105" />
              <text className="t-tick" x={x(t)} y="120">{t} s</text>
            </g>
          ))}
          {call.spans.map((s, i) => (
            <rect key={i} className={`t-span t-${s.lane === 1 ? "agent" : s.kind}`}
                  x={x(s.start)} y={s.lane === 1 ? 68 : 30} width={Math.max(x(s.end) - x(s.start), 3)} height="26">
              <title>{s.title}</title>
            </rect>
          ))}
          {marks.map((m, i) => {
            const end = x(m.t) > W - 230;
            return (
              <g key={i} className="t-mark">
                <line x1={x(m.t)} y1={m.repeat ? 26 : 6} x2={x(m.t)} y2="98" />
                {!m.repeat && <text x={x(m.t) + (end ? -8 : 8)} y="16" textAnchor={end ? "end" : "start"}>{m.label}</text>}
              </g>
            );
          })}
          {at !== null && <line className="t-head" x1={x(Math.min(at, duration))} y1="24" x2={x(Math.min(at, duration))} y2="100" />}
        </svg>
      </div>
      {call.audio && (
        <div className="transport">
          <button type="button" className="play" onClick={toggle} aria-label={playing ? "Pause recording" : "Play recording"}>
            {playing
              ? <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 2.5h3v11h-3zM9.5 2.5h3v11h-3z" /></svg>
              : <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 2.5v11l9-5.5z" /></svg>}
          </button>
          <span className="time">{clock(at ?? 0)} / {clock(duration)}</span>
          <span className="hint">Stereo: caller in the left ear, agent in the right. Click the timeline to jump.</span>
        </div>
      )}
    </div>
  );
}

export function Legend() {
  return (
    <ul className="legend">
      <li><i className="k-caller" />caller speaks</li>
      <li><i className="k-cut" />caller interrupts or says a filler word</li>
      <li><i className="k-gap" />caller pauses or stays silent</li>
      <li><i className="k-agent" />agent makes sound</li>
      <li><i className="k-mark" />where it went wrong</li>
    </ul>
  );
}
