// Everything the site shows comes from this one file, which `arena report`
// writes from the recorded calls. Nothing here is typed in by hand.
import raw from "@/content/arena.json";

export type Span = { start: number; end: number; lane: number; kind: string; title: string };
export type Mark = { t: number; label: string };
export type Failure = {
  id: string; agent: string; scenario: string; title: string; description: string;
  family: string; language: string; status: string; reasons: string[];
  passShown: number; passes: number; notPassed: number;
  audio: string | null; duration: number; spans: Span[]; marks: Mark[];
  callerLines: { text: string; kind: string }[]; agentLines: string[];
};
export type Metric = { value: string; footnote: string; share: number | null; perPass: string[] };
export type Agent = { id: string; label: string; calls: number; passes: number; metrics: Record<string, Metric> };
export type Cell = { passed: number; total: number; untestable: number; kind: "pass" | "fail" | "mixed" };
export type Scenario = { id: string; title: string; description: string; family: string; language: string };
export type Family = {
  key: string; name: string; does: string; catches: string; scenarios: number; calls: number; passed: number;
};
export type Column = { key: string; title: string; better: "higher" | "lower" };
export type Group = { agents: Agent[]; matrix: Record<string, Record<string, Cell>>; failures: Failure[] };

export type Arena = Group & {
  site: { name: string; url: string; repo_url: string; contact_email: string };
  stamp: { scenarioSet: string; code: string; callsPlaced: string };
  facts: { scenarios: number; languages: number; calls: number; failures: number };
  columns: Column[];
  definitions: { term: string; meaning: string }[];
  families: Family[];
  scenarios: Scenario[];
  hero: string | null;
  proof: { figure: string; title: string; text: string }[];
  calibration: Group;
};

export const arena = raw as unknown as Arena;
