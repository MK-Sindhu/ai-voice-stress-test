import type { Metadata } from "next";
import { Failures } from "@/components/Failures";
import { PageHead } from "@/components/PageHead";
import { arena } from "@/lib/arena";

export const metadata: Metadata = {
  title: "Failures",
  description: "A recording of every call a voice agent failed, drawn as a timeline with the moment it went wrong marked.",
};

export default function FailuresPage() {
  const { failures, agents, families } = arena;
  return (
    <div className="wrap page">
      <PageHead tag="Recordings" title="Every failure, with audio">
        Pick an agent, then press play. The line moving across the drawing is where you are in the call.
      </PageHead>
      <Failures failures={failures} agents={agents} families={families} />
    </div>
  );
}
