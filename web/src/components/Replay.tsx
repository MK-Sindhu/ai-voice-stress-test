"use client";

// The screen at the top of the home page. It replays one real recorded call
// the way a match is replayed on television: a running clock, the two
// speakers in two lanes, the caller's words as captions, and a flag that
// comes up at the moment the agent goes wrong. It runs silently on a loop;
// "Play with sound" switches to the actual recording.
import { useEffect, useRef, useState } from "react";
import type { Failure } from "@/lib/arena";
import { L, LANE, W, scale, ticks } from "@/lib/timeline";

const FLAG_SECONDS = 3.2;

export function Replay({ call, agentLabel }: { call: Failure; agentLabel: string }) {
  const duration = Math.max(call.duration, 1);
  const x = scale(duration);
  const firstMark = call.marks[0]?.t ?? duration / 2;
  const [t, setT] = useState(firstMark + 0.4);   // what a visitor without motion sees: the moment it went wrong
  const [sound, setSound] = useState(false);
  const audio = useRef<HTMLAudioElement | null>(null);

  // The silent loop, a little faster than real time.
  useEffect(() => {
    if (sound || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let frame = 0, last = performance.now(), at = 0;
    const step = (now: number) => {
      at += ((now - last) / 1000) * 1.2;
      last = now;
      if (at > duration + 1.6) at = 0;
      setT(Math.min(at, duration));
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [sound, duration]);

  // With sound, the clock follows the recording.
  useEffect(() => {
    if (!sound) return;
    const el = audio.current;
    if (!el) return;
    let frame = 0;
    const step = () => { setT(el.currentTime); frame = requestAnimationFrame(step); };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [sound]);
  useEffect(() => () => audio.current?.pause(), []);

  const toggleSound = () => {
    if (!call.audio) return;
    if (!audio.current) {
      audio.current = new Audio(`/audio/${call.audio}`);
      audio.current.addEventListener("ended", () => setSound(false));
    }
    const el = audio.current;
    if (sound) { el.pause(); setSound(false); } else { el.currentTime = 0; void el.play(); setSound(true); }
  };
  const seek = (event: React.MouseEvent<SVGSVGElement>) => {
    const el = audio.current;
    if (!sound || !el) return;
    const box = event.currentTarget.getBoundingClientRect();
    el.currentTime = Math.max(0, Math.min(1, (((event.clientX - box.left) / box.width) * W - L) / LANE)) * duration;
  };

  const speaking = (lane: number) => call.spans.find((s) => s.lane === lane && s.kind !== "gap" && t >= s.start && t <= s.end);
  const callerNow = speaking(0);
  const lastCaller = [...call.spans].reverse().find((s) => s.lane === 0 && s.kind !== "gap" && t >= s.start);
  const waiting = call.spans.find((s) => s.kind === "gap" && t >= s.start && t <= s.end);
  const agentNow = speaking(1);
  const flag = call.marks.find((m) => t >= m.t && t <= m.t + FLAG_SECONDS);
  const tenths = Math.floor((t % 1) * 10);

  return (
    <div className={`replay${flag ? " replay-flagged" : ""}`}>
      <div className="replay-bar">
        <span className="bug">Replay</span>
        <span className="replay-title">{call.title}</span>
        <span className="replay-meta">{agentLabel} · {call.language}</span>
        <span className="replay-clock" aria-hidden="true">
          {String(Math.floor(t / 60)).padStart(2, "0")}:{String(Math.floor(t % 60)).padStart(2, "0")}.{tenths}
        </span>
      </div>

      <div className="replay-captions" aria-hidden="true">
        <p className={`caption caption-caller${callerNow ? " is-live" : ""}`}>
          <span>Caller</span>
          {waiting ? <em>… pauses mid-sentence</em> : lastCaller ? `“${lastCaller.title}”` : <em>line is quiet</em>}
        </p>
        <p className={`caption caption-agent${agentNow ? " is-live" : ""}`}>
          <span>Agent</span>
          {agentNow ? <><i className="level" /><i className="level" /><i className="level" /><i className="level" /> speaking</> : <em>silent</em>}
        </p>
      </div>

      <div className="lanes">
        <svg viewBox={`0 0 ${W} 112`} role="img" onClick={seek}
             aria-label={`Timeline of a recorded call. ${call.reasons.join("; ")}.`}>
          <defs><clipPath id="played"><rect x="0" y="0" width={x(t)} height="112" /></clipPath></defs>
          <text className="t-label" x="0" y="34">CALLER</text>
          <text className="t-label" x="0" y="72">AGENT</text>
          <rect className="t-track" x={L} y="16" width={LANE} height="26" />
          <rect className="t-track" x={L} y="54" width={LANE} height="26" />
          {ticks(duration).map((s) => (
            <g key={s}><line className="t-axis" x1={x(s)} y1="86" x2={x(s)} y2="91" /><text className="t-tick" x={x(s)} y="106">{s} s</text></g>
          ))}
          {[false, true].map((played) => (
            <g key={String(played)} className={played ? "t-played" : "t-ahead"} clipPath={played ? "url(#played)" : undefined}>
              {call.spans.map((s, i) => (
                <rect key={i} className={`t-span t-${s.lane === 1 ? "agent" : s.kind}`} x={x(s.start)} y={s.lane === 1 ? 54 : 16}
                      width={Math.max(x(s.end) - x(s.start), 3)} height="26" />
              ))}
            </g>
          ))}
          {call.marks.filter((m) => t >= m.t).map((m, i) => <line key={i} className="t-foul" x1={x(m.t)} y1="8" x2={x(m.t)} y2="88" />)}
          <line className="t-head" x1={x(t)} y1="6" x2={x(t)} y2="90" />
        </svg>
      </div>

      <div className="replay-foot">
        <button type="button" className="btn btn-on-dark" onClick={toggleSound} aria-pressed={sound}>
          {sound ? "Stop sound" : "Play with sound"}
        </button>
        <p className={`flag${flag ? " is-up" : ""}`} role="status">
          <b>Flag</b>{flag ? flag.label : call.reasons[0]}
        </p>
      </div>
    </div>
  );
}
