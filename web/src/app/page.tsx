import Link from "next/link";
import { Standings } from "@/components/Board";
import { FamilyGlyph } from "@/components/FamilyGlyph";
import { Replay } from "@/components/Replay";
import { arena } from "@/lib/arena";

export default function Home() {
  const { facts, families, agents, failures, proof } = arena;
  const hero = failures.find((f) => f.id === arena.hero) ?? failures[0];
  const heroAgent = agents.find((a) => a.id === hero?.agent);

  return (
    <>
      <section className="hero">
        <div className="wrap">
          <div className="hero-grid">
            <h1>The caller<br />from <em>hell</em></h1>
            <div className="hero-side">
              <p className="tag">Voice agent benchmark · Hindi · Hinglish · Indian English</p>
              <p className="hero-sub">
                It phones your voice agent and behaves like a difficult customer: pauses mid-sentence, interrupts,
                mumbles “hmm”, reads numbers over street noise, changes its mind. Every call is recorded, so you
                can hear exactly where the agent slipped.
              </p>
              <div className="actions">
                <Link className="btn" href="/leaderboard">See the leaderboard <span aria-hidden="true">→</span></Link>
                <Link className="btn btn-line" href="/failures">Hear the failures</Link>
              </div>
            </div>
          </div>
          {hero && <Replay call={hero} agentLabel={heroAgent?.label ?? hero.agent} />}
          <ul className="facts">
            <li><b>{facts.scenarios}</b>scripted scenarios</li>
            <li><b>{facts.languages}</b>languages</li>
            <li><b>{facts.calls}</b>recorded calls</li>
            <li><b>{facts.failures}</b>failures you can play</li>
          </ul>
        </div>
      </section>

      <section className="wrap block">
        <div className="block-head">
          <div>
            <p className="tag">Leaderboard</p>
            <h2>Standings</h2>
          </div>
          <Link className="more-link" href="/leaderboard">Every measurement <span aria-hidden="true">→</span></Link>
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
            <p className="tag">Scenarios</p>
            <h2>Seven ways it makes trouble</h2>
          </div>
          <Link className="more-link" href="/scenarios">All {facts.scenarios} scenarios <span aria-hidden="true">→</span></Link>
        </div>
        <ul className="moves">
          {families.map((f) => (
            <li key={f.key}>
              <FamilyGlyph family={f.key} />
              <h3>{f.name}</h3>
              <p>{f.calls > 0 ? <><b>{f.passed}</b> of {f.calls} calls passed</> : `${f.scenarios} scenarios`}</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="wrap block">
        <div className="block-head">
          <div>
            <p className="tag">Method</p>
            <h2>The measuring was tested first</h2>
          </div>
          <Link className="more-link" href="/method">How it is checked <span aria-hidden="true">→</span></Link>
        </div>
        <dl className="proof-strip">
          {proof.map((p) => (<div key={p.title}><dd>{p.figure}</dd><dt>{p.title}</dt></div>))}
        </dl>
      </section>

      <section className="wrap">
        <div className="closing">
          <div>
            <p className="tag tag-on-dark">Not open yet</p>
            <h2>Testing your own agent</h2>
          </div>
          <p>
            The same caller will be able to phone an agent on ElevenLabs, Vapi, Retell or smallest.ai and produce a
            scorecard like these, with a recording of every failure.
          </p>
          {arena.site.contact_email
            ? <a className="btn btn-on-dark" href={`mailto:${arena.site.contact_email}`}>Ask about testing your agent</a>
            : <Link className="btn btn-on-dark" href="/method">Read how it works <span aria-hidden="true">→</span></Link>}
        </div>
      </section>
    </>
  );
}
