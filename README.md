# Voice agent stress-test arena

An automated "caller from hell" for voice agents. A scripted caller holds real-time spoken calls with an agent in Hindi, Hinglish and Indian English, deliberately sets off the situations voice agents are known to get wrong, scores what the agent did, and publishes a leaderboard with a playable recording of every failure.

Everything runs locally on open models. No telephony and no paid API is involved.

## Leaderboard

<!-- leaderboard:start -->
| Agent | Scenarios passed | Response delay, median / p95 | Talked over a pause | Stopped when interrupted | Time to stop, median | Kept talking through 'hmm' | Details read back right | Replied in caller's language |
|---|---|---|---|---|---|---|---|---|
| Local baseline, 1000 ms silence timeout, larger recogniser | 29/60 (1 untestable) | 4,830 ms / 6,301 ms (70 turns) | 0/14 | 10/10 | 270 ms | 0/9 | 8/18 | 54/54 |
| Local baseline, 1000 ms silence timeout | 22/60 | 2,630 ms / 3,556 ms (70 turns) | 2/14 | 10/10 | 270 ms | 0/10 | 6/18 | 54/54 |
| Local baseline, end-of-turn detector (Hindi audio model, threshold 0.9) | 21/60 | 2,860 ms / 3,606 ms (70 turns) | 2/14 | 10/10 | 260 ms | 0/10 | 6/18 | 53/54 |
| Local baseline, 500 ms silence timeout | 21/60 | 2,650 ms / 5,033 ms (70 turns) | 5/14 | 10/10 | 270 ms | 0/10 | 6/18 | 54/54 |

Counts are out of the number of times each situation came up, over all passes. Scenario set `ea2ee3631ac1`. Full results with audio: [docs/index.html](docs/index.html).
<!-- leaderboard:end -->

These are four configurations of one local pipeline, each run through all 30 scenarios twice (60 calls) on 24 November 2026. No commercial platform has been run. What the calls show:

- **Every configuration stops for a filler word.** All of them went quiet within 360 ms of "hmm", "हाँ" or "अच्छा" on every one of the 39 occasions tested. They treat any speech from the caller as an interruption. That also makes them reliable at stopping for a real interruption (10 of 10, about 270 ms).
- **Crowd and television noise silences them completely.** In three of the four noise scenarios (10 dB signal-to-noise) no configuration ever replied: the voice-activity detector hears the background as continuous speech and never finds the end of the turn. Only the street-noise call was answered.
- **A shorter silence timeout did not make the agent faster, only ruder.** The 500 ms timeout talked over 5 of 14 mid-thought pauses against 2 of 14 for 1000 ms, with the same median response delay (2,650 and 2,630 ms). Speech recognition takes about 850 ms and already starts 200 ms into the silence, so it, not the timeout, sets the delay.
- **The end-of-turn detector did not beat the 1000 ms timeout here.** It talked over the same 2 of 14 pauses and was slower at the median (2,860 ms). It decided "finished" after 200 ms on 59 of 108 turn ends and fell back to its 1,500 ms limit on the other 49. That model is unfinished work in progress, so this is a first reading, not a verdict.
- **The larger recogniser helps where hearing matters and costs two seconds.** Details read back right rose from 6 to 8 of 18 and scenarios passed from 22 to 29 of 60, but the median delay went from 2.6 to 4.8 seconds. It never talked over a pause, mostly because it is too slow to: the caller resumes before it has said anything.
- **No configuration handled a change of mind** (0 of 6), and details are read back wrong most of the time. The small language model and the recogniser both contribute; the failure list on the site has the audio for each.
- The two passes gave nearly identical results (the language model runs at temperature 0), so the second pass adds little independent evidence.

## Run it

```
uv sync --extra local          # Python 3.12 environment with the speech models' libraries
ollama pull llama3.2:3b        # the language model the local baseline agents use (2 GB)
uv run dvc repro               # validate, render, run every agent, score, build the site
open docs/index.html
```

A full run places 360 calls and takes about two hours on an Apple M4 laptop, 95 minutes of it the agents talking in real time. To work on one piece:

```
uv run arena run --agent local-silence-500 --scenarios scenarios/barge_in_*.yaml
uv run arena score --agent local-silence-500
uv run arena report
uv run pytest                  # metric validation and the rest of the tests, about 10 seconds
```

## Scenarios

30 scripted calls of 10 to 40 seconds, one YAML file each in [scenarios/](scenarios/). They are scripted, not improvised by a language model, so every agent gets exactly the same caller.

| Family | What the caller does | What it catches |
|---|---|---|
| Mid-thought pause | Stops for 1.5 to 3 seconds in the middle of a sentence, then finishes it | Agent answers the half sentence and talks over the caller |
| Barge-in | Cuts into the agent's answer after 1, 2 or 4 seconds with a new request | Agent keeps talking, or carries on with the old answer |
| Backchannel | Says "mm-hmm", "हाँ" or "अच्छा" while the agent is explaining | Agent wrongly stops |
| Numbers and details | Gives an order number with "double nine", a mobile number in Hindi, a PIN code, a date, a spelled-out email, two amounts | Details misheard or read back wrong |
| Background noise | Speaks over street, crowd or television noise, after four seconds of noise alone | Agent answers the noise, or mishears |
| Change of mind | "Friday… no, actually, Saturday" | Agent acts on the first version |
| Long silence | Says nothing for 12 to 15 seconds, then comes back | Agent never checks in, or is gone when the caller returns |

| Family | Indian English | Hindi | Hinglish | Total |
|---|---|---|---|---|
| Mid-thought pause | 2 | 2 | 1 | 5 |
| Barge-in | 1 | 2 | 2 | 5 |
| Backchannel | 1 | 1 | 2 | 4 |
| Numbers and details | 3 | 2 | 1 | 6 |
| Background noise | 1 | 1 | 2 | 4 |
| Change of mind | 1 | 1 | 1 | 3 |
| Long silence | 1 | 1 | 1 | 3 |
| Total | 10 | 10 | 10 | 30 |

A scenario file is a list of caller steps and the checks to apply:

```yaml
id: barge_in_replacement_en
family: barge_in
language: en-IN
steps:
- say: Can you explain your return policy in detail?
  id: ask
- wait_agent_speech:        # wait until the agent has been talking for 2 s ...
    for: 2.0
- say: No wait, I don't want a refund, I want a replacement.
  id: cut
  kind: barge_in            # ... then talk over it
- listen:
    oracle: Sure, I will arrange a replacement for you instead. Can I have your order number?
checks:
- type: barge_in_stops
- type: recovery            # the next reply must be about the replacement
  reply_to: cut
  mentions:
  - [replacement, replace]
```

Hinglish lines are written the way people type them ("Mujhe Friday ko table book karni hai") and carry a Devanagari `spoken` form for the voice to read. The `oracle` and `wrong` texts are a correct and a deliberately incorrect reply; they are used to check the content metrics (see below).

## How a call works

```
            every 20 ms
 Caller ──── 320 samples ────▶ Agent under test
   ▲                              │
   └────────── 320 samples ◀──────┘
 both streams are written side by side:
   recording.wav   caller on the left channel, agent on the right
   timeline.json   every caller action with its exact time
```

- **Caller** ([caller.py](src/arena/caller.py)). Lines are spoken by Kokoro, an open text-to-speech model, with a Hindi voice that is also used for the Indian English lines. Rendered lines are cached by a hash of their text and voice settings. The caller hears the agent, so it can wait for a reply to finish or time an interruption, but it never improvises.
- **Intelligibility check.** Every rendered line is transcribed by a speech recogniser (Whisper large-v3-turbo) and compared with its text. Lines that are not understood are rewritten. All 50 caller lines in the current set pass: on average 1.9% of characters are misheard, 20% in the worst line, against a limit of 25% ([results/intelligibility.json](results/intelligibility.json)).
- **Engine** ([engine.py](src/arena/engine.py)). A loop on a real 20 ms clock. Both sides can speak at once. How far the loop ran behind the clock is saved with every call.
- **Agent adapter** ([agents/base.py](src/arena/agents/base.py)). Four methods: `connect`, `send_audio`, `receive_audio`, `close`. The agent only ever receives the caller's audio.
- **Scoring** ([metrics.py](src/arena/metrics.py), [score.py](src/arena/score.py)). Nothing is taken from the agent's own account of itself. When the agent spoke is read off its channel of the recording; what it said is transcribed from that audio.

## Agents

| Agent | What it is | Status |
|---|---|---|
| `local-silence-500`, `local-silence-1000` | A plain pipeline from open models: Silero voice-activity detection, faster-whisper `small`, `llama3.2:3b` through Ollama, Kokoro speech. It decides the caller has finished after 500 or 1000 ms of silence. | Run, on the leaderboard |
| `local-turbo-1000` | The same with the larger `large-v3-turbo` recogniser: hears Hindi far better, answers later. | Run, on the leaderboard |
| `local-detector` | The same as `local-silence-500` but the end-of-turn decision is made by the audio model from the sibling [End-of-turn-detector](../End-of-turn-detector) project: after 200 ms of quiet the model is asked whether the caller is finished. | Run, on the leaderboard. That project is still in progress; the entry uses its model as of commit `e217209` |
| `fake-*` | Agents that reply with a tone at exact, configured times | Calibration only |
| `oracle`, `oracle-wrong` | Agents that are handed the script and say the reference reply, or a wrong one on purpose | Calibration only |
| ElevenLabs, Vapi, Retell, smallest.ai | Adapters written from public documentation | **Untested. Never run. Not on the leaderboard.** See [COMMERCIAL.md](COMMERCIAL.md) |

The local agents all use the instructions in [prompts/agent_system.md](prompts/agent_system.md). Use the same text for any other agent you add, so the comparison is fair.

## Metrics

All metrics are computed from the recording and the timeline, and reported as counts out of the number of times the situation came up.

| Metric | Definition |
|---|---|
| Response delay | From the caller's last sound in a turn to the agent's first sound. Median and 95th percentile. Turns where the agent was already talking are left out |
| Talked over a pause (false interruption) | The agent started speaking between the start of a mid-thought pause and the end of the caller's turn |
| Stopped when interrupted | After the caller starts talking over the agent, the agent goes quiet (for at least 700 ms) within 1500 ms |
| Time to stop | From the start of the interruption to the agent going quiet |
| Dealt with the interruption | The reply after an interruption mentions what the caller interrupted about |
| Kept talking through "hmm" | The agent did not go quiet within one second of a filler word |
| Details read back right | The reply is transcribed and searched for the right number, date or name. "4 7 double 9 3", "47993", "forty-seven thousand…" and "चार सात नौ नौ तीन" all count as 47993 |
| Replied in caller's language | The recogniser hears the reply as English for an English caller and as Hindi for a Hindi or Hinglish caller |
| Scenarios passed | Every check in the scenario passed and every caller turn got a reply |
| Turns with no reply | The agent said nothing within 10 seconds of a caller turn |

A check that could not be applied is reported as **untestable**, not as a pass or a fail. Example: the agent's answer was too short to interrupt.

### Do the metrics measure correctly?

A benchmark with unverified metrics is not credible, so the metrics are tested against agents whose behaviour is known in advance.

**Timing.** Fake agents with exact timings are run through the engine and the measured value is compared with the configured one. These comparisons run as tests on every push ([tests/test_metric_validation.py](tests/test_metric_validation.py)) and are written to [results/metric_validation.json](results/metric_validation.json).

| What was checked | Configured values | Result |
|---|---|---|
| Response delay | 200, 300, 500, 700, 1000, 1500, 2000 ms, and 500 ms on a real clock | Measured exactly, error 0 ms |
| Time to stop when interrupted | 100, 200, 300, 500, 800, 1200 ms | Measured exactly, error 0 ms |
| Agent that never stops | | Reported as not stopping |
| Talking over a pause | Reply delays of 500 to 2500 ms against pauses of 1 and 2 s | Reported in the 2 cases where it happens, not in the 2 where it does not |
| Stopping for a filler word | An agent that stops and one that does not | Both reported correctly |

14 timing checks and 8 yes/no checks, all correct. The allowed timing error is 30 ms. The measurement works in 10 ms steps and the fake agents act on 20 ms frame boundaries, which is why the error is exactly zero and not merely small; a real agent's timings are measured to about 10 ms.

**Content.** The oracle agent says the reference reply for every turn through the same voice the local agents use; `oracle-wrong` says a reply with one detail changed. A perfect measurement would pass the first on everything and fail the second on every detail.

| Agent | Scenarios passed | Details read back right | What it shows |
|---|---|---|---|
| `oracle` (says the right thing) | 30/30 | 9/9 | No correct reply was marked wrong |
| `oracle-wrong` (one detail changed) | 18/30 | 0/9 | Every wrong detail was caught. The 12 failures are the 9 detail scenarios and the 3 change-of-mind scenarios, as intended |

This holds for one voice. Getting there took rewording: Hindi digit strings and place names did not survive the trip through the voice and the recogniser reliably, so read-backs are checked on numbers, and number words are accepted in either language. Full output: [docs/calibration.html](docs/calibration.html).

## Pipeline and tracking

| Tool | Used for |
|---|---|
| DVC pipeline ([dvc.yaml](dvc.yaml)) | Stages: validate scenarios, check metrics, generate noise, render caller audio, intelligibility check, run (one per agent), score (one per agent), report. `dvc repro` reruns only what changed: editing one scenario re-renders one line; changing a metric rescores without making the calls again |
| DVC data versioning | Rendered audio, noise and all call recordings are tracked by DVC with only fingerprints in git ([dvc.lock](dvc.lock)). The remote is a local folder, `../.dvc-remotes/stress-test-arena` |
| [params.yaml](params.yaml) | Every setting: agent configurations, voices, thresholds, tolerances |
| MLflow | Each pass of an agent over the scenarios is one MLflow run with the agent's settings, every metric, and the recordings and timelines as artifacts, tagged with the git commit and the scenario-set version. `uv run mlflow ui --backend-store-uri sqlite:///mlflow.db --port 5001` |
| DVC metrics | [results/leaderboard.json](results/leaderboard.json) holds the leaderboard numbers, so `dvc metrics diff` shows how an agent's scores moved between commits |
| CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) | On every push: lint, scenario schema checks, metric measurement against the fake agents, tests. It installs no speech model and starts running once the repo is pushed to GitHub |

A run against a live agent is not perfectly repeatable: the language model's wording and real-time scheduling vary. Each local agent is therefore run through the whole set twice, and the leaderboard shows each pass's number under the total.

## The website

The site is a Next.js app in [web/](web/). It contains no numbers of its own: `arena report` writes the results to `web/src/content/arena.json` and the failure recordings to `web/public/audio/`, and the site renders those. It has a short landing page and separate pages for the leaderboard, the scenarios, every failure with a playable recording drawn as a timeline, the method, and the calibration agents.

```
cd web && npm install && npm run dev
```

To deploy on Vercel, import the repository and set the Root Directory to `web`. The site name, its public address (`url`, used for the sitemap and link previews), the "Source" link and an optional contact address are set under `site:` in [params.yaml](params.yaml). See [web/README.md](web/README.md).

`arena report` also still writes a plain-HTML copy of the same results to [docs/](docs/), which needs no build and opens straight from disk. The worker's per-job results page uses that same HTML.

## Testing one agent on request

`arena job` runs, scores and reports a single agent into one folder, and there is a container image for it. This is the worker for a future "test my agent" form on the website. See [WORKER.md](WORKER.md) for how to run it and [AWS.md](AWS.md) for the planned hosting and its estimated cost. Nothing has been deployed.

## Add an agent

1. Write a class with the four methods in [agents/base.py](src/arena/agents/base.py). `receive_audio` must return 20 ms of audio immediately, silence if there is nothing to say. [agents/fake.py](src/arena/agents/fake.py) is the smallest example, [agents/_network.py](src/arena/agents/_network.py) has the buffer a network agent needs.
2. Register it in `AGENT_TYPES` in `base.py`.
3. Add an entry under `agents:` in `params.yaml`, and its name to `pipeline_agents` if `dvc repro` should run it.
4. `uv run arena run --agent <name>`, `uv run arena score --agent <name>`, `uv run arena report`.

## Commercial platforms

Adapters for ElevenLabs, Vapi, Retell and smallest.ai are in [src/arena/agents/](src/arena/agents/). They were written from the platforms' public documentation and have never been run, because no API key was used while building this. They are kept off the leaderboard until someone runs them. [COMMERCIAL.md](COMMERCIAL.md) has the steps for each platform and the points in each adapter that are most likely to need fixing on first contact.

## Limitations

- The caller is a synthetic voice, not a person. Accents, hesitation and speaking style vary far less than with real callers. The Indian English lines are a Hindi voice reading English, not a recorded Indian English speaker.
- The background noise is generated (filtered noise for the street, layered synthetic voices for the crowd and the television), not recorded.
- Scenarios are scripted, so open-ended conversation is not covered.
- About 30 scenarios is a small sample. A metric such as "kept talking through hmm" rests on five events per pass. Read the counts.
- Content metrics depend on a speech recogniser reading the agent's voice, and it makes mistakes; the oracle results above show how often with one voice. A different agent voice may be read better or worse.
- "Replied in caller's language" cannot tell Hindi from Hinglish.
- A backchannel is scored as wrongly stopping the agent if the agent goes quiet for 700 ms around it. An agent that happened to finish its answer at that moment would be counted too.
- The local baselines are slow, 2.6 to 4.8 seconds from the end of the caller's turn to the first sound. A slow agent that decides too early often gets away with it, because the caller resumes before it has said anything and it drops the reply. So the false-interruption count understates how often these agents *decided* wrongly; it counts only what a caller would hear.
- The leaderboard so far compares configurations of one local pipeline on one laptop. It says nothing yet about any commercial platform.
- The commercial adapters are untested.

## Repository layout

```
scenarios/            the scripted calls, one YAML file each
prompts/              the instructions every agent is given
src/arena/            caller, engine, agents, metrics, scoring, report
tests/                metric validation first, then the rest
params.yaml           every setting
dvc.yaml, dvc.lock    the pipeline and the fingerprints of what it produced
results/              scores, leaderboard and validation results (recordings are in DVC)
web/                  the Next.js website; its data and audio are written by the report step
docs/                 a plain-HTML copy of the same results, no build needed
PLAN.md               the plan this was built from
COMMERCIAL.md         how to run the commercial adapters
STEPS.md              what each pipeline step does
WORKER.md, Dockerfile the worker that tests one agent on request
AWS.md                planned AWS setup and estimated cost (nothing deployed)
```
