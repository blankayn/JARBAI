from jarbai.brain.llm import parse_response
from jarbai.brain.memory import Memory
from jarbai.brain.prompts import build_system_prompt
from jarbai.brain.router import Router
from jarbai.skills import get_skills


class FakeLLM:
    def __init__(self, raw):
        self.raw = raw

    def chat(self, messages):
        return self.raw


def test_parse_plain_json():
    assert parse_response('{"skill": "chat", "text": "Hello"}') == {"skill": "chat", "text": "Hello"}


def test_parse_fenced_json():
    raw = '```json\n{"skill": "chat", "text": "Hi"}\n```'
    parsed = parse_response(raw)
    assert parsed["skill"] == "chat"
    assert parsed["text"] == "Hi"


def test_parse_embedded_json():
    raw = 'Sure thing: {"skill": "get_time", "args": {}} hope that helps'
    parsed = parse_response(raw)
    assert parsed["skill"] == "get_time"
    assert parsed["args"] == {}


def test_parse_fallback_to_chat():
    parsed = parse_response("just talking, no json here")
    assert parsed["skill"] == "chat"
    assert "just talking" in parsed["text"]


def test_registry_has_core_skills():
    skills = get_skills()
    for expected in ("open_app", "set_volume", "get_time", "weather", "take_screenshot", "get_volume"):
        assert expected in skills


def test_system_prompt_lists_skills():
    skills = get_skills()
    prompt = build_system_prompt(skills)
    for name in skills:
        assert name in prompt


def test_router_executes_skill():
    llm = FakeLLM('{"skill": "get_time", "args": {}}')
    router = Router(llm=llm, memory=Memory(), skills=get_skills())
    reply = router.handle("what time is it, jarbai")
    assert "sir" in reply.lower()


def test_router_chat_skill():
    llm = FakeLLM('{"skill": "chat", "text": "Greetings, sir."}')
    router = Router(llm=llm, memory=Memory(), skills=get_skills())
    assert router.handle("hello") == "Greetings, sir."


# --- tolerance for the near-miss JSON qwen2.5:3b actually emits ---

def test_parse_bare_skill_key():
    """{"write_file": {...}} - the wrapper dropped entirely."""
    raw = '{"write_file": {"path": "a.txt", "content": "hi"}}'
    parsed = parse_response(raw, get_skills())
    assert parsed["skill"] == "write_file"
    assert parsed["args"] == {"path": "a.txt", "content": "hi"}


def test_parse_flattened_args():
    """Args placed beside the skill name instead of under "args"."""
    parsed = parse_response('{"skill": "write_file", "path": "a.txt", "content": "hi"}')
    assert parsed["skill"] == "write_file"
    assert parsed["args"] == {"path": "a.txt", "content": "hi"}


def test_parse_alternate_name_key():
    parsed = parse_response('{"name": "get_time", "args": {}}')
    assert parsed["skill"] == "get_time"


def test_bare_key_ignored_when_not_a_skill():
    """A single unknown key must stay chat, not become a bogus skill call."""
    parsed = parse_response('{"greeting": {"a": 1}}', get_skills())
    assert parsed["skill"] == "chat"


def test_router_runs_bare_skill_key():
    llm = FakeLLM('{"get_time": {}}')
    router = Router(llm=llm, memory=Memory(), skills=get_skills())
    assert "sir" in router.handle("time?").lower()


# --- ambient listening (always-on wake word + snap) ---

from jarbai.ears.ambient import command_after_wake

WAKE = ["jarbai", "jar by", "jarvis"]


def test_wake_extracts_command():
    assert command_after_wake("Jarbai, what time is it", WAKE) == "what time is it"


def test_wake_alone_returns_empty():
    assert command_after_wake("Jarbai", WAKE) == ""


def test_no_wake_word_is_ignored():
    """Ordinary room chatter must not be treated as a command."""
    assert command_after_wake("I think we should get lunch", WAKE) is None


def test_wake_mid_sentence():
    assert command_after_wake("hey Jarbai open spotify", WAKE) == "open spotify"


def test_wake_accepts_mishearing():
    assert command_after_wake("Jar by, lock the pc", WAKE) == "lock the pc"


# --- snap detection: an impulse must be told apart from speech and thumps ---

import numpy as np

from jarbai.ears.ambient import BLOCK, SAMPLERATE, AmbientListener
from jarbai.utils.config import Config


def _listener():
    return AmbientListener(Config({}))


def _rms(x):
    return float(np.sqrt(np.mean(np.square(x))))


def _snap_signal():
    rng = np.random.default_rng(7)
    sig = np.zeros(BLOCK, dtype=np.float32)
    burst = rng.normal(0, 1.0, 120).astype(np.float32) * np.exp(-np.linspace(0, 6, 120))
    sig[100:220] = burst
    return sig


def _speech_signal():
    t = np.arange(BLOCK) / SAMPLERATE
    return (0.45 * np.sin(2 * np.pi * 160 * t)
            + 0.28 * np.sin(2 * np.pi * 320 * t)
            + 0.14 * np.sin(2 * np.pi * 640 * t)).astype(np.float32)


def test_snap_is_detected():
    sig = _snap_signal()
    assert _listener()._is_snap(sig, _rms(sig))


def test_speech_is_not_a_snap():
    """Sustained speech is loud but has a low crest factor."""
    sig = _speech_signal()
    assert not _listener()._is_snap(sig, _rms(sig))


def test_low_thump_is_not_a_snap():
    """A door or desk bump is impulsive but dark, so brightness rejects it."""
    t = np.arange(BLOCK) / SAMPLERATE
    sig = np.zeros(BLOCK, dtype=np.float32)
    sig[100:300] = (np.sin(2 * np.pi * 90 * t[:200])
                    * np.exp(-np.linspace(0, 5, 200))).astype(np.float32) * 1.2
    assert not _listener()._is_snap(sig, _rms(sig))


def test_quiet_room_is_not_a_snap():
    sig = np.random.default_rng(3).normal(0, 0.004, BLOCK).astype(np.float32)
    assert not _listener()._is_snap(sig, _rms(sig))


# --- fast path: common commands must skip the LLM entirely ---

from jarbai.brain import fastpath


class BoomLLM:
    """Any call to this means the fast path failed to catch the command."""
    def chat(self, messages):
        raise AssertionError("fast path should have handled this without the LLM")


def test_fastpath_hits_common_commands():
    skills = get_skills()
    for text, expect in [
        ("what time is it", "get_time"),
        ("open spotify", "open_app"),
        ("close chrome", "close_app"),
        ("louder", "set_volume"),
        ("volume 40", "set_volume"),
        ("mute", "toggle_mute"),
        ("lock the pc", "lock_pc"),
        ("search for cheap flights", "search_web"),
        ("weather in Cebu", "weather"),
        ("what is on my screen", "look_at_screen"),
    ]:
        got = fastpath.match(text, skills)
        assert got is not None and got[0] == expect, f"{text!r} -> {got}"


def test_fastpath_extracts_arguments():
    skills = get_skills()
    assert fastpath.match("open spotify", skills)[1] == {"name": "spotify"}
    assert fastpath.match("volume 40", skills)[1] == {"level": 40}
    assert fastpath.match("google python tutorials", skills)[1] == {"query": "python tutorials"}
    assert fastpath.match("weather in Cebu", skills)[1] == {"city": "Cebu"}


def test_fastpath_ignores_open_ended_talk():
    """False matches would silently steal requests the model handles better."""
    skills = get_skills()
    for text in ["tell me a joke", "why is the sky blue", "write a poem about rain",
                 "how are you", "what do you think about this design"]:
        assert fastpath.match(text, skills) is None, text


def test_router_uses_fastpath_without_calling_llm():
    router = Router(llm=BoomLLM(), memory=Memory(), skills=get_skills())
    assert "sir" in router.handle("what time is it").lower()


# --- provider switching: cloud, local, and offline fallback ---

from jarbai.brain.llm import LLMUnavailable
from jarbai.brain.providers import AutoClient, GeminiClient, make_llm


def _cfg(provider="auto"):
    return Config({"brain": {"provider": provider, "model": "qwen2.5:3b",
                             "base_url": "http://127.0.0.1:11434",
                             "gemini_model": "gemini-flash-lite-latest"}})


class DeadClient:
    def chat(self, messages):
        raise LLMUnavailable("simulated: no internet")

    def complete(self, messages, num_predict=260):
        raise LLMUnavailable("simulated: no internet")


class LiveClient:
    def __init__(self, tag="local"):
        self.tag = tag
        self.calls = 0

    def chat(self, messages):
        self.calls += 1
        return '{"skill": "chat", "text": "%s"}' % self.tag

    def complete(self, messages, num_predict=260):
        self.calls += 1
        return self.tag


def test_provider_local_selects_ollama(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert type(make_llm(_cfg("local"))).__name__ == "LLMClient"


def test_provider_cloud_selects_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert isinstance(make_llm(_cfg("cloud")), GeminiClient)


def test_auto_without_key_falls_back_to_local(monkeypatch):
    """No API key means cloud is impossible - never hand back an AutoClient."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert type(make_llm(_cfg("auto"))).__name__ == "LLMClient"


def test_auto_uses_local_when_cloud_is_down():
    """The whole point: no internet must still get an answer."""
    local = LiveClient("local")
    auto = AutoClient(DeadClient(), local)
    assert auto.complete([{"role": "user", "content": "hi"}]) == "local"
    assert auto.last_used == "local"


def test_auto_stops_retrying_dead_cloud():
    """A cooldown, so being offline costs one timeout and not one per turn."""
    cloud = DeadClient()
    local = LiveClient("local")
    auto = AutoClient(cloud, local)
    for _ in range(3):
        auto.complete([{"role": "user", "content": "hi"}])
    assert local.calls == 3


def test_auto_prefers_cloud_when_it_works():
    cloud = LiveClient("cloud")
    local = LiveClient("local")
    auto = AutoClient(cloud, local)
    assert auto.complete([{"role": "user", "content": "hi"}]) == "cloud"
    assert local.calls == 0


def test_gemini_message_conversion():
    """system -> systemInstruction, assistant -> model."""
    system, contents = GeminiClient._convert([
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi sir"},
    ])
    assert system == ["be brief"]
    assert [c["role"] for c in contents] == ["user", "model"]
    assert contents[0]["parts"][0]["text"] == "hello"
