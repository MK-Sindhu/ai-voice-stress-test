import type { Metadata } from "next";
import { Leaderboard, Matrix } from "@/components/Board";
import { Failures } from "@/components/Failures";
import { PageHead } from "@/components/PageHead";
import { arena } from "@/lib/arena";

export const metadata: Metadata = {
  title: "Calibration agents",
  description: "Results of agents whose behaviour is known in advance, used to check that the measurements are right.",
};

export default function CalibrationPage() {
  const { calibration, columns, scenarios, families } = arena;
  return (
    <div className="wrap page">
      <PageHead tag="Method · checking the measurements" title="Calibration agents">
        These are not real agents. Their behaviour is known in advance, so they show whether the arena measures
        correctly. A fake agent set to reply after 500 ms must be measured at 500 ms; the oracle, which is handed the
        script, must pass everything; the oracle that states wrong details must be caught.
      </PageHead>
      <Leaderboard agents={calibration.agents} columns={columns} ranked={false} />
      <section className="block">
        <div className="block-head"><h2>Results by scenario</h2></div>
        <Matrix agents={calibration.agents} scenarios={scenarios} matrix={calibration.matrix} families={families} linkTo={null} />
      </section>
      <section className="block">
        <div className="block-head"><h2>What was flagged</h2></div>
        <p className="lead">
          The fake agents reply with a tone, so they fail every check on what was said. That is expected; their job is
          to test the timing. These calls have no audio here.
        </p>
        <Failures failures={calibration.failures} agents={calibration.agents} families={families} />
      </section>
    </div>
  );
}
