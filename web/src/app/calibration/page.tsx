import type { Metadata } from "next";
import Link from "next/link";
import { Leaderboard, Matrix } from "@/components/Board";
import { Failures } from "@/components/Failures";
import { Footer, Nav } from "@/components/Nav";
import { arena } from "@/lib/arena";

export const metadata: Metadata = { title: `${arena.site.name}: calibration agents` };

const LINKS = [
  { href: "/", label: "Leaderboard" },
  { href: "#results", label: "Results" },
  { href: "#flagged", label: "Flagged" },
];

export default function Calibration() {
  const { calibration, columns, scenarios, families } = arena;
  const familyNames = families.map(({ key, name }) => ({ key, name }));
  return (
    <>
      <Nav links={LINKS} />
      <main className="wrap plain-page">
        <p className="eyebrow">Method · checking the measurements</p>
        <h1 className="page-title">Calibration agents</h1>
        <p className="lead">
          These are not real agents. Their behaviour is known in advance, so they show whether the arena measures
          correctly. A fake agent set to reply after 500 ms must be measured at 500 ms; the oracle, which is handed
          the script, must pass everything; the oracle that states wrong details must be caught.
        </p>
        <Link className="btn btn-glass" href="/">Back to the leaderboard</Link>

        <section id="results">
          <h2>Results</h2>
          <Leaderboard agents={calibration.agents} columns={columns} ranked={false} />
        </section>
        <section id="scenarios">
          <h2>Results by scenario</h2>
          <Matrix agents={calibration.agents} scenarios={scenarios} matrix={calibration.matrix} families={familyNames} />
        </section>
        <section id="flagged">
          <h2>What was flagged</h2>
          <p className="lead">
            The fake agents reply with a tone, so they fail every check on what was said. That is expected; their job
            is to test the timing. These calls have no audio here.
          </p>
          <Failures failures={calibration.failures} agents={calibration.agents} families={familyNames} />
        </section>
      </main>
      <Footer />
    </>
  );
}
