"""Adapter for agents hosted on smallest.ai Atoms.

UNTESTED — written from public documentation on 2026-11-24, never run against
the live service. Expect to fix small things on the first real call.

Transport: the Atoms "Realtime Agent" WebSocket, JSON text messages, audio as
base64 inside JSON.

    1. POST https://api.smallest.ai/atoms/v1/conversation/register-call
       (Authorization: Bearer <API key>)
           {"agent_id": "...", "mode": "webcall",
            "input_audio_format": "pcm_16000", "output_audio_format": "pcm_16000"}
       ->  201 {"data": {"access_token": "wct_...", "expires_in": 30, ...}}
       The token is single-use and lasts 30 seconds.
    2. Open wss://api.smallest.ai/atoms/v1/agent/connect?token=<access_token>
    3. The server sends {"type": "session.created", "call_id", "output_audio_format", ...}.
    4. Caller audio goes up as {"type": "input_audio_buffer.append", "audio": "<base64>"};
       agent audio comes down as {"type": "output_audio.delta", "audio": "<base64>"}.
       PCM is signed 16-bit little-endian mono. The server does its own voice
       activity detection; audio is simply streamed continuously.
    5. {"type": "interruption"} means the caller interrupted: playback is flushed.
    6. Hang up with {"type": "session.close"}, then close the socket.

Docs used:
    https://docs.smallest.ai/atoms/api-reference/api-reference/realtime-agent/realtime-agent
    https://docs.smallest.ai/voice-agents/api-reference/realtime-agent/register-call
    https://docs.smallest.ai/voice-agents/platform/agent-sdk/audio-formats
    https://docs.smallest.ai/atoms/atoms-platform/integrate/web-socket-sdk

Unsure about:
    - The docs say what `interruption` means but not what a client must do
      with audio it has already received. Flushing is the obvious reading.
    - Whether `output_audio.delta` chunks that were already in flight when the
      interruption was sent can arrive after it. There is no sequence number
      to filter on, so such stragglers would be played.
    - Recommended chunk size and keep-alive are not documented. Audio is sent
      every 20 ms throughout, and the WebSocket library answers protocol pings.
    - The register-call reply is read as {"data": {"access_token": ...}}, as
      the reference describes it; a top-level access_token is accepted too.
    - A smallest.ai blog post shows a different, older endpoint
      (wss://atoms.smallest.ai/v1/agents/{id}/stream). It contradicts the
      current API reference and is not used.
"""

import asyncio
import json

import numpy as np

from arena.agents._network import (
    WebSocketAgent,
    b64_decode,
    b64_encode,
    encode_audio,
    http_json,
    open_websocket,
    parse_format,
)
from arena.audio import SR

REGISTER_URL = "https://api.smallest.ai/atoms/v1/conversation/register-call"
CONNECT_URL = "wss://api.smallest.ai/atoms/v1/agent/connect"
AUDIO_FORMAT = f"pcm_{SR}"


def register_call_body(agent_id: str, variables: dict | None = None) -> dict:
    """The request that mints a token for a 16 kHz PCM voice session."""
    body = {"agent_id": agent_id, "mode": "webcall",
            "input_audio_format": AUDIO_FORMAT, "output_audio_format": AUDIO_FORMAT}
    if variables:
        body["variables"] = variables
    return body


class SmallestAgent(WebSocketAgent):
    """agent_id    the Atoms agent to call (from the smallest.ai console)
    variables   optional per-call prompt variables
    """

    KEY_ENV = "SMALLEST_API_KEY"
    PLATFORM = "smallest.ai"

    def __init__(self, agent_id: str, variables: dict | None = None):
        super().__init__()
        self.agent_id = agent_id
        self.variables = variables
        self._reset()

    def _reset(self) -> None:
        self._ready = asyncio.Event()
        self._out_format = ("pcm", SR)

    async def connect(self) -> None:
        key = self._begin()
        self._reset()
        reply = await http_json("POST", REGISTER_URL, headers={"Authorization": f"Bearer {key}"},
                                body=register_call_body(self.agent_id, self.variables))
        token = (reply.get("data") or reply).get("access_token")
        if not token:
            raise RuntimeError(f"smallest.ai: the register-call response has no access_token: {reply}")
        self._ws = await open_websocket(f"{CONNECT_URL}?token={token}")
        self._start_receiving()
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=15)
        except TimeoutError:
            await self._hang_up()
            raise RuntimeError(f"smallest.ai: no session.created within 15 s; notes so far: {self.events}") from None

    def _on_message(self, message: str | bytes) -> dict | None:
        data = json.loads(message)
        kind = data.get("type")
        if kind == "output_audio.delta":
            encoding, rate = self._out_format
            self.buffer.push_bytes(b64_decode(data["audio"]), rate, encoding)
        elif kind == "interruption":
            self.flush("interruption")
        elif kind == "session.created":
            # Trust what the server says it will send over what we asked for.
            if data.get("output_audio_format"):
                self._out_format = parse_format(data["output_audio_format"])
            self.note("connected", call_id=data.get("call_id"), session_id=data.get("session_id"),
                      input_audio_format=data.get("input_audio_format"),
                      output_audio_format=data.get("output_audio_format"))
            self._ready.set()
        elif kind == "transcript":
            self.note("transcript", role=data.get("role"), text=data.get("text"))
        elif kind in ("agent_start_talking", "agent_stop_talking"):
            self.note(kind, buffered_ms=round(self.buffer.buffered_ms))
        elif kind == "error":
            self.note("error", code=data.get("code"), message=data.get("message"))
        elif kind == "session.closed":
            self.note("session_closed", reason=data.get("reason"))
        return None

    async def send_audio(self, frame: np.ndarray) -> None:
        await self._send(json.dumps({"type": "input_audio_buffer.append", "audio": b64_encode(encode_audio(frame))}))

    async def close(self) -> None:
        await self._hang_up({"type": "session.close"})
