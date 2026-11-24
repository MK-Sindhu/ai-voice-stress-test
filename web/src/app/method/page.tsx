import type { Metadata } from "next";
import Link from "next/link";
import { PageHead } from "@/components/PageHead";
import { arena } from "@/lib/arena";

export const metadata: Metadata = {
  title: "Method",
  description: "How the calls are measured, how the measuring was checked, and what to keep in mind before quoting a number.",
};

const CAVEATS = [
  "The caller is a synthetic voice, not a person. Real callers vary far more.",
  "The background noise is generated, not recorded.",
  "Content checks rely on a speech recogniser reading the agent's voice, and it makes mistakes.",
  "The baseline agents are slow, so an agent that decides too early often drops its reply before the caller hears it. “Talked over a pause” counts only what a caller would hear.",
  "About 30 scenarios is a small sample. Some measurements rest on five events per pass.",
];

export default function MethodPage() {
  const { proof, definitions } = arena;
  return (
    <div className="wrap page">
      <PageHead tag="Method" title="Why the numbers can be trusted">
        Nothing is taken from an agent&apos;s own account of itself. When it spoke is read off the recording; what it
        said is transcribed from the recording. The measuring was then tested on agents whose behaviour is known in advance.
      </PageHead>
      <div className="proof">
        {proof.map((p) => (
          <div key={p.title} className="proof-card">
            <p className="figure">{p.figure}</p>
            <h2>{p.title}</h2>
            <p>{p.text}</p>
          </div>
        ))}
      </div>
      <nav className="next-links" aria-label="Related pages">
        <Link href="/calibration">The calibration agents&apos; full results <span aria-hidden="true">→</span></Link>
      </nav>

      <div className="two">
        <section>
          <h2 className="sub-head">What each measurement means</h2>
          <dl className="defs">
            {definitions.map((d) => (<div key={d.term}><dt>{d.term}</dt><dd>{d.meaning}</dd></div>))}
          </dl>
        </section>
        <section>
          <h2 className="sub-head">Read this before quoting a number</h2>
          <ul className="caveats">{CAVEATS.map((c) => <li key={c}>{c}</li>)}</ul>
        </section>
      </div>
    </div>
  );
}
