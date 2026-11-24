"use client";

// The list of recorded failures, one agent at a time, optionally one kind of scenario.
import { useEffect, useMemo, useState } from "react";
import type { Agent, Failure } from "@/lib/arena";
import { CallPlayer, Legend } from "./CallPlayer";

const STEP = 6;

export function Failures({ failures, agents, families }: {
  failures: Failure[]; agents: Agent[]; families: { key: string; name: string }[];
}) {
  const [agent, setAgent] = useState(agents[0]?.id ?? "");
  const [family, setFamily] = useState("all");
  const [limit, setLimit] = useState(STEP);

  // A link from the results table (#agent--scenario) opens that call.
  useEffect(() => {
    const open = () => {
      const id = decodeURIComponent(window.location.hash.slice(1));
      const target = failures.find((f) => f.id === id);
      if (!target) return;
      setAgent(target.agent); setFamily("all"); setLimit(failures.length);
      requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ block: "start" }));
    };
    open();
    window.addEventListener("hashchange", open);
    return () => window.removeEventListener("hashchange", open);
  }, [failures]);

  const ofAgent = useMemo(() => failures.filter((f) => f.agent === agent), [failures, agent]);
  const present = families.filter((f) => ofAgent.some((x) => x.family === f.key));
  const shown = ofAgent.filter((f) => family === "all" || f.family === family);
  const pick = (set: () => void) => { set(); setLimit(STEP); };

  if (!failures.length) return <p className="lead">Nothing to show: every scenario was passed.</p>;
  return (
    <div>
      <div className="filters" role="group" aria-label="Agent">
        <span className="filter-name">Agent</span>
        {agents.map((a) => (
          <button key={a.id} type="button" className="chip" aria-pressed={a.id === agent}
                  onClick={() => pick(() => { setAgent(a.id); setFamily("all"); })}>{a.label}</button>
        ))}
      </div>
      <div className="filters" role="group" aria-label="Scenario">
        <span className="filter-name">Scenario</span>
        <button type="button" className="chip" aria-pressed={family === "all"} onClick={() => pick(() => setFamily("all"))}>All kinds</button>
        {present.map((f) => (
          <button key={f.key} type="button" className="chip" aria-pressed={f.key === family}
                  onClick={() => pick(() => setFamily(f.key))}>{f.name}</button>
        ))}
      </div>
      <Legend />
      <p className="showing" aria-live="polite">
        Showing {Math.min(limit, shown.length)} of {shown.length} failures for this agent · {failures.length} recorded in all
      </p>
      <div className="cards">
        {shown.slice(0, limit).map((f) => <FailureCard key={f.id} call={f} families={families} />)}
      </div>
      {shown.length > limit && (
        <button type="button" className="btn btn-glass more" onClick={() => setLimit(limit + STEP)}>
          Show {Math.min(STEP, shown.length - limit)} more
        </button>
      )}
    </div>
  );
}

export function FailureCard({ call, families }: { call: Failure; families: { key: string; name: string }[] }) {
  const family = families.find((f) => f.key === call.family)?.name ?? call.family;
  return (
    <article className="card" id={call.id}>
      <header>
        <p className="meta">
          {family} · {call.language}
          {call.passes > 1 && ` · pass ${call.passShown} shown · not passed in ${call.notPassed} of ${call.passes} passes`}
        </p>
        <h3>{call.title} <span className={`badge badge-${call.status}`}>{call.status === "untestable" ? "untestable" : "failed"}</span></h3>
        <p className="desc">{call.description}</p>
        <p className="why"><strong>What went wrong</strong>{call.reasons.join("; ")}</p>
      </header>
      <CallPlayer call={call} />
      <details>
        <summary>Transcript</summary>
        <div className="script">
          <div>
            <p className="script-name">What the caller said</p>
            <ol>{call.callerLines.map((l, i) => (
              <li key={i}>{l.text}{l.kind !== "turn" && <em> ({l.kind.replace("_", " ")})</em>}</li>
            ))}</ol>
          </div>
          {call.agentLines.length > 0 && (
            <div>
              <p className="script-name">What the agent said, as transcribed</p>
              <ol>{call.agentLines.map((l, i) => <li key={i}>{l}</li>)}</ol>
            </div>
          )}
        </div>
      </details>
    </article>
  );
}
