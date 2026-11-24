# Running the benchmark against commercial platforms

Adapters exist for four hosted voice-agent platforms: ElevenLabs, Vapi, Retell AI and smallest.ai (Atoms).

**All four are UNTESTED.** They were written from each platform's public documentation on 2026-11-24 and have never
been run against the live services, because no API key was used while building this repo. Expect the first call on
each platform to need a small fix. Each adapter's docstring (`src/arena/agents/<platform>.py`) lists the doc pages it
was written from and the points that were unclear. Results stay marked `untested: true` until you have looked at a
few recordings and are satisfied the adapter behaves.

What is checked without a network (`uv run pytest tests/test_network_adapters.py -q`): the audio buffer, the
resampling, the handling of each platform's documented messages, and the error you get when a key is missing.

## Before you start

1. Install the network clients: `uv sync --extra commercial` (adds `websockets` and `httpx`).
   Retell additionally needs `aiortc`, see its section.
2. On each platform, create one agent with the same instructions as every other agent on the leaderboard:
   paste the full contents of `prompts/agent_system.md` as the agent's system prompt.
3. Keep the rest of the agent as close to the platform's defaults as you can, and write down what you chose
   (language model, voice, speech recogniser, turn-taking settings). The benchmark measures that whole configuration,
   not "the platform". Things that must be right:
   - **Languages.** The scenarios are in Indian English, Hindi and Hinglish, and the prompt asks for Hindi replies in
     Devanagari. Pick a speech recogniser and a voice that handle Hindi and English (a multilingual setting where the
     platform has one).
   - **First message / greeting.** Decide once whether the agent greets first, and use the same choice on every
     platform, or their numbers are not comparable.
   - **No tools, no call transfer, no "end call" function.** The benchmark's caller hangs up; an agent that ends the
     call itself leaves the rest of the scenario as silence.
   - **Interruptions enabled** (barge-in), since several scenarios measure it.
4. API keys go in environment variables only. Never put them in `params.yaml`.

## Cost and call time

The full scenario set is about 30 calls of 20 to 60 seconds each, so one pass is roughly 15 to 25 minutes of call
time per platform. With `repeats: 2` (the default below) that is two passes: roughly 30 to 50 minutes of call time
per platform. Failed or repeated runs add to it.

Free-tier allowances were **not verified** for any of the four platforms. Check each platform's current pricing page
for how many free minutes or credits you have, and whether language-model and voice usage are billed separately,
before running a full pass. To try an adapter cheaply first, set `repeats: 1`.

## Running one platform

After adding the agent to `params.yaml` (entries below, under `agents:`):

```
uv run arena run --agent <name>
uv run arena score --agent <name>
uv run arena report
```

After the first run, listen to two or three recordings and open a timeline: the adapter's notes are saved under
`agent_events` (connection details, the platform's transcripts, interruptions). If the agent channel is silent,
garbled or plays at the wrong speed, the adapter needs fixing before any number means anything.

---

## ElevenLabs

Transport: WebSocket (`wss://api.elevenlabs.io/v1/convai/conversation`), audio as base64 in JSON. The adapter asks
for a signed URL with your key, so the agent may be private.

Dashboard:
1. Create an agent (ElevenAgents, formerly Conversational AI) and paste `prompts/agent_system.md` as its system prompt.
2. In the agent's audio settings set both the user input format and the agent (TTS) output format to **PCM 16000 Hz**.
   The adapter reads the formats the server announces and converts if they differ, so this is recommended, not
   required. (Where exactly this setting sits in the dashboard was not verified.)
3. Copy the agent ID.
4. Create an API key that may use the Agents / Conversational AI endpoints.

```
export ELEVENLABS_API_KEY=...
```

```yaml
  elevenlabs:
    type: elevenlabs
    label: "ElevenLabs Agents"
    untested: true
    repeats: 2
    agent_id: "YOUR_AGENT_ID"
    # api_host: api.in.residency.elevenlabs.io   # only for data-residency accounts
```

```
uv run arena run --agent elevenlabs
uv run arena score --agent elevenlabs
uv run arena report
```

Interruption handling: ElevenLabs sends an `interruption` event; the adapter then discards audio it had received
but not yet played. This is the best-documented of the four.

## Vapi

Transport: Vapi's WebSocket transport. `POST https://api.vapi.ai/call` with `transport.provider: vapi.websocket`
returns a `websocketCallUrl`; raw 16 kHz 16-bit PCM flows both ways as binary frames.

Dashboard:
1. Create an assistant and paste `prompts/agent_system.md` as its system prompt.
2. Copy the assistant ID.
3. Copy your **private** API key (the public key cannot create calls).

```
export VAPI_API_KEY=...
```

```yaml
  vapi:
    type: vapi
    label: "Vapi"
    untested: true
    repeats: 2
    assistant_id: "YOUR_ASSISTANT_ID"
```

```
uv run arena run --agent vapi
uv run arena score --agent vapi
uv run arena report
```

**Known gap — check this before trusting barge-in numbers.** Vapi's documentation for this transport describes no
interruption or "clear audio" signal, and does not document the JSON messages it sends to the client. The adapter
guesses that a `user-interrupted` message may arrive and discards unplayed audio if it does. If Vapi sends audio
faster than real time and sends no such message, the recording will contain speech the platform had already
cancelled, and the benchmark will overstate how long the assistant kept talking after an interruption. To check:
open a timeline from a barge-in scenario and look at `peak_buffered_ms` in the `closed` note under `agent_events`.
If it is within a few hundred ms, audio arrives in real time and the numbers are sound. If it is seconds long and
there are no `interruption` notes, do not publish Vapi's barge-in results.

## Retell AI

Transport: WebRTC (Opus). Retell has no raw-audio WebSocket for web calls. The LiveKit-based web call (v2) was
deprecated in autumn 2026; the adapter uses the current path: `POST https://api.retellai.com/v3/create-web-call`,
then a standard WebRTC offer/answer exchange with Retell's signalling endpoint, as documented in Retell's
"native web call" guide.

Extra package (not in `pyproject.toml`): `aiortc`, a WebRTC implementation for Python. Version 1.15.0 was current
when the adapter was written.

```
uv pip install "aiortc>=1.15"
```

(`uv sync` removes packages that are not in the lock file, so either re-install it after syncing or add it to the
`commercial` extra in `pyproject.toml`.)

Dashboard:
1. Create an agent (single-prompt / Retell LLM) and paste `prompts/agent_system.md` as its prompt.
2. Copy the agent ID.
3. Copy your API key (a secret key, not the browser "public key").

```
export RETELL_API_KEY=...
```

```yaml
  retell:
    type: retell
    label: "Retell AI"
    untested: true
    repeats: 2
    agent_id: "YOUR_AGENT_ID"
```

```
uv run arena run --agent retell
uv run arena score --agent retell
uv run arena report
```

Notes:
- This adapter is the least certain of the four. Retell's guide gives examples for Swift, Kotlin, React Native and
  Flutter; using `aiortc` against the same endpoints should work but is not something Retell documents.
- There is no interruption event on this path and none is needed: WebRTC audio is real-time, so an interrupted
  agent simply goes quiet. For the same reason the timeline has no Retell transcripts, only call status.
- Web calls count toward your account's concurrency limit. The benchmark places one call at a time.

## smallest.ai (Atoms)

Transport: the Atoms Realtime Agent WebSocket (`wss://api.smallest.ai/atoms/v1/agent/connect`), audio as base64
in JSON. The adapter first calls `POST https://api.smallest.ai/atoms/v1/conversation/register-call` with your key,
asking for 16 kHz PCM in both directions, and connects with the short-lived token it returns.

Console:
1. Create an Atoms agent (single prompt) and paste `prompts/agent_system.md` as its prompt.
2. Copy the agent ID.
3. Create an API key.

```
export SMALLEST_API_KEY=...
```

```yaml
  smallest:
    type: smallest
    label: "smallest.ai Atoms"
    untested: true
    repeats: 2
    agent_id: "YOUR_AGENT_ID"
```

```
uv run arena run --agent smallest
uv run arena score --agent smallest
uv run arena report
```

Interruption handling: Atoms sends an `interruption` event and the adapter discards unplayed audio. The messages
carry no sequence numbers, so audio already on its way when the interruption was sent cannot be filtered out; if the
recordings show a short burst of speech just after an interruption, that is the cause.

---

## If a first run fails

- `... the environment variable X is not set`: export the key in the same shell you run `arena` from.
- `HTTP 401/403` in the error: wrong key, wrong kind of key (Vapi needs the private key, Retell the secret key),
  or the key lacks access to the agent.
- `HTTP 400/404`: wrong agent or assistant ID, or the request shape has changed since 2026-11-24. The error shows
  the platform's reply; compare it with the doc page listed at the top of the adapter.
- Connects but the agent channel is silent: look at `agent_events` in the timeline. A `disconnected` or `error` note
  says what the platform reported. No notes at all usually means the audio message names have changed.
- Agent audio is too fast, too slow or noise: the sample rate or encoding is not what the adapter assumed.
  The `connected` note records the formats the platform announced (ElevenLabs, smallest.ai).
