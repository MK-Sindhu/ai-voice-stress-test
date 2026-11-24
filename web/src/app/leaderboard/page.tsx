import type { Metadata } from "next";
import Link from "next/link";
import { Leaderboard } from "@/components/Board";
import { PageHead } from "@/components/PageHead";
import { arena } from "@/lib/arena";

export const metadata: Metadata = {
  title: "Leaderboard",
  description: "Every measurement for every voice agent tested, as counts out of the number of times each situation came up.",
};

export default function LeaderboardPage() {
  const { agents, columns, facts } = arena;
  return (
    <div className="wrap page">
      <PageHead tag="Leaderboard" title="Every agent, every measurement">
        Counts are out of the number of times each situation came up, added over all passes. With {facts.scenarios} scenarios
        these are small samples: read them as counts, not percentages.
      </PageHead>
      <Leaderboard agents={agents} columns={columns} />
      <p className="notice">
        Every entry so far is a baseline agent built from open models and run on one laptop. No commercial platform has
        been tested yet: the connections for ElevenLabs, Vapi, Retell and smallest.ai are written but have never been run.
      </p>
      <nav className="next-links" aria-label="Related pages">
        <Link href="/scenarios">Results scenario by scenario <span aria-hidden="true">→</span></Link>
        <Link href="/method">What each measurement means <span aria-hidden="true">→</span></Link>
      </nav>
    </div>
  );
}
