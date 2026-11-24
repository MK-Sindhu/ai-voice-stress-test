# Plan: Voice agent stress-test arena

Status: plan only. Nothing is built yet.

## Goal

An automated "caller from hell" that holds real-time spoken conversations with a voice agent, deliberately triggers the known failure modes of voice agents, scores the agent, and publishes a leaderboard with audio clips of every failure. The focus is Indian callers: Hindi, Indian English and Hinglish code-switching.

## Ground rules

- Zero cost: open models and local compute. No telephony.
- No commercial API is called during the build. Platform adapters are written but stay unrun until the owner supplies keys.
- Every number on the leaderboard comes from a run that actually happened, with raw results saved under `results/`. No placeholder numbers for agents that were not run.
- Small, regular commits under the owner's git identity. No pushing.

## Steps

### 1. Scenarios

About 30 short scenarios (20 to 40 seconds each), written as YAML files. Each one is a scripted sequence of caller lines with timing instructions and the checks to apply. They are scripted, not improvised by an LLM, so that every run is identical and comparable.

| Family | Example | What it catches |
|---|---|---|
| Mid-thought pause | "Table for... (2 s pause) ...four people on Friday" | Agent talks over the caller |
| Barge-in | Caller cuts into a long answer: "No wait, I want a replacement" | Agent keeps talking, or resumes the old answer |
| Backchannel | Caller says "hmm" or "haan" while the agent speaks | Agent wrongly stops |
| Numbers and details | "Order number 4 7 double 9 3", phone numbers, dates, addresses, spelled-out emails, in Hindi and Hinglish | Details misheard or read back wrong |
| Background noise | TV, street or crowd noise at a set loudness | Agent responds to noise or mishears |
| Change of mind | "Book it for Friday, no actually Saturday" | Agent acts on the first version |
| Long silence | Caller goes quiet | Agent hangs, or never checks in |

### 2. Caller

- Caller lines are spoken by a local open-source text-to-speech engine. Kokoro and Piper are the candidates; the one that handles Hindi and Indian-accented English better is chosen.
- Rendered audio is cached.
- Each rendered line is transcribed by a local speech recogniser to confirm it is intelligible. Lines that fail are rewritten or dropped.

### 3. Real-time audio engine

- Caller and agent exchange audio in 20 ms frames on a real clock, and both can speak at once.
- Every run saves a two-channel recording (caller on the left, agent on the right) and a timeline of events with the exact times of everything the caller did.

### 4. Agents under test

One small adapter interface (connect, send audio, receive audio, close) lets any agent be plugged in.

| Agent | Purpose | Run during the build? |
|---|---|---|
| Fake agents with known behaviour (replies after exactly X ms, never stops when interrupted, stops after exactly Z ms) | Prove the metrics measure correctly | Yes |
| Local baseline: speech recognition (faster-whisper), LLM via Ollama, text-to-speech, with a silence timeout of 500 ms and 1000 ms | Real leaderboard entries | Yes |
| Local baseline using the end-of-turn detector from the sibling project | Shows the detector's effect in a live agent | Yes, once the detector exists |
| ElevenLabs, smallest.ai, Vapi, Retell | The comparison the companies care about | No. Written from their public docs, marked untested, kept off the leaderboard until run with the owner's keys |

### 5. Metrics

All are computed from the recording and timeline, and reported as counts with denominators.

| Metric | Definition |
|---|---|
| Response delay | Caller stops speaking to agent's first sound; median and 95th percentile |
| False interruptions | Agent starts speaking during a caller's mid-utterance pause |
| Barge-in stop time | Caller starts speaking over the agent to agent going silent |
| Barge-in recovery | Whether the next reply addresses the interruption |
| Backchannel robustness | Agent wrongly stops on "hmm" or "haan" |
| Detail accuracy | Agent's reply is transcribed and checked for the right number, ID or date (handling digits, Hindi number words, "double nine") |
| Language match | Reply is in the caller's language mix |
| Task completion | Per-scenario pass or fail |
| No response | Agent never replies or times out |

**Metric validation**: the fake agents have known timings, so the measured values must match them within a stated tolerance. This runs as automated tests, and the measurement error is published in the README. A benchmark with unverified metrics is not credible.

### 6. Runner and leaderboard

- Commands: `arena run --agent <name> --scenarios <files>` and `arena report`.
- The report is a static website in `docs/` (ready for GitHub Pages) with the leaderboard table, a per-scenario breakdown, and playable audio of each failure with its timeline drawn out.

### 7. MLOps

| Tool | Used for |
|---|---|
| **DVC pipeline** | `dvc.yaml` defines the stages render caller audio, intelligibility check, run (one per agent configuration), score, build report. `dvc repro` reruns only what changed, so editing one scenario does not re-render the rest. |
| **DVC data versioning** | Rendered caller audio, noise files and full run recordings are tracked by DVC, with only the small pointer files in git. The remote is a local folder during the build. |
| **`params.yaml`** | Agent configurations (timeouts, thresholds, model names), caller voice, noise levels and metric tolerances in one file. |
| **MLflow tracking** | Each benchmark run is one MLflow run: the agent configuration as parameters, every metric, and the recordings and timelines as artifacts, tagged with the git commit and scenario-set version. `mlflow ui` then compares agents and reruns side by side. |
| **DVC metrics** | The leaderboard numbers are also written as JSON metrics, so `dvc metrics diff` shows how an agent's scores moved between commits. |
| **Scenario validation** | A pipeline stage checks every scenario file against a schema before anything runs. |
| **CI (GitHub Actions)** | On every push: lint, the metric-validation tests against the fake agents, and scenario schema checks. Free for public repos; it starts running once the owner pushes. |

One caveat: a run against a live agent is not perfectly repeatable, because the LLM's replies and real-time scheduling vary. Each configuration is therefore run more than once, and the spread is reported alongside the score.

MLflow run folders and the DVC cache stay out of git.

### 8. Repo contents

- Test suite centred on metric validation.
- Reproducible from a clean clone with `dvc repro`.
- README: leaderboard first, then scenario catalogue, architecture, metric definitions with measured error, how to add an agent, how to run against commercial platforms, and limitations.

## Known limitations (stated in the README)

- The caller is a synthetic voice, not a human, so accents and hesitation are less varied than real callers.
- Scenarios are scripted, so they do not cover open-ended conversation.
- About 30 scenarios per agent is a small sample; results come with counts, not just percentages.
- Commercial adapters are untested until run with real keys.

## What needs the owner

- **Free-tier API keys** for ElevenLabs, smallest.ai, Vapi or Retell, to put commercial platforms on the leaderboard. The free minutes on each platform were not checked; about 30 scenarios of 20 to 40 seconds is roughly 15 to 20 minutes of call time per platform per full run.
- **Publishing the site** through GitHub Pages after pushing.
- **Ollama model**: one small model (about 2 to 3 GB) is downloaded for the baseline agent.

## Order of work

1. Thin slice: one scenario, one fake agent, metrics, report page. DVC pipeline, `params.yaml` and MLflow logging are in place from this first slice.
2. Audio engine, all fake agents, metric validation tests.
3. Caller voice selection and intelligibility check; full scenario set.
4. Local baseline agent; real runs at 500 ms and 1000 ms silence timeouts.
5. Leaderboard site with audio clips.
6. Commercial adapters (untested) and the instructions to run them; CI workflow.
7. After the detector project is finished: add the baseline-with-detector entry and rerun.

## Decisions to confirm

- Scenario languages: roughly one third each of Hindi, Hinglish and Indian English. Change the mix if one matters more.
- Commercial platforms to write adapters for: ElevenLabs, smallest.ai, Vapi, Retell. Drop or add any.
- Whether the build may use the owner's API keys once provided, or whether the owner runs those tests personally.
