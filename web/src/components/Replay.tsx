"use client";

// The card in the middle of the landing page. It replays one real recorded
// call: the waveform fills in, the caller's words appear as they are spoken,
// and a flag comes up at the moment the agent goes wrong. It runs silently on
// a loop; the round button plays the actual recording.
import { useEffect, useRef, useState } from "react";
import type { Failure } from "@/lib/arena";
import { clock } from "@/lib/timeline";
import { PlayIcon } from "./CallPlayer";
import { Wave } from "./Wave";

const FLAG_SECONDS = 3.2;

export function Replay({ call, agentLabel }: { call: Failure; agentLabel: string }) {
  const duration = Math.max(call.duration, 1);
  const firstMark = call.marks[0]?.t ?? duration / 2;
  const [t, setT] = useState(0);
  const [sound, setSound] = useState(false);
  const audio = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    if (sound) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      // No loop: hold on the moment it went wrong.
      const hold = requestAnimationFrame(() => setT(firstMark + 0.4));
      return () => cancelAnimationFrame(hold);
    }
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
  }, [sound, duration, firstMark]);

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

  // The caller's current line, revealed word by word as it is spoken.
  const line = [...call.spans].reverse().find((s) => s.lane === 0 && s.kind !== "gap" && t >= s.start);
  const pausing = call.spans.some((s) => s.kind === "gap" && t >= s.start && t <= s.end);
  const agentTalking = call.spans.some((s) => s.lane === 1 && t >= s.start && t <= s.end);
  let said = "", coming = "";
  if (line) {
    const share = Math.min(1, (t - line.start) / Math.max(line.end - line.start, 0.2));
    const cut = Math.round(line.title.length * share);
    said = line.title.slice(0, cut);
    coming = line.title.slice(cut, cut + 5);
  }
  const flag = call.marks.find((m) => t >= m.t && t <= m.t + FLAG_SECONDS);

  return (
    <div className="replay">
      <div className="replay-top">
        <p className="replay-kicker">Replay of a real call<span>{clock(t)} / {clock(duration)}</span></p>
        <p className="replay-title">{call.title}</p>
        <p className="replay-meta">{agentLabel} · {call.language}</p>
      </div>
      <Wave call={call} at={t} big onSeek={sound ? (s) => { if (audio.current) audio.current.currentTime = s; } : undefined} />
      <p className="replay-line" aria-hidden="true">
        {line ? <>{said}<span>{coming}</span></> : <em>The line is quiet</em>}
      </p>
      <p className="replay-status" aria-hidden="true">
        <span className={`who who-caller${pausing ? " is-on" : ""}`}>{pausing ? "Caller is pausing mid-sentence" : "Caller"}</span>
        <span className={`who who-agent${agentTalking ? " is-on" : ""}`}>{agentTalking ? "Agent is talking" : "Agent"}</span>
      </p>
      <div className="replay-mic">
        <button type="button" className="mic" onClick={toggleSound} aria-pressed={sound}
                aria-label={sound ? "Stop the recording" : "Play the recording with sound"}>
          <PlayIcon playing={sound} />
        </button>
      </div>
      <p className={`flag${flag ? " is-up" : ""}`} role="status">{flag ? flag.label : call.reasons[0]}</p>
    </div>
  );
}
