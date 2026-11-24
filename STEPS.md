# Pipeline steps

What each step of the pipeline does, in the order it runs. The steps are defined in [dvc.yaml](dvc.yaml), and every setting they read is in [params.yaml](params.yaml).

`uv run dvc repro` runs all of them. It skips any step whose inputs have not changed since the last run. Each step can also be run on its own with the command shown.

| # | Step | Command | In one line |
|---|---|---|---|
| 1 | Validate scenarios | `arena validate` | Check that every scenario file is well formed |
| 2 | Check metrics | `arena check-metrics` | Prove the metrics measure correctly, using fake agents |
| 3 | Generate noise | `arena noise` | Make the background noise files |
| 4 | Render audio | `arena render` | Turn every scripted line into speech |
| 5 | Check audio | `arena check-audio` | Confirm a speech recogniser understands the caller's lines |
| 6 | Run | `arena run --agent <name>` | Place the calls and record them |
| 7 | Score | `arena score --agent <name>` | Measure what the agent did in each call |
| 8 | Report | `arena report` | Build the leaderboard and the website |

Steps 1 to 5 prepare and check the test itself. Steps 6 and 7 run once per agent. Step 8 combines all agents.

## 1. Validate scenarios

**Command:** `uv run arena validate`

Reads every file in [scenarios/](scenarios/) and checks it in two ways:

- **Shape.** The file matches the schema in [src/arena/schema/scenario.schema.json](src/arena/schema/scenario.schema.json): the right fields, the right types, a known family and language.
- **Sense.** Things a schema cannot express: step ids are unique, a check refers to a step that exists, an interruption comes after something the agent can be interrupted in, a noise scenario names a noise kind.

It also computes a short fingerprint of the whole scenario set (for example `ea2ee3631ac1`). That fingerprint is printed on the leaderboard, so a result can always be tied to the exact scenarios it came from.

**Writes:** `results/validation.json`
**Stops the pipeline if:** any scenario is invalid.

## 2. Check metrics

**Command:** `uv run arena check-metrics`

Tests the measuring instrument before it is used on a real agent. Fake agents with exactly known behaviour are run through the real engine, and the measured values are compared with the configured ones:

- Response delay set to 200 to 2000 ms.
- Time to stop when interrupted set to 100 to 1200 ms.
- An agent that never stops when interrupted.
- Agents that do and do not talk over a mid-thought pause.
- Agents that do and do not stop for a filler word.

These calls run on a simulated clock, so the step takes seconds. The same checks run as tests in [tests/test_metric_validation.py](tests/test_metric_validation.py).

**Writes:** `results/metric_validation.json`
**Stops the pipeline if:** a timing is off by more than the tolerance (30 ms) or a yes/no outcome is wrong.

## 3. Generate noise

**Command:** `uv run arena noise`

Creates the three background-noise files used by the noise scenarios: street, crowd and television. They are generated from a fixed seed, not recorded, so they are identical on every machine.

**Writes:** `data/noise/`

## 4. Render audio

**Command:** `uv run arena render`

Turns every scripted line into speech with the Kokoro text-to-speech model:

- **Caller lines** from the scenarios, in the caller's voice. Hinglish lines are read from their Devanagari `spoken` form.
- **Reference replies** (the `oracle` and `wrong` texts) and the agent's check-in line, in the agent's voice. These are used by the calibration agents.

Each line is saved under a name made from a hash of its text and voice settings. A line that already exists is not rendered again, so editing one scenario re-renders only the lines that changed.

**Writes:** `data/caller_audio/`, `data/agent_audio/`, `results/render.json`

## 5. Check audio

**Command:** `uv run arena check-audio`

Makes sure the caller can be understood. A failed call should be the agent's fault, never the fault of a badly pronounced line.

Every caller line is transcribed by a speech recogniser (Whisper large-v3-turbo) and compared with its text. A line fails if more than 25% of its characters are misheard, or if a number in it comes out wrong. Lines that fail are rewritten in the scenario file by hand.

**Writes:** `results/intelligibility.json`
**Stops the pipeline if:** any caller line fails.

## 6. Run (once per agent)

**Command:** `uv run arena run --agent <name>`

Places the calls. For each scenario:

1. The agent is started and connected.
2. The caller and the agent exchange audio in 20 ms pieces on a real-time clock. The caller follows its script: speaking, pausing, waiting for the agent, or talking over it.
3. Both sides are recorded side by side, and every caller action is logged with its exact time.

Live agents go through the whole scenario set twice, because a live agent does not behave identically each time. Calibration agents go through once.

The agents run by the pipeline are listed under `pipeline_agents` in [params.yaml](params.yaml). Useful options: `--scenarios scenarios/barge_in_*.yaml` to run a subset, `--repeats 1` for a single pass.

**Writes:** `results/runs/<agent>/rep<k>/<scenario>/recording.wav` and `timeline.json`, plus `results/runs/<agent>/run.json` with the settings and code version used.

This is the slow step: about 25 minutes per live agent.

## 7. Score (once per agent)

**Command:** `uv run arena score --agent <name>`

Measures each recorded call. Nothing is taken from the agent's own logs; everything comes from the recording and the caller's timeline.

- **Timing.** Finds when the agent was speaking on its channel, then works out response delay, whether it talked over a pause, whether and how fast it stopped when interrupted, and whether it stopped for a filler word.
- **Content.** Transcribes the agent's replies and checks them: the right number, date or name was read back; the reply after an interruption deals with the interruption; the reply is in the caller's language.
- **Verdict.** Each scenario is marked pass, fail or untestable, with the reason. Untestable means a check could not be applied, for example the agent's answer was too short to interrupt.

Each pass is also logged to MLflow as one run, with settings, metrics and recordings.

Because this step reads only the saved recordings, changing a metric or a threshold rescores every agent without placing the calls again.

**Writes:** `results/scores/<agent>.json`

## 8. Report

**Command:** `uv run arena report`

Combines the scores of all agents into what people read:

- `results/leaderboard.json`: the leaderboard numbers.
- `docs/index.html`: the leaderboard, results by scenario, and every failure with a playable recording.
- `docs/calibration.html`: the results of the fake and oracle agents, which show whether the metrics can be trusted.
- `docs/audio/`: the failure recordings, compressed to MP3.
- The leaderboard table in [README.md](README.md), between the `leaderboard:start` and `leaderboard:end` markers.

Calibration agents never appear on the leaderboard. An agent that has not been run does not appear at all.

## What reruns when something changes

| You change | Steps that run again |
|---|---|
| One scenario file | 1, 4 (only the changed lines), 5, 6, 7, 8 |
| A metric or threshold in `params.yaml` | 2, 7, 8 (no calls are placed again) |
| One agent's settings | 6 and 7 for that agent, then 8 |
| The caller's voice | 4, 5, 6, 7, 8 |
| The report layout | 8 |
