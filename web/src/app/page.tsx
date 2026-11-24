import Link from "next/link";
import { Leaderboard, Matrix } from "@/components/Board";
import { CallPlayer } from "@/components/CallPlayer";
import { Failures } from "@/components/Failures";
import { FamilyGlyph } from "@/components/FamilyGlyph";
import { Field } from "@/components/Field";
import { Footer, Nav } from "@/components/Nav";
import { arena } from "@/lib/arena";

const LINKS = [
  { href: "#caller", label: "The caller" },
  { href: "#leaderboard", label: "Leaderboard" },
  { href: "#failures", label: "Failures" },
  { href: "#method", label: "Method" },
];

const CAVEATS = [
  "The caller is a synthetic voice, not a person. Real callers vary far more.",
  "The background noise is generated, not recorded.",
  "Content checks rely on a speech recogniser reading the agent's voice, and it makes mistakes.",
  "The baseline agents are slow, so an agent that decides too early often drops its reply before the caller hears it. “Talked over a pause” counts only what a caller would hear.",
];

export default function Home() {
  const { site, facts, families, agents, columns, scenarios, matrix, failures, proof, definitions } = arena;
  const hero = failures.find((f) => f.id === arena.hero) ?? failures[0];
  const heroAgent = agents.find((a) => a.id === hero?.agent);
  const familyNames = families.map(({ key, name }) => ({ key, name }));

  return (
    <>
      <Nav links={LINKS} />
      <main>
        <section className="hero">
          <Field />
          <div className="hero-copy">
            <p className="pill">Voice agent benchmark <span>Hindi · Hinglish · Indian English</span></p>
            <h1>The caller built to break voice agents</h1>
            <p className="hero-sub">
              It phones the agent and behaves like a difficult customer: pauses mid-sentence, interrupts, mumbles
              “hmm”, reads out numbers over street noise, changes its mind. Every call is recorded, so you can
              hear exactly where the agent slipped.
            </p>
            <div className="actions">
              <a className="btn btn-light" href="#leaderboard">See the leaderboard</a>
              <a className="btn btn-glass" href="#failures">Listen to the failures</a>
            </div>
          </div>
          {hero && (
            <div className="glass hero-call" id="listen">
              <p className="eyebrow"><b>A real call from this run</b> · {heroAgent?.label} · {hero.language}</p>
              <p className="hero-call-title">{hero.description}</p>
              <p className="why"><strong>What went wrong</strong>{hero.reasons.join("; ")}</p>
              <CallPlayer call={hero} animate />
            </div>
          )}
        </section>

        <div className="wrap">
          <ul className="facts">
            <li><b>{facts.scenarios}</b> scripted scenarios</li>
            <li><b>{facts.languages}</b> languages</li>
            <li><b>{facts.calls}</b> recorded calls</li>
            <li><b>{facts.failures}</b> failures you can play</li>
          </ul>

          <section id="caller">
            <p className="eyebrow">The caller</p>
            <h2>Seven ways it makes trouble</h2>
            <p className="lead">
              Each drawing shows the caller on the top line and the agent below, the same way every recorded call
              is drawn further down. The calls are scripted, so every agent gets exactly the same caller.
            </p>
            <div className="families">
              {families.map((f) => (
                <article key={f.key} className="family">
                  <FamilyGlyph family={f.key} />
                  <h3>{f.name}</h3>
                  <p>{f.does}</p>
                  <p className="catches"><span>Catches</span>{f.catches}</p>
                  <p className="count">
                    {f.scenarios} scenarios{f.calls > 0 && <> · <b>{f.passed} of {f.calls}</b> calls passed</>}
                  </p>
                </article>
              ))}
            </div>
          </section>

          <section id="leaderboard">
            <p className="eyebrow">Results</p>
            <h2>Leaderboard</h2>
            <p className="lead">
              Counts are out of the number of times each situation came up, added over all passes. With {facts.scenarios} scenarios
              these are small samples: read them as counts, not percentages.
            </p>
            <Leaderboard agents={agents} columns={columns} />
            <p className="notice">
              Every entry so far is a baseline agent built from open models and run on one laptop. No commercial
              platform has been tested yet: the connections for ElevenLabs, Vapi, Retell and smallest.ai are written
              but have never been run.
            </p>
          </section>

          <section id="scenarios">
            <p className="eyebrow">Scenario by scenario</p>
            <h2>Where each agent held, and where it broke</h2>
            <p className="lead">Passes out of passes run. Follow a red or amber cell to hear that call.</p>
            <Matrix agents={agents} scenarios={scenarios} matrix={matrix} families={familyNames} />
          </section>

          <section id="failures">
            <p className="eyebrow">Recordings</p>
            <h2>Every failure, with audio</h2>
            <p className="lead">Pick an agent, then press play. The line moving across the drawing is where you are in the call.</p>
            <Failures failures={failures} agents={agents} families={familyNames} />
          </section>

          <section id="method">
            <p className="eyebrow">Method</p>
            <h2>Why the numbers can be trusted</h2>
            <p className="lead">
              Nothing is taken from an agent&apos;s own account of itself. When it spoke is read off the recording;
              what it said is transcribed from the recording. The measuring was then tested on agents whose
              behaviour is known in advance.
            </p>
            <div className="proof">
              {proof.map((p) => (
                <div key={p.title} className="proof-card">
                  <p className="figure">{p.figure}</p>
                  <h3>{p.title}</h3>
                  <p>{p.text}</p>
                </div>
              ))}
            </div>
            <p className="after-proof"><Link href="/calibration">See the calibration agents&apos; full results</Link></p>

            <div className="two">
              <div>
                <h3 className="sub-head">What each measurement means</h3>
                <dl className="defs">
                  {definitions.map((d) => (<div key={d.term}><dt>{d.term}</dt><dd>{d.meaning}</dd></div>))}
                </dl>
              </div>
              <div>
                <h3 className="sub-head">Read this before quoting a number</h3>
                <ul className="caveats">{CAVEATS.map((c) => <li key={c}>{c}</li>)}</ul>
              </div>
            </div>
          </section>

          <section className="closing">
            <Field quiet />
            <div className="closing-copy">
              <p className="pill">Not open yet</p>
              <h2>Testing your own agent</h2>
              <p>
                The same caller will be able to phone an agent on ElevenLabs, Vapi, Retell or smallest.ai and produce
                a page like this one, with a recording of every failure.
              </p>
              {site.contact_email
                ? <a className="btn btn-light" href={`mailto:${site.contact_email}`}>Ask about testing your agent</a>
                : site.repo_url && <a className="btn btn-light" href={site.repo_url}>Read the source</a>}
            </div>
          </section>
        </div>
      </main>
      <Footer />
    </>
  );
}
