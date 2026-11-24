"""Adapter for assistants hosted on Vapi.

UNTESTED — written from public documentation on 2026-11-24, never run against
the live service. Expect to fix small things on the first real call.

Transport: Vapi's "WebSocket transport". Raw PCM in binary frames both ways.

    1. POST https://api.vapi.ai/call  (Authorization: Bearer <private key>)
           {"assistantId": "...",
            "transport": {"provider": "vapi.websocket",
                          "audioFormat": {"format": "pcm_s16le", "container": "raw", "sampleRate": 16000}}}
       ->  {"id": "...", "transport": {"websocketCallUrl": "wss://api.vapi.ai/<callId>/transport"}, ...}
    2. Open websocketCallUrl. Binary frames are audio (16-bit little-endian
       mono at the requested rate) in both directions; text frames are JSON
       control messages.
    3. Hang up by sending {"type": "end-call"} as text, then closing.

IMPORTANT GAP — interruption. The WebSocket transport page documents no
"clear" or interruption signal and does not document the JSON messages Vapi
sends to the client at all (only that there are some). What this adapter does
about it is a GUESS:
    - if a text frame with type "user-interrupted" arrives (that is the name
      of Vapi's interruption message on its other client channels, and it is
      in the assistant's `clientMessages` list), the receive buffer is flushed;
    - `speech-update` and final `transcript` messages are saved as notes.
If Vapi sends audio in real time the missing signal does not matter: an
interrupted assistant simply stops sending. If Vapi sends audio faster than
real time and never sends "user-interrupted" on this channel, the benchmark
will hear the buffered remainder and OVERSTATE how long the assistant kept
talking after a barge-in. Check on the first run: the `closed` note at the
end of each call records the highest buffer level seen (`peak_buffered_ms`),
and the message notes carry the level at that moment (`buffered_ms`). If the
peak stays within a few hundred ms, audio is real-time.

Docs used:
    https://docs.vapi.ai/calls/websocket-transport
    https://docs.vapi.ai/api-reference/calls/create
    https://docs.vapi.ai/calls/call-features   (live call control; not used)
    https://docs.vapi.ai/server-url/events     (message names, for the guess above)

Also unsure about:
    - Whether the JSON messages on this socket have the same shape as Vapi's
      client messages elsewhere ({"type": "transcript", "role", "transcriptType",
      "transcript"}, {"type": "speech-update", "status", "role"}). Unknown
      types are noted by name only and otherwise ignored.
    - Keep-alive: none is documented. Audio is sent every 20 ms throughout.
    - The create-call response status is "queued"; it is assumed the socket
      can be opened straight away.
"""

import json

import numpy as np

from arena.agents._network import WebSocketAgent, encode_audio, http_json, open_websocket
from arena.audio import SR

API_URL = "https://api.vapi.ai/call"


def create_call_body(assistant_id: str) -> dict:
    """The request that starts a WebSocket call carrying 16 kHz raw PCM."""
    return {
        "assistantId": assistant_id,
        "transport": {
            "provider": "vapi.websocket",
            "audioFormat": {"format": "pcm_s16le", "container": "raw", "sampleRate": SR},
        },
    }


class VapiAgent(WebSocketAgent):
    """assistant_id   the assistant to call (from the Vapi dashboard)"""

    KEY_ENV = "VAPI_API_KEY"
    PLATFORM = "Vapi"

    def __init__(self, assistant_id: str):
        super().__init__()
        self.assistant_id = assistant_id
        self._seen_types: set[str] = set()
        self._peak_ms = 0.0  # the most agent audio ever waiting to be played

    async def connect(self) -> None:
        key = self._begin()
        self._seen_types = set()
        self._peak_ms = 0.0
        call = await http_json("POST", API_URL, headers={"Authorization": f"Bearer {key}"},
                               body=create_call_body(self.assistant_id))
        url = (call.get("transport") or {}).get("websocketCallUrl")
        if not url:
            raise RuntimeError(f"Vapi: the create-call response has no transport.websocketCallUrl: {call}")
        self._ws = await open_websocket(url)
        self.note("connected", call_id=call.get("id"))
        self._start_receiving()

    def _on_message(self, message: str | bytes) -> dict | None:
        if isinstance(message, bytes):
            self.buffer.push_bytes(message, SR)
            self._peak_ms = max(self._peak_ms, self.buffer.buffered_ms)
            return None
        # Everything below is a guess at an undocumented schema; see the module docstring.
        data = json.loads(message)
        kind = str(data.get("type"))
        level = round(self.buffer.buffered_ms)
        if kind == "user-interrupted":
            self.flush("user-interrupted")
        elif kind == "speech-update":
            self.note("speech_update", role=data.get("role"), status=data.get("status"), buffered_ms=level)
        elif kind == "transcript":
            if data.get("transcriptType", "final") == "final":
                self.note("transcript", role=data.get("role"), text=data.get("transcript"), buffered_ms=level)
        elif kind not in self._seen_types:
            self.note("message", message_type=kind, buffered_ms=level)  # first sighting of each other type
        self._seen_types.add(kind)
        return None

    async def send_audio(self, frame: np.ndarray) -> None:
        await self._send(encode_audio(frame))

    async def close(self) -> None:
        if self._ws is not None:
            self.note("closed", peak_buffered_ms=round(self._peak_ms))
        await self._hang_up({"type": "end-call"})
