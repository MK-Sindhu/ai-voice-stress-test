"""The adapter interface every agent under test implements.

Four methods are enough to plug in any voice agent:

    connect()         open the call
    send_audio(f)     hand the agent 20 ms of caller audio (320 int16 samples, 16 kHz)
    receive_audio()   return the agent's audio for the same 20 ms
    close()           hang up

The engine calls send_audio and then receive_audio once per tick, every 20 ms.
receive_audio must not wait: if the agent has nothing to say right now, it
returns silence. Adapters for network agents keep a small buffer of received
audio and hand it out one frame per tick.
"""

import importlib

import numpy as np

from arena.audio import FRAME


class Agent:
    # True only for agents whose behaviour depends on frame counts alone, so
    # they can be driven faster than real time. Real agents leave this False.
    frame_synchronous = False

    def __init__(self) -> None:
        # Optional notes from the agent (what it heard, what it said, when it
        # decided to reply). Saved in the timeline; never used for scoring.
        self.events: list[dict] = []

    def prepare(self, scenario: dict, context: dict) -> None:
        """Called before each call with the scenario about to be run. Real
        agents ignore it; the calibration agents use it."""

    def observe(self, event: dict) -> None:
        """Called with each caller event as it happens. Real agents ignore it:
        an agent under test only ever gets the caller's audio. Only the oracle
        calibration agent uses this side channel."""

    async def connect(self) -> None:
        pass

    async def send_audio(self, frame: np.ndarray) -> None:
        raise NotImplementedError

    async def receive_audio(self) -> np.ndarray:
        raise NotImplementedError

    async def close(self) -> None:
        pass

    @staticmethod
    def silence() -> np.ndarray:
        return np.zeros(FRAME, dtype=np.int16)


# Agent type (the `type` field in params.yaml) -> "module:Class".
AGENT_TYPES = {
    "fake": "arena.agents.fake:FakeAgent",
    "oracle": "arena.agents.fake:OracleAgent",
    "local": "arena.agents.local:LocalAgent",
    "elevenlabs": "arena.agents.elevenlabs:ElevenLabsAgent",
    "vapi": "arena.agents.vapi:VapiAgent",
    "retell": "arena.agents.retell:RetellAgent",
    "smallest": "arena.agents.smallest:SmallestAgent",
}


def build_agent(config: dict) -> Agent:
    """Create an agent from its params.yaml entry."""
    config = dict(config)
    kind = config.pop("type")
    for key in ("label", "clock", "repeats", "calibration", "untested", "tone_only"):
        config.pop(key, None)
    module_name, class_name = AGENT_TYPES[kind].split(":")
    cls = getattr(importlib.import_module(module_name), class_name)
    return cls(**config)
