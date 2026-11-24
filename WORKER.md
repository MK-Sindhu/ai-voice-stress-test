# The job worker

The worker runs one test job: it takes a description of an agent, places the calls, scores them and writes a results page into one folder. It is the piece that will sit behind a "test my agent" form on the website.

**Status.** The worker runs locally and in a container, and has been tried with the fake agent. It has not been run against any commercial platform, because their adapters are still untested (see [COMMERCIAL.md](COMMERCIAL.md)). Nothing has been created in AWS, and the website has no form yet.

## What a job is

A small JSON document:

```json
{
  "job_id": "a1b2c3",
  "agent": {"type": "elevenlabs", "agent_id": "YOUR_AGENT_ID", "label": "My support agent"},
  "scenarios": ["scenarios/barge_in_*.yaml"],
  "repeats": 1
}
```

| Field | Meaning |
|---|---|
| `job_id` | A name for the job: letters, digits, `-` and `_` |
| `agent.type` | `elevenlabs`, `vapi`, `retell` or `smallest` |
| `agent.*` | The settings that platform's adapter takes; see its section in [COMMERCIAL.md](COMMERCIAL.md) |
| `scenarios` | Optional. Which scenario files to run. Default: all 30 |
| `repeats` | Optional. Passes over the scenarios, 1 to 3. Default: 1 |

**API keys never go in the job.** Each adapter reads its key from an environment variable, named in COMMERCIAL.md. A job containing a field that looks like a key, secret or token is refused. The worker does not write the environment to any file.

## What it produces

| File | Contents |
|---|---|
| `status.json` | `running`, then `done` or `failed` with the reason. A waiting web page reads this |
| `runs/` | The recording and timeline of every call |
| `score.json` | Every measurement |
| `summary.json` | The headline numbers |
| `index.html`, `audio/` | The results page: summary table, results by scenario, every failure with audio |

A job that cannot run (bad description, platform refuses the connection) ends as `failed` in `status.json`; the command exits with code 1.

## Run a job locally

```
uv run arena job --spec job.json --out out/
open out/index.html
```

To try it without a platform account, use the fake agent, which replies with a tone at a fixed delay:

```
echo '{"job_id": "try1", "agent": {"type": "fake", "response_delay_ms": 800},
       "scenarios": ["scenarios/barge_in_replacement_en.yaml"]}' > job.json
uv run arena job --spec job.json --out out/ --allow-test-agents
```

## Run a job in the container

The image holds the code, the scenarios, the caller's rendered lines, the noise files and the speech recogniser. It does not hold the speech synthesis model or the local baseline agents, and it needs no GPU.

```
uv run dvc pull                       # the rendered caller audio must be under data/
docker build -t arena-worker --build-arg ARENA_VERSION=$(git rev-parse --short HEAD) .

docker run --rm -v "$PWD/out:/out" \
  -e ARENA_JOB_SPEC="$(cat job.json)" \
  -e ELEVENLABS_API_KEY \
  arena-worker
```

| Environment variable | Purpose |
|---|---|
| `ARENA_JOB_SPEC` | The job, when no `--spec` file is given |
| The platform's key variable | The API key for the agent under test |
| `ARENA_WORKER_LOCATION` | Optional. Where the worker runs, for example `AWS Mumbai`. Printed on the results page, because response delay includes the network time from there to the agent |
| `ARENA_COMPUTE_TYPE` | Set to `int8` in the image, the fast setting for transcription without a GPU |

After changing a caller line, re-render (`uv run dvc repro check_audio`) and rebuild the image; the worker cannot render speech itself.

## How a result differs from the leaderboard

- The leaderboard runs each agent twice; a job runs once by default.
- The container transcribes with `int8` arithmetic on a CPU, the leaderboard with the laptop's GPU. Transcripts can differ slightly, which can change a content check.
- Response delay includes the network time between the worker and the platform.

## Still to build

1. **One working platform adapter**, proven with a real key. Everything below depends on it.
2. **Queue and storage glue.** Take a job from a queue (Amazon SQS), upload the output folder (Amazon S3), delete the key.
3. **Compute that starts on demand.** An ECS Fargate task per job, or AWS Batch if a GPU is wanted.
4. **The form.** A page and a small API function on the website that create the job, and a status page that polls `status.json`.
5. **Limits.** An access code or sign-in, and a cap on jobs per person, so the worker cannot be flooded.
