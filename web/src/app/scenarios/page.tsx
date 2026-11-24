import type { Metadata } from "next";
import { Matrix } from "@/components/Board";
import { FamilyGlyph } from "@/components/FamilyGlyph";
import { PageHead } from "@/components/PageHead";
import { arena } from "@/lib/arena";

export const metadata: Metadata = {
  title: "Scenarios",
  description: "The scripted calls: what the caller does in each, what it catches, and how every agent did.",
};

export default function ScenariosPage() {
  const { families, agents, scenarios, matrix, facts } = arena;
  return (
    <div className="wrap page">
      <PageHead tag="Scenarios" title="Seven ways the caller makes trouble">
        {facts.scenarios} scripted calls of 10 to 40 seconds. They are scripted, not improvised, so every agent gets
        exactly the same caller. Each drawing shows the caller on the top line and the agent below.
      </PageHead>
      <div className="families">
        {families.map((f) => (
          <article key={f.key} className="family">
            <FamilyGlyph family={f.key} />
            <h2>{f.name}</h2>
            <p>{f.does}</p>
            <p className="catches"><span>Catches</span>{f.catches}</p>
            <p className="count">{f.scenarios} scenarios{f.calls > 0 && <> · <b>{f.passed} of {f.calls}</b> calls passed</>}</p>
          </article>
        ))}
      </div>

      <section className="block" id="results">
        <div className="block-head">
          <div>
            <p className="tag">Scenario by scenario</p>
            <h2>Where each agent held, and where it broke</h2>
          </div>
        </div>
        <p className="lead">Passes out of passes run. Follow a red or amber cell to hear that call.</p>
        <Matrix agents={agents} scenarios={scenarios} matrix={matrix} families={families} />
      </section>
    </div>
  );
}
