"""Adapter for agents hosted on Retell AI.

UNTESTED — written from public documentation on 2026-11-24, never run against
the live service. Expect to fix things on the first real call; of the four
commercial adapters this one has the most moving parts.

NEEDS AN EXTRA PACKAGE that is not in pyproject.toml: `aiortc` (1.15.0 was
current when this was written; it needs Python >= 3.10 and brings `av`).
It is imported only inside connect().

Transport: WebRTC (Opus audio). Retell has no raw-audio WebSocket for web
calls. NOTE: Retell web calls used to run on LiveKit (create-web-call v2 plus
a LiveKit room token). That path was deprecated in autumn 2026; the current
v3 endpoint returns `transport: "gateway"` and is joined with plain WebRTC
and a small HTTP signalling exchange, documented for native apps. This
adapter follows that "native web call" guide, so `livekit` is not needed.

    1. POST https://api.retellai.com/v3/create-web-call  (Authorization: Bearer <API key>)
           {"agent_id": "..."}
       ->  201 {"call_id", "access_token", "ice_servers": [...], "transport": "gateway", "expires_at"}
       The client must connect within 5 minutes.
    2. Build a peer connection with those ICE servers, add one audio track
       (the caller's voice) and a data channel named "control", make an offer.
    3. POST https://api.retellai.com/webrtc-proxy/{call_id}/v1/webrtc/sessions
       (Authorization: Bearer <access_token>)   {"identity": "client", "sdp": "<offer>"}
       ->  201 {"session_id", "sdp": "<answer>"}
       The connection must reach "connected" within 15 seconds.
    4. Agent audio arrives as the remote audio track.
    5. Hang up: send {"type": "hangup"} on the control channel, then
       DELETE .../sessions/{session_id} with the same bearer token, then
       close the peer connection.

Interruption: there is NO clear / interruption event on this path, and none
is needed. WebRTC media is real-time: when the caller barges in, Retell stops
sending speech and the track goes quiet. Nothing is buffered ahead here beyond
the network jitter buffer, so there is nothing to flush. (Retell's `update`,
`agent_start_talking` and `agent_stop_talking` events are not delivered on the
gateway transport; Retell staff confirmed this on their community forum in
September 2026.) The only control messages are call status, noted as events.

Docs used:
    https://docs.retellai.com/api-references/create-web-call
    https://docs.retellai.com/deploy/native-web-call
    https://docs.retellai.com/deprecation-notice/2026/09-30_create_web_call_v2
    https://community.retellai.com/t/3654   (staff reply on missing gateway events)

Unsure about:
    - aiortc against Retell's media server: the guide lists Swift, Kotlin,
      React Native and Flutter WebRTC libraries, not aiortc. Codec negotiation
      (Opus) and ICE should be standard, but this is the likeliest place for
      a first-run failure.
    - aiortc gathers all ICE candidates before the offer is posted (no trickle
      ICE). The guide allows this ("wait about 1 second for ICE gathering").
    - The caller's audio is handed to aiortc as 16 kHz mono frames and aiortc's
      Opus encoder resamples to 48 kHz itself.
    - No keep-alive is sent on the control channel. The guide documents an
      optional ping/pong there but does not require it.
    - The guide tells phone apps to enable echo cancellation. Not relevant
      here: the agent's audio is never played into the caller's track.
"""

import asyncio
import contextlib
import json
from fractions import Fraction

import numpy as np

from arena.agents._network import NetworkAgent, http_json
from arena.audio import FRAME, SR

API = "https://api.retellai.com"
CREATE_URL = f"{API}/v3/create-web-call"
CONNECT_TIMEOUT_S = 15.0


def sessions_url(call_id: str, session_id: str | None = None) -> str:
    """The signalling endpoint for a call, or for one session of it."""
    url = f"{API}/webrtc-proxy/{call_id}/v1/webrtc/sessions"
    return url if session_id is None else f"{url}/{session_id}"


def pcm_to_frame(pcm: np.ndarray, pts: int):
    """16 kHz int16 samples -> the audio frame type aiortc sends."""
    import av

    frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(pcm, dtype=np.int16).reshape(1, -1),
                                       format="s16", layout="mono")
    frame.sample_rate = SR
    frame.pts = pts
    frame.time_base = Fraction(1, SR)
    return frame


def make_resampler():
    """Turns whatever aiortc decodes (48 kHz stereo) into 16 kHz mono. It keeps
    state between frames, so there are no seams at frame edges."""
    import av

    return av.AudioResampler(format="s16", layout="mono", rate=SR)


def frame_to_pcm(resampler, frame) -> np.ndarray:
    """A received audio frame -> 16 kHz int16 samples (possibly none yet)."""
    parts = [out.to_ndarray().reshape(-1) for out in resampler.resample(frame)]
    return np.concatenate(parts).astype(np.int16) if parts else np.zeros(0, dtype=np.int16)


def make_caller_track(queue: asyncio.Queue):
    """The outgoing audio track. aiortc pulls frames from it; it hands over the
    caller frames the engine queued, at the engine's pace. If the engine has
    produced nothing for half a second it sends silence so the stream stays alive."""
    from aiortc import MediaStreamTrack

    class CallerTrack(MediaStreamTrack):
        kind = "audio"

        def __init__(self) -> None:
            super().__init__()
            self._pts = 0

        async def recv(self):
            try:
                pcm = await asyncio.wait_for(queue.get(), timeout=0.5)
            except TimeoutError:
                pcm = np.zeros(FRAME, dtype=np.int16)
            frame = pcm_to_frame(pcm, self._pts)
            self._pts += len(pcm)
            return frame

    return CallerTrack()


class RetellAgent(NetworkAgent):
    """agent_id                      the agent to call (from the Retell dashboard)
    agent_version                 optional version number or tag
    retell_llm_dynamic_variables  optional per-call prompt variables (strings)
    """

    KEY_ENV = "RETELL_API_KEY"
    PLATFORM = "Retell AI"

    def __init__(self, agent_id: str, agent_version: int | str | None = None,
                 retell_llm_dynamic_variables: dict | None = None):
        super().__init__()
        self.agent_id = agent_id
        self.agent_version = agent_version
        self.dynamic_variables = retell_llm_dynamic_variables
        self._pc = None
        self._control = None
        self._outgoing: asyncio.Queue | None = None
        self._call_id: str | None = None
        self._session_id: str | None = None
        self._token: str | None = None

    def _create_body(self) -> dict:
        body: dict = {"agent_id": self.agent_id}
        if self.agent_version is not None:
            body["agent_version"] = self.agent_version
        if self.dynamic_variables:
            body["retell_llm_dynamic_variables"] = self.dynamic_variables
        return body

    async def connect(self) -> None:
        key = self._begin()
        try:
            from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
        except ImportError as exc:
            raise RuntimeError(
                "Retell AI: the adapter needs the `aiortc` package (WebRTC), which is not a project "
                "dependency. Install it with: uv pip install 'aiortc>=1.15'"
            ) from exc

        call = await http_json("POST", CREATE_URL, headers={"Authorization": f"Bearer {key}"},
                               body=self._create_body())
        self._call_id, self._token = call["call_id"], call["access_token"]
        self._session_id = None

        servers = [
            RTCIceServer(urls=s["urls"], username=s.get("username"), credential=s.get("credential"))
            for s in call.get("ice_servers", [])
        ]
        pc = self._pc = RTCPeerConnection(RTCConfiguration(iceServers=servers))
        self._outgoing = asyncio.Queue(maxsize=10)  # at most 200 ms of caller audio waiting
        pc.addTrack(make_caller_track(self._outgoing))
        self._control = pc.createDataChannel("control")  # must exist before the offer is made
        self._control.on("message", self._on_control)
        pc.on("track", self._on_track)

        try:
            # aiortc finishes gathering ICE candidates inside setLocalDescription,
            # so the offer that is posted already contains them.
            await pc.setLocalDescription(await pc.createOffer())
            answer = await http_json(
                "POST", sessions_url(self._call_id), headers={"Authorization": f"Bearer {self._token}"},
                body={"identity": "client", "sdp": pc.localDescription.sdp},
            )
            self._session_id = answer["session_id"]
            await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type="answer"))

            waited = 0.0
            while pc.connectionState != "connected":
                if pc.connectionState in ("failed", "closed") or waited >= CONNECT_TIMEOUT_S:
                    raise RuntimeError(f"Retell AI: WebRTC did not connect (state {pc.connectionState!r})")
                await asyncio.sleep(0.05)
                waited += 0.05
        except BaseException:
            await self.close()
            raise
        self.note("connected", call_id=self._call_id, session_id=self._session_id)

    def _on_track(self, track) -> None:
        if track.kind == "audio":
            self._spawn(self._read_track(track))

    async def _read_track(self, track) -> None:
        """Move the agent's audio from the WebRTC track into the buffer."""
        resampler = make_resampler()
        try:
            while True:
                self.buffer.push(frame_to_pcm(resampler, await track.recv()))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # aiortc raises MediaStreamError when the track ends
            self.note("track_ended", error=type(exc).__name__)

    def _on_control(self, message) -> None:
        """Call status from Retell: connected, ended, replaced. Pongs are ignored."""
        try:
            data = json.loads(message)
        except (TypeError, ValueError):
            return
        if data.get("type") == "status":
            self.note("status", state=data.get("state"))

    async def send_audio(self, frame: np.ndarray) -> None:
        if self._outgoing is None:
            return
        if self._outgoing.full():  # the sender has fallen behind: drop the oldest frame
            with contextlib.suppress(asyncio.QueueEmpty):
                self._outgoing.get_nowait()
        self._outgoing.put_nowait(np.asarray(frame, dtype=np.int16))

    async def close(self) -> None:
        if self._control is not None and self._control.readyState == "open":
            with contextlib.suppress(Exception):
                self._control.send(json.dumps({"type": "hangup"}))
        if self._session_id is not None:
            with contextlib.suppress(Exception):
                await http_json("DELETE", sessions_url(self._call_id, self._session_id),
                                headers={"Authorization": f"Bearer {self._token}"}, timeout=5)
        await self._stop_tasks()
        if self._pc is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._pc.close(), timeout=5)
        self._pc = self._control = self._outgoing = None
        self._session_id = None
