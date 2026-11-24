import Link from "next/link";
import { Standings } from "@/components/Board";
import { Replay } from "@/components/Replay";
import { arena } from "@/lib/arena";

// The measurements shown as sliders on the "best agent" card.
const SLIDERS = [
  { key: "task_completion", label: "Scenarios passed" },
  { key: "barge_in_stopped", label: "Stopped when interrupted" },
  { key: "detail_accuracy", label: "Details read back right" },
  { key: "backchannel_ignored", label: "Kept talking through “hmm”" },
];
const SHORT: Record<string, string> = {
  mid_thought_pause: "Pause", barge_in: "Barge-in", backchannel: "“Hmm”", numbers_details: "Numbers",
  background_noise: "Noise", change_of_mind: "Change", long_silence: "Silence",
};

export default function Home() {
  const { facts, families, agents, failures, proof } = arena;
  const hero = failures.find((f) => f.id === arena.hero) ?? failures[0];
  const heroAgent = agents.find((a) => a.id === hero?.agent);
  const best = agents[0];
  const top = Math.max(...families.map((f) => (f.calls ? f.passed / f.calls : 0)));

  return (
    <>
      <section className="hero wrap">
        <p className="pill">Voice agent benchmark · Hindi · Hinglish · Indian English</p>
        <h1>Meet the caller <span>from hell</span></h1>
        <p className="hero-sub">
          It phones your voice agent and behaves like a difficult customer: pauses mid-sentence, interrupts, mumbles
          “hmm”, reads numbers over street noise. Every call is recorded, so you can hear where the agent slipped.
        </p>
        <div className="actions">
          <Link className="btn" href="/leaderboard">See the leaderboard</Link>
          <Link className="btn btn-soft" href="/failures">Hear the failures</Link>
        </div>

        <div className="trio">
          {best && (
            <article className="soft-card side-card">
              <p className="card-kicker">Best agent so far</p>
              <h2>{best.label}</h2>
              <ul className="sliders">
                {SLIDERS.map((s) => {
                  const m = best.metrics[s.key];
                  return (
                    <li key={s.key}>
                      <p><span>{s.label}</span><b>{m.value}</b></p>
                      <span className="slider"><i style={{ width: `${(m.share ?? 0) * 100}%` }} /></span>
                    </li>
                  );
                })}
              </ul>
              <Link className="card-link" href="/leaderboard">Full leaderboard</Link>
            </article>
          )}

          {hero && <Replay call={hero} agentLabel={heroAgent?.label ?? hero.agent} />}

          <article className="soft-card side-card">
            <p className="card-kicker">Calls passed, by kind of trouble</p>
            <h2>All agents together</h2>
            <ul className="bars" aria-label="Share of calls passed for each kind of scenario">
              {families.map((f) => {
                const share = f.calls ? f.passed / f.calls : 0;
                return (
                  <li key={f.key} className={share === top ? "is-top" : undefined}>
                    <span className="bar-value">{f.passed}/{f.calls}</span>
                    <span className="bar"><i style={{ height: `${Math.max(share * 100, 4)}%` }} /></span>
                    <span className="bar-name">{SHORT[f.key] ?? f.name}</span>
                  </li>
                );
              })}
            </ul>
            <Link className="card-link" href="/scenarios">All {facts.scenarios} scenarios</Link>
          </article>
        </div>

        <ul className="facts">
          <li><b>{facts.scenarios}</b> scripted scenarios</li>
          <li><b>{facts.languages}</b> languages</li>
          <li><b>{facts.calls}</b> recorded calls</li>
          <li><b>{facts.failures}</b> failures you can play</li>
        </ul>
      </section>

      <section className="wrap block">
        <div className="block-head">
          <div>
            <p className="tag">Leaderboard</p>
            <h2>Standings</h2>
          </div>
          <Link className="card-link" href="/leaderboard">Every measurement</Link>
        </div>
        <Standings agents={agents} />
        <p className="notice">
          Every entry so far is a baseline agent built from open models and run on one laptop. No commercial platform
          has been tested yet.
        </p>
      </section>

      <section className="wrap block">
        <div className="block-head">
          <div>
            <p className="tag">Method</p>
            <h2>The measuring was tested first</h2>
          </div>
          <Link className="card-link" href="/method">How it is checked</Link>
        </div>
        <dl className="proof-strip">
          {proof.map((p) => (<div key={p.title} className="soft-card"><dd>{p.figure}</dd><dt>{p.title}</dt></div>))}
        </dl>
      </section>

      <section className="wrap">
        <div className="closing">
          <div>
            <p className="pill pill-on-blue">Not open yet</p>
            <h2>Testing your own agent</h2>
            <p>
              The same caller will be able to phone an agent on ElevenLabs, Vapi, Retell or smallest.ai and produce a
              scorecard like these, with a recording of every failure.
            </p>
          </div>
          {arena.site.contact_email
            ? <a className="btn btn-white" href={`mailto:${arena.site.contact_email}`}>Ask about testing your agent</a>
            : <Link className="btn btn-white" href="/method">Read how it works</Link>}
        </div>
      </section>
    </>
  );
}
