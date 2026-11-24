"use client";

// One recorded call as a waveform with a play button.
import { useEffect, useRef, useState } from "react";
import type { Failure } from "@/lib/arena";
import { clock } from "@/lib/timeline";
import { Wave } from "./Wave";

let current: HTMLAudioElement | null = null;   // only one recording plays at a time

export function PlayIcon({ playing }: { playing: boolean }) {
  return playing
    ? <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 2.5h3v11h-3zM9.5 2.5h3v11h-3z" /></svg>
    : <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 2.5v11l9-5.5z" /></svg>;
}

export function CallPlayer({ call }: { call: Failure }) {
  const duration = Math.max(call.duration, 1);
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
  const seek = (seconds: number) => {
    const el = load();
    if (!el) return;
    el.currentTime = seconds;
    setAt(seconds);
    play();
  };

  return (
    <div className={`call${playing ? " is-playing" : ""}`}>
      <div className="wave-scroll"><Wave call={call} at={at} onSeek={call.audio ? seek : undefined} /></div>
      {call.audio && (
        <div className="transport">
          <button type="button" className="play" onClick={toggle} aria-label={playing ? "Pause recording" : "Play recording"}>
            <PlayIcon playing={playing} />
          </button>
          <span className="time">{clock(at ?? 0)} / {clock(duration)}</span>
          <span className="hint">Stereo: caller in the left ear, agent in the right. Click the waveform to jump.</span>
        </div>
      )}
    </div>
  );
}
