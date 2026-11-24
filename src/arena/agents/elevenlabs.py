"""Adapter for agents hosted on ElevenLabs (ElevenAgents / Conversational AI).

UNTESTED — written from public documentation on 2026-11-24, never run against
the live service. Expect to fix small things on the first real call.

Transport: one WebSocket, JSON text messages, audio as base64 inside JSON.

    1. GET https://api.elevenlabs.io/v1/convai/conversation/get-signed-url?agent_id=...
       with header `xi-api-key`  ->  {"signed_url": "wss://...&token=..."}
    2. Open the signed URL and send {"type": "conversation_initiation_client_data", ...}.
    3. The server sends `conversation_initiation_metadata` naming the audio
       formats for this call (agent_output_audio_format, user_input_audio_format).
    4. Caller audio goes up as {"user_audio_chunk": "<base64>"}; agent audio
       comes down as {"type": "audio", "audio_event": {"audio_base_64", "event_id"}}.
    5. {"type": "ping"} must be answered with {"type": "pong", "event_id": ...}.
    6. {"type": "interruption", "interruption_event": {"event_id": N}} means the
       caller barged in: playback is flushed and audio events with
       event_id <= N that arrive later are dropped (as the official SDK does).
    7. Hanging up is closing the socket.

Audio formats are a property of the agent, not of the call: they are set in
the agent's settings (asr.user_input_audio_format, tts.agent_output_audio_format)
and cannot be overridden per conversation. The adapter reads them from the
metadata event and converts both ways, so any pcm_* rate or ulaw_8000 works,
but setting both to PCM 16000 Hz in the dashboard avoids resampling.

Docs used:
    https://elevenlabs.io/docs/eleven-agents/api-reference/eleven-agents/websocket
    https://elevenlabs.io/docs/eleven-agents/libraries/web-sockets
    https://elevenlabs.io/docs/eleven-agents/customization/events/client-events
    https://elevenlabs.io/docs/api-reference/conversations/get-signed-url
    https://github.com/elevenlabs/elevenlabs-python (src/elevenlabs/conversational_ai/conversation.py)

Unsure about:
    - The signed URL is always requested, also for public agents. The docs
      describe it for agents that require authorization; it is assumed to work
      for any agent the key owns.
    - How long a signed URL stays valid is not stated; it is used at once.
    - Whether the server expects the pong at once or after `ping_ms`. The
      official Python SDK answers at once, so this does too.
    - No explicit "end conversation" message is documented; the socket is closed.
    - Audio is sent every 20 ms. The SDK suggests 250 ms chunks but nothing
      in the docs forbids smaller ones.
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


class ElevenLabsAgent(WebSocketAgent):
    """agent_id          the agent to call (from the ElevenLabs dashboard)
    api_host          API host; change it for a data-residency account,
                      e.g. api.in.residency.elevenlabs.io
    config_override   optional `conversation_config_override` sent at the start
                      of the call (the agent must allow overrides in its settings)
    dynamic_variables optional `dynamic_variables` for the agent's prompt
    """

    KEY_ENV = "ELEVENLABS_API_KEY"
    PLATFORM = "ElevenLabs"

    def __init__(self, agent_id: str, api_host: str = "api.elevenlabs.io",
                 config_override: dict | None = None, dynamic_variables: dict | None = None):
        super().__init__()
        self.agent_id = agent_id
        self.api_host = api_host
        self.config_override = config_override
        self.dynamic_variables = dynamic_variables
        self._reset()

    def _reset(self) -> None:
        self._ready = asyncio.Event()
        self._last_interrupt_id = 0
        # Until the metadata event says otherwise.
        self._in_format = ("pcm", SR)  # what we send
        self._out_format = ("pcm", SR)  # what the agent sends

    def _initiation_message(self) -> dict:
        message: dict = {"type": "conversation_initiation_client_data"}
        if self.config_override:
            message["conversation_config_override"] = self.config_override
        if self.dynamic_variables:
            message["dynamic_variables"] = self.dynamic_variables
        return message

    async def connect(self) -> None:
        key = self._begin()
        self._reset()
        signed = await http_json(
            "GET", f"https://{self.api_host}/v1/convai/conversation/get-signed-url",
            headers={"xi-api-key": key}, params={"agent_id": self.agent_id},
        )
        self._ws = await open_websocket(signed["signed_url"])
        self._start_receiving()
        await self._send(json.dumps(self._initiation_message()))
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=15)
        except TimeoutError:
            await self._hang_up()
            raise RuntimeError(
                f"ElevenLabs: no conversation_initiation_metadata within 15 s; notes so far: {self.events}"
            ) from None

    def _on_message(self, message: str | bytes) -> dict | None:
        data = json.loads(message)
        kind = data.get("type")
        if kind == "audio":
            event = data["audio_event"]
            # Audio that belongs to a reply the caller has already interrupted.
            if int(event.get("event_id", 0)) <= self._last_interrupt_id:
                return None
            encoding, rate = self._out_format
            self.buffer.push_bytes(b64_decode(event["audio_base_64"]), rate, encoding)
        elif kind == "interruption":
            event_id = int(data.get("interruption_event", {}).get("event_id", 0))
            self._last_interrupt_id = max(self._last_interrupt_id, event_id)
            self.flush("interruption")
        elif kind == "ping":
            return {"type": "pong", "event_id": data["ping_event"]["event_id"]}
        elif kind == "conversation_initiation_metadata":
            meta = data["conversation_initiation_metadata_event"]
            self._out_format = parse_format(meta.get("agent_output_audio_format", "pcm_16000"))
            self._in_format = parse_format(meta.get("user_input_audio_format", "pcm_16000"))
            self.note("connected", conversation_id=meta.get("conversation_id"),
                      agent_output_audio_format=meta.get("agent_output_audio_format"),
                      user_input_audio_format=meta.get("user_input_audio_format"))
            self._ready.set()
        elif kind == "user_transcript":
            self.note("user_transcript", text=data["user_transcription_event"]["user_transcript"])
        elif kind == "agent_response":
            self.note("agent_response", text=data["agent_response_event"]["agent_response"])
        elif kind == "agent_response_correction":
            event = data["agent_response_correction_event"]
            self.note("agent_response_correction", text=event.get("corrected_agent_response"))
        elif kind in ("queue_status", "guardrail_triggered", "client_tool_call"):
            # Worth seeing in the timeline: each of these can explain a silent agent.
            self.note(kind, detail={k: v for k, v in data.items() if k != "type"})
        return None

    async def send_audio(self, frame: np.ndarray) -> None:
        encoding, rate = self._in_format
        await self._send(json.dumps({"user_audio_chunk": b64_encode(encode_audio(frame, rate, encoding))}))

    async def close(self) -> None:
        await self._hang_up()
