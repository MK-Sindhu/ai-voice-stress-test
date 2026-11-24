"""Shared plumbing for agents that live on the network.

The engine asks for exactly one 20 ms frame of agent audio per tick and will
not wait for it. A network agent sends audio whenever it likes, in chunks of
any size and often at another sample rate. AudioBuffer sits between the two:
a background task pushes whatever arrives, the engine pops one frame per tick.

When a platform says the agent was interrupted, the adapter must call
buffer.clear(). Platforms often send speech faster than real time; without
the flush the benchmark would keep "hearing" audio the platform has already
thrown away and would record the agent as still talking.

Also here: base64 / mu-law / resampling helpers, small HTTP and WebSocket
helpers that import their client library only when used, and the two base
classes the platform adapters build on.

Resampling note: push_bytes resamples each chunk on its own, which leaves a
tiny discontinuity at chunk edges. It is inaudible to the metrics (they work
on 10 ms loudness), and the adapters ask every platform for 16 kHz so that
no resampling happens at all where the platform allows it.
"""

import asyncio
import base64
import contextlib
import json
import os
import time
from collections import deque

import numpy as np

from arena.agents.base import Agent
from arena.audio import FRAME, SR, resample, to_int16

# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def require_key(env_name: str, platform: str) -> str:
    """The API key from the environment, or a clear error naming the variable."""
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise RuntimeError(
            f"{platform}: the environment variable {env_name} is not set. "
            f"Set it to your {platform} API key (see COMMERCIAL.md); keys are never read from params.yaml."
        )
    return key


def parse_format(token: str) -> tuple[str, int]:
    """'pcm_16000' -> ('pcm', 16000); 'ulaw_8000' / 'mulaw_8000' -> ('ulaw', 8000)."""
    encoding, _, rate = token.strip().lower().rpartition("_")
    if encoding == "mulaw":
        encoding = "ulaw"
    if encoding not in ("pcm", "ulaw") or not rate.isdigit():
        raise ValueError(f"unsupported audio format {token!r} (expected e.g. pcm_16000 or ulaw_8000)")
    return encoding, int(rate)


def ulaw_decode(data: bytes) -> np.ndarray:
    """G.711 mu-law bytes -> int16 samples."""
    u = ~np.frombuffer(data, dtype=np.uint8)
    magnitude = (((u & 0x0F).astype(np.int32) << 3) + 0x84 << ((u >> 4) & 0x07)) - 0x84
    return np.where(u & 0x80, -magnitude, magnitude).astype(np.int16)


def ulaw_encode(pcm: np.ndarray) -> bytes:
    """int16 samples -> G.711 mu-law bytes."""
    x = pcm.astype(np.int32)
    sign = np.where(x < 0, 0x80, 0)
    x = np.minimum(np.abs(x), 32635) + 0x84
    exponent = np.floor(np.log2(x)).astype(np.int32) - 7
    mantissa = (x >> (exponent + 3)) & 0x0F
    return (~(sign | (exponent << 4) | mantissa) & 0xFF).astype(np.uint8).tobytes()


def decode_audio(data: bytes, rate: int = SR, encoding: str = "pcm") -> np.ndarray:
    """Platform audio bytes -> int16 samples at 16 kHz.

    'pcm' is signed 16-bit little-endian mono; 'ulaw' is G.711 mu-law. A
    trailing odd byte of PCM is dropped (AudioBuffer.push_bytes carries it
    over to the next chunk instead)."""
    if encoding == "ulaw":
        pcm = ulaw_decode(data)
    else:
        pcm = np.frombuffer(data[: len(data) // 2 * 2], dtype="<i2")
    if rate != SR and len(pcm):
        pcm = to_int16(resample(pcm, rate, SR))
    return pcm.astype(np.int16)


def encode_audio(frame: np.ndarray, rate: int = SR, encoding: str = "pcm") -> bytes:
    """A 16 kHz int16 frame -> platform audio bytes at `rate`."""
    pcm = np.asarray(frame, dtype=np.int16)
    if rate != SR:
        pcm = to_int16(resample(pcm, SR, rate))
    if encoding == "ulaw":
        return ulaw_encode(pcm)
    return pcm.astype("<i2").tobytes()


def b64_decode(text: str) -> bytes:
    return base64.b64decode(text)


def b64_encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# ---------------------------------------------------------------------------
# The receive buffer
# ---------------------------------------------------------------------------


class AudioBuffer:
    """Agent audio waiting to be handed to the engine, one frame per tick."""

    def __init__(self) -> None:
        self._chunks: deque[np.ndarray] = deque()
        self._samples = 0
        self._carry = b""  # an odd byte left over from a PCM chunk split mid-sample
        self._waited = False  # a short tail was held back on the previous tick

    @property
    def buffered_ms(self) -> float:
        return self._samples * 1000 / SR

    def push(self, pcm: np.ndarray) -> None:
        """Add int16 samples that are already at 16 kHz."""
        pcm = np.asarray(pcm, dtype=np.int16).reshape(-1)
        if len(pcm):
            self._chunks.append(pcm)
            self._samples += len(pcm)

    def push_bytes(self, data: bytes, rate: int = SR, encoding: str = "pcm") -> None:
        """Add raw platform audio of any length, sample rate and encoding."""
        if encoding == "pcm":
            data = self._carry + data
            whole = len(data) // 2 * 2
            data, self._carry = data[:whole], data[whole:]
        self.push(decode_audio(data, rate, encoding))

    def pop(self) -> np.ndarray:
        """The next 20 ms frame: always exactly FRAME int16 samples, never waits.

        With less than a full frame buffered it returns silence once (more
        audio is probably on its way) and on the next tick hands out the short
        tail padded with silence, so the end of an utterance is not lost."""
        out = np.zeros(FRAME, dtype=np.int16)
        if self._samples < FRAME and not (self._samples and self._waited):
            self._waited = self._samples > 0
            return out
        self._waited = False
        filled = 0
        while filled < FRAME and self._chunks:
            chunk = self._chunks[0]
            take = min(FRAME - filled, len(chunk))
            out[filled : filled + take] = chunk[:take]
            filled += take
            if take == len(chunk):
                self._chunks.popleft()
            else:
                self._chunks[0] = chunk[take:]
        self._samples -= filled
        return out

    def clear(self) -> float:
        """Throw away everything not yet played. Returns how many ms were dropped."""
        dropped = self.buffered_ms
        self._chunks.clear()
        self._samples = 0
        self._carry = b""
        self._waited = False
        return dropped


# ---------------------------------------------------------------------------
# Lazy network clients
# ---------------------------------------------------------------------------


async def http_json(method: str, url: str, *, headers: dict, body: dict | None = None,
                    params: dict | None = None, timeout: float = 20.0) -> dict:
    """One JSON request. Raises RuntimeError with the platform's reply on failure."""
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError("the commercial adapters need httpx: uv sync --extra commercial") from exc
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(method, url, headers=headers, json=body, params=params)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {url} failed with HTTP {response.status_code}: {response.text[:500]}")
    return response.json() if response.content else {}


async def open_websocket(url: str, **kwargs):
    """Open a WebSocket. The library answers protocol-level pings by itself."""
    try:
        from websockets.asyncio.client import connect
    except ImportError as exc:
        raise RuntimeError("the commercial adapters need websockets>=13: uv sync --extra commercial") from exc
    return await connect(url, max_size=16 * 1024 * 1024, **kwargs)


# ---------------------------------------------------------------------------
# Base classes
# ---------------------------------------------------------------------------


class NetworkAgent(Agent):
    """An agent reached over the network: a receive buffer, notes, background tasks."""

    KEY_ENV = ""  # environment variable holding the API key
    PLATFORM = ""  # name used in error messages

    def __init__(self) -> None:
        super().__init__()
        self.buffer = AudioBuffer()
        self._t0 = time.perf_counter()
        self._tasks: list[asyncio.Task] = []

    def _begin(self) -> str:
        """Start of connect(): check the key first, then reset per-call state."""
        key = require_key(self.KEY_ENV, self.PLATFORM)
        self.events = []  # a new list: the previous call's timeline keeps the old one
        self.buffer = AudioBuffer()
        self._tasks = []
        self._t0 = time.perf_counter()
        return key

    def note(self, kind: str, **fields) -> None:
        """Record something the platform told us. Saved, never scored."""
        self.events.append({"t": round(time.perf_counter() - self._t0, 3), "type": kind, **fields})

    def flush(self, reason: str) -> None:
        """The platform says playback must stop: drop everything not yet played."""
        self.note("interruption", reason=reason, dropped_ms=round(self.buffer.clear(), 1))

    async def receive_audio(self) -> np.ndarray:
        return self.buffer.pop()

    def _spawn(self, coro) -> None:
        self._tasks.append(asyncio.create_task(coro))

    async def _stop_tasks(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks = []


class WebSocketAgent(NetworkAgent):
    """A network agent whose call is one WebSocket.

    Subclasses open the socket in connect(), call _start_receiving(), and
    implement _on_message, which handles one incoming message and may return
    a JSON-able reply (for example the answer to a ping)."""

    def __init__(self) -> None:
        super().__init__()
        self._ws = None
        self._send_failed = False

    def _on_message(self, message: str | bytes) -> dict | None:
        raise NotImplementedError

    def _start_receiving(self) -> None:
        self._send_failed = False
        self._spawn(self._receive_loop())

    async def _receive_loop(self) -> None:
        try:
            async for message in self._ws:
                try:
                    reply = self._on_message(message)
                except Exception as exc:  # one bad message must not end the call
                    self.note("bad_message", error=repr(exc))
                    continue
                if reply is not None:
                    await self._send(json.dumps(reply))
            self.note("disconnected", code=getattr(self._ws, "close_code", None),
                      reason=getattr(self._ws, "close_reason", None))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.note("disconnected", error=repr(exc))

    async def _send(self, data: str | bytes) -> None:
        """Send without ever raising into the engine's clock. A dead socket is
        noted once; the rest of the call is then recorded as agent silence."""
        if self._ws is None or self._send_failed:
            return
        try:
            await self._ws.send(data)
        except Exception as exc:
            self._send_failed = True
            self.note("send_failed", error=repr(exc))

    async def _hang_up(self, farewell: dict | None = None) -> None:
        """Optionally send a last control message, then close everything."""
        if self._ws is not None:
            if farewell is not None:
                await self._send(json.dumps(farewell))
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._ws.close(), timeout=5)
        await self._stop_tasks()
        self._ws = None
