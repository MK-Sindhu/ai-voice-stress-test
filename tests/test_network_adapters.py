"""The commercial adapters, as far as they can be checked without a network.

Nothing here opens a connection or needs an API key. It covers the shared
receive buffer, the audio helpers, the missing-key errors and each adapter's
handling of the platform's messages (built by hand from the public docs).
"""

import asyncio
import base64
import json

import numpy as np
import pytest

from arena.agents._network import (
    AudioBuffer,
    b64_encode,
    decode_audio,
    encode_audio,
    parse_format,
    require_key,
    ulaw_decode,
    ulaw_encode,
)
from arena.agents.base import build_agent
from arena.agents.elevenlabs import ElevenLabsAgent
from arena.agents.retell import RetellAgent, sessions_url
from arena.agents.smallest import SmallestAgent, register_call_body
from arena.agents.vapi import VapiAgent, create_call_body
from arena.audio import FRAME, SR

KEYS = ["ELEVENLABS_API_KEY", "VAPI_API_KEY", "RETELL_API_KEY", "SMALLEST_API_KEY"]


def ramp(n: int, start: int = 1) -> np.ndarray:
    return np.arange(start, start + n, dtype=np.int16)


def sine(seconds: float, rate: int, hz: float = 440.0) -> np.ndarray:
    t = np.arange(int(rate * seconds)) / rate
    return (np.sin(2 * np.pi * hz * t) * 8000).astype(np.int16)


def drain(buffer: AudioBuffer, ticks: int) -> np.ndarray:
    frames = [buffer.pop() for _ in range(ticks)]
    assert all(f.shape == (FRAME,) and f.dtype == np.int16 for f in frames)
    return np.concatenate(frames)


# --- the shared buffer --------------------------------------------------------


def test_empty_buffer_gives_silence():
    frame = AudioBuffer().pop()
    assert frame.shape == (FRAME,) and frame.dtype == np.int16
    assert not frame.any()


def test_frames_come_out_in_order():
    buffer = AudioBuffer()
    buffer.push(ramp(3 * FRAME))
    assert np.array_equal(drain(buffer, 3), ramp(3 * FRAME))
    assert not buffer.pop().any()


def test_odd_sized_chunks_are_reframed():
    buffer = AudioBuffer()
    audio = ramp(1000)
    for start, end in [(0, 7), (7, 500), (500, 501), (501, 1000)]:
        buffer.push(audio[start:end])
    out = drain(buffer, 3)  # three full frames = 960 samples
    assert np.array_equal(out, audio[:960])
    assert buffer.buffered_ms == pytest.approx(40 * 1000 / SR)


def test_short_tail_waits_one_tick_then_is_padded():
    buffer = AudioBuffer()
    buffer.push(ramp(100))
    assert not buffer.pop().any()  # held back: more audio may be about to arrive
    tail = buffer.pop()
    assert np.array_equal(tail[:100], ramp(100)) and not tail[100:].any()
    assert buffer.buffered_ms == 0


def test_short_tail_is_joined_by_audio_that_arrives_in_time():
    buffer = AudioBuffer()
    buffer.push(ramp(100))
    assert not buffer.pop().any()
    buffer.push(ramp(220, start=101))
    assert np.array_equal(buffer.pop(), ramp(FRAME))  # no gap inserted


def test_flush_drops_everything():
    buffer = AudioBuffer()
    buffer.push(ramp(5 * FRAME))
    buffer.pop()
    assert buffer.clear() == pytest.approx(80.0)
    assert not drain(buffer, 3).any()
    buffer.push(ramp(FRAME))  # and it keeps working afterwards
    assert np.array_equal(buffer.pop(), ramp(FRAME))


def test_bytes_split_in_the_middle_of_a_sample():
    buffer = AudioBuffer()
    data = ramp(2 * FRAME).astype("<i2").tobytes()
    buffer.push_bytes(data[:333])
    buffer.push_bytes(data[333:])
    assert np.array_equal(drain(buffer, 2), ramp(2 * FRAME))


@pytest.mark.parametrize("rate", [8000, 24000, 44100, 48000])
def test_resampling_gives_the_right_length(rate):
    buffer = AudioBuffer()
    buffer.push_bytes(sine(1.0, rate).astype("<i2").tobytes(), rate)
    assert buffer.buffered_ms == pytest.approx(1000, abs=1)
    out = drain(buffer, 50)
    assert np.abs(out[SR // 4 : SR // 2]).max() > 6000  # still a tone, at about the same level


def test_decode_and_encode_change_rate():
    assert len(decode_audio(sine(0.5, 24000).tobytes(), 24000)) == SR // 2
    assert len(decode_audio(sine(0.5, 8000).tobytes(), 8000)) == SR // 2
    assert len(encode_audio(sine(0.02, SR), 8000)) == 160 * 2
    assert len(encode_audio(sine(0.02, SR), 48000)) == 960 * 2
    frame = sine(0.02, SR)
    assert np.array_equal(decode_audio(encode_audio(frame)), frame)


def test_ulaw_round_trip():
    pcm = sine(0.1, 8000)
    data = ulaw_encode(pcm)
    assert len(data) == len(pcm)
    back = ulaw_decode(data)
    assert np.abs(back.astype(int) - pcm.astype(int)).max() < 400  # mu-law is lossy, by a few percent
    # Known values of the G.711 table.
    assert ulaw_decode(bytes([0xFF, 0x7F, 0x00, 0x80])).tolist() == [0, 0, -32124, 32124]
    assert len(encode_audio(sine(0.02, SR), 8000, "ulaw")) == 160


def test_parse_format():
    assert parse_format("pcm_16000") == ("pcm", 16000)
    assert parse_format("pcm_44100") == ("pcm", 44100)
    assert parse_format("ulaw_8000") == ("ulaw", 8000)
    assert parse_format("mulaw_8000") == ("ulaw", 8000)
    with pytest.raises(ValueError):
        parse_format("opus_48000")


# --- keys -----------------------------------------------------------------------


@pytest.fixture
def no_keys(monkeypatch):
    for name in KEYS:
        monkeypatch.delenv(name, raising=False)


def test_require_key(monkeypatch):
    monkeypatch.setenv("SOME_KEY", "  abc  ")
    assert require_key("SOME_KEY", "Somewhere") == "abc"
    monkeypatch.setenv("SOME_KEY", "")
    with pytest.raises(RuntimeError, match="SOME_KEY"):
        require_key("SOME_KEY", "Somewhere")


@pytest.mark.parametrize(
    "config, env",
    [
        ({"type": "elevenlabs", "agent_id": "agent_x"}, "ELEVENLABS_API_KEY"),
        ({"type": "vapi", "assistant_id": "asst_x"}, "VAPI_API_KEY"),
        ({"type": "retell", "agent_id": "agent_x"}, "RETELL_API_KEY"),
        ({"type": "smallest", "agent_id": "agent_x"}, "SMALLEST_API_KEY"),
    ],
)
def test_connect_without_key_names_the_variable(no_keys, config, env):
    # Built the way the runner builds it, with the bookkeeping fields of params.yaml.
    agent = build_agent({**config, "label": "x", "untested": True, "repeats": 2})
    assert agent.frame_synchronous is False
    with pytest.raises(RuntimeError, match=env):
        asyncio.run(agent.connect())


def test_before_connect_the_agent_is_silent_and_close_is_safe(no_keys):
    async def go(agent):
        frame = await agent.receive_audio()
        await agent.close()
        return frame

    for agent in (ElevenLabsAgent("a"), VapiAgent("a"), RetellAgent("a"), SmallestAgent("a")):
        frame = asyncio.run(go(agent))
        assert frame.shape == (FRAME,) and not frame.any()


# --- ElevenLabs messages -------------------------------------------------------


def el_audio(event_id: int, pcm: np.ndarray) -> str:
    return json.dumps({"type": "audio", "audio_event": {"audio_base_64": b64_encode(pcm.astype("<i2").tobytes()),
                                                        "event_id": event_id}})


def el_metadata(out: str = "pcm_16000", inp: str = "pcm_16000") -> str:
    return json.dumps({"type": "conversation_initiation_metadata", "conversation_initiation_metadata_event": {
        "conversation_id": "conv_1", "agent_output_audio_format": out, "user_input_audio_format": inp}})


def test_elevenlabs_initiation_message():
    assert ElevenLabsAgent("a")._initiation_message() == {"type": "conversation_initiation_client_data"}
    override = {"agent": {"language": "hi"}}
    message = ElevenLabsAgent("a", config_override=override, dynamic_variables={"x": 1})._initiation_message()
    assert message["conversation_config_override"] == override and message["dynamic_variables"] == {"x": 1}


def test_elevenlabs_ping_is_answered_with_its_event_id():
    reply = ElevenLabsAgent("a")._on_message(json.dumps({"type": "ping", "ping_event": {"event_id": 7, "ping_ms": 50}}))
    assert reply == {"type": "pong", "event_id": 7}


def test_elevenlabs_audio_and_interruption():
    agent = ElevenLabsAgent("a")
    assert agent._on_message(el_metadata()) is None
    assert agent._ready.is_set()
    assert agent.events[-1]["type"] == "connected" and agent.events[-1]["conversation_id"] == "conv_1"

    agent._on_message(el_audio(1, ramp(4 * FRAME)))
    assert np.array_equal(agent.buffer.pop(), ramp(FRAME))

    agent._on_message(json.dumps({"type": "interruption", "interruption_event": {"event_id": 1}}))
    assert agent.buffer.buffered_ms == 0
    assert agent.events[-1]["type"] == "interruption" and agent.events[-1]["dropped_ms"] == 60.0

    agent._on_message(el_audio(1, ramp(FRAME)))  # a straggler from the interrupted reply
    assert agent.buffer.buffered_ms == 0
    agent._on_message(el_audio(2, ramp(FRAME)))  # the new reply
    assert np.array_equal(agent.buffer.pop(), ramp(FRAME))


def test_elevenlabs_follows_the_formats_in_the_metadata():
    agent = ElevenLabsAgent("a")
    agent._on_message(el_metadata(out="pcm_24000", inp="ulaw_8000"))
    agent._on_message(el_audio(1, sine(0.5, 24000)))
    assert agent.buffer.buffered_ms == pytest.approx(500, abs=1)

    sent = []

    async def capture(data):
        sent.append(json.loads(data))

    agent._send = capture
    asyncio.run(agent.send_audio(sine(0.02, SR)))
    assert len(base64.b64decode(sent[0]["user_audio_chunk"])) == 160  # 20 ms of 8 kHz mu-law


def test_elevenlabs_transcripts_become_notes():
    agent = ElevenLabsAgent("a")
    agent._on_message(json.dumps({"type": "user_transcript", "user_transcription_event": {"user_transcript": "hi"}}))
    agent._on_message(json.dumps({"type": "agent_response", "agent_response_event": {"agent_response": "hello"}}))
    agent._on_message(json.dumps({"type": "vad_score", "vad_score_event": {"vad_score": 0.9}}))  # ignored
    assert [(e["type"], e["text"]) for e in agent.events] == [("user_transcript", "hi"), ("agent_response", "hello")]
    assert all(isinstance(e["t"], float) for e in agent.events)


# --- Vapi messages ---------------------------------------------------------------


def test_vapi_create_call_body_asks_for_16k_pcm():
    assert create_call_body("asst_1") == {
        "assistantId": "asst_1",
        "transport": {"provider": "vapi.websocket",
                      "audioFormat": {"format": "pcm_s16le", "container": "raw", "sampleRate": 16000}},
    }


def test_vapi_binary_frames_are_audio_and_interruption_flushes():
    agent = VapiAgent("a")
    data = ramp(3 * FRAME).astype("<i2").tobytes()
    agent._on_message(data[:701])  # chunk boundaries need not fall on samples
    agent._on_message(data[701:])
    assert np.array_equal(agent.buffer.pop(), ramp(FRAME))
    agent._on_message(json.dumps({"type": "user-interrupted"}))
    assert agent.buffer.buffered_ms == 0 and agent.events[-1]["type"] == "interruption"


def test_vapi_text_messages_become_notes():
    agent = VapiAgent("a")
    for kind, text in [("partial", "h"), ("final", "hi")]:  # only final transcripts are kept
        agent._on_message(json.dumps({"type": "transcript", "role": "user", "transcriptType": kind,
                                      "transcript": text}))
    agent._on_message(json.dumps({"type": "speech-update", "role": "assistant", "status": "started"}))
    agent._on_message(json.dumps({"type": "something-new"}))
    agent._on_message(json.dumps({"type": "something-new"}))  # each unknown type is noted once
    assert [e["type"] for e in agent.events] == ["transcript", "speech_update", "message"]
    assert agent.events[0]["text"] == "hi"


def test_vapi_sends_raw_pcm():
    agent = VapiAgent("a")
    sent = []

    async def capture(data):
        sent.append(data)

    agent._send = capture
    asyncio.run(agent.send_audio(ramp(FRAME)))
    assert sent == [ramp(FRAME).astype("<i2").tobytes()]


# --- smallest.ai messages --------------------------------------------------------


def test_smallest_register_call_body_asks_for_16k_pcm():
    assert register_call_body("agent_1") == {
        "agent_id": "agent_1", "mode": "webcall",
        "input_audio_format": "pcm_16000", "output_audio_format": "pcm_16000",
    }
    assert register_call_body("agent_1", {"name": "Asha"})["variables"] == {"name": "Asha"}


def test_smallest_audio_and_interruption():
    agent = SmallestAgent("a")
    agent._on_message(json.dumps({"type": "session.created", "session_id": "s", "call_id": "c",
                                  "input_audio_format": "pcm_16000", "output_audio_format": "pcm_24000"}))
    assert agent._ready.is_set() and agent.events[-1]["call_id"] == "c"

    delta = {"type": "output_audio.delta", "audio": b64_encode(sine(0.3, 24000).astype("<i2").tobytes())}
    agent._on_message(json.dumps(delta))
    assert agent.buffer.buffered_ms == pytest.approx(300, abs=1)  # the server's stated rate wins

    agent._on_message(json.dumps({"type": "interruption"}))
    assert agent.buffer.buffered_ms == 0 and agent.events[-1]["type"] == "interruption"

    agent._on_message(json.dumps({"type": "transcript", "role": "assistant", "text": "namaste"}))
    agent._on_message(json.dumps({"type": "transcript.delta", "role": "assistant", "text": "na"}))  # ignored
    assert agent.events[-1] == {"t": agent.events[-1]["t"], "type": "transcript", "role": "assistant",
                                "text": "namaste"}


def test_smallest_sends_base64_pcm():
    agent = SmallestAgent("a")
    sent = []

    async def capture(data):
        sent.append(json.loads(data))

    agent._send = capture
    asyncio.run(agent.send_audio(ramp(FRAME)))
    assert sent[0]["type"] == "input_audio_buffer.append"
    assert base64.b64decode(sent[0]["audio"]) == ramp(FRAME).astype("<i2").tobytes()


# --- Retell ----------------------------------------------------------------------


def test_retell_urls_and_body():
    assert sessions_url("call_1") == "https://api.retellai.com/webrtc-proxy/call_1/v1/webrtc/sessions"
    assert sessions_url("call_1", "s1").endswith("/sessions/s1")
    assert RetellAgent("agent_1")._create_body() == {"agent_id": "agent_1"}
    assert RetellAgent("agent_1", agent_version=3)._create_body() == {"agent_id": "agent_1", "agent_version": 3}


def test_retell_control_messages():
    agent = RetellAgent("a")
    agent._on_control(json.dumps({"type": "status", "state": "connected"}))
    agent._on_control(json.dumps({"type": "pong", "ts": 1}))
    agent._on_control(b"\x00not json")
    assert [(e["type"], e["state"]) for e in agent.events] == [("status", "connected")]


def test_retell_audio_frame_conversion():
    av = pytest.importorskip("av")
    from arena.agents.retell import frame_to_pcm, make_resampler, pcm_to_frame

    frame = pcm_to_frame(ramp(FRAME), pts=640)
    assert (frame.samples, frame.sample_rate, frame.pts) == (FRAME, SR, 640)

    # What aiortc hands over: 20 ms frames of 48 kHz stereo.
    resampler = make_resampler()
    tone = sine(1.0, 48000)
    total = 0
    for start in range(0, len(tone), 960):
        stereo = np.repeat(tone[start : start + 960], 2).reshape(1, -1)
        incoming = av.AudioFrame.from_ndarray(stereo, format="s16", layout="stereo")
        incoming.sample_rate = 48000
        pcm = frame_to_pcm(resampler, incoming)
        assert pcm.dtype == np.int16
        total += len(pcm)
    assert abs(total - SR) <= FRAME  # one second in, one second out (less the resampler's delay)


def test_retell_caller_track():
    pytest.importorskip("aiortc")
    from arena.agents.retell import make_caller_track

    async def go():
        queue: asyncio.Queue = asyncio.Queue()
        queue.put_nowait(ramp(FRAME))
        track = make_caller_track(queue)
        first, second = await track.recv(), await track.recv()  # the second is the silence fallback
        return first, second

    first, second = asyncio.run(go())
    assert (first.samples, first.pts, second.pts) == (FRAME, 0, FRAME)
    assert not second.to_ndarray().any()
