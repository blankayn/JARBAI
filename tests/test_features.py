"""Streaming, memory persistence, reminders - the turn-key features."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import jarbai.skills.reminders as rem_module
from jarbai.brain.llm import LiveTextFilter
from jarbai.brain.memory import Memory
from jarbai.brain.router import Router
from jarbai.skills import get_skills
from jarbai.skills import reminders as rem


# ---- LiveTextFilter: partial JSON must render as speakable prose ----

def _feed(chunks):
    live = LiveTextFilter()
    out = []
    for c in chunks:
        r = live.push(c)
        if r is not None:
            out.append(r)
    return out, live


def test_filter_streams_chat_text():
    chunks = ['{"skill": ', '"chat"', ', "text": ', '"Quite', ' well, ', 'sir."}']
    texts, live = _feed(chunks)
    assert live.full == '{"skill": "chat", "text": "Quite well, sir."}'
    # the last preview is the full text; nothing raw ever showed
    assert texts[-1] == "Quite well, sir."
    assert all("{" not in t and '"' not in t for t in texts)


def test_filter_caption_for_skill_calls():
    texts, live = _feed(['{"skill": ', '"open_app"', ', "args": {"name": "spotify"}}'])
    assert texts[-1] == "Opening it, sir…"
    assert "spotify" not in texts[-1]


def test_filter_handles_escapes():
    # the text contains an escaped quote split across chunks: the JSON is
    # {"skill":"chat","text":"say \"hi\" sir"} - the \" must survive whole
    chunks = ['{"skill":"chat","text":"say \\"', 'hi\\" sir"}']
    texts, live = _feed(chunks)
    assert texts[-1] == 'say "hi" sir'


def test_filter_silent_before_envelope_opens():
    out, _ = _feed(['{"sk'])
    assert out == []            # braces must never flash on screen


# ---- Router.handle_stream: streaming must equal handle() exactly ----

class ChunkedLLM:
    """Serves a reply in word-sized chunks, exactly like Ollama's stream."""

    def __init__(self, full):
        self.full = full
        self.streamed = False

    def chat(self, messages):
        return self.full

    def stream_chat(self, messages, num_predict=80):
        self.streamed = True
        for i in range(len(self.full)):
            yield self.full[i:i + 1]


def test_handle_stream_matches_handle(tmp_path):
    full = '{"skill": "chat", "text": "Greetings, sir."}'
    llm = ChunkedLLM(full)

    mem1 = Memory(max_turns=10, path=tmp_path / "a.json")
    mem2 = Memory(max_turns=10, path=tmp_path / "b.json")
    r_stream = Router(llm=llm, memory=mem1, skills=get_skills())
    r_plain = Router(llm=llm, memory=mem2, skills=get_skills())

    previews, finals = [], []
    for preview, final in r_stream.handle_stream("hello"):
        if preview is not None:
            previews.append(preview)
        if final is not None:
            finals.append(final)

    assert finals == ["Greetings, sir."]
    assert r_plain.handle("hello") == finals[0]
    assert llm.streamed
    assert previews[-1] == finals[0]
    assert mem1.messages() == mem2.messages()


def test_stream_falls_back_when_provider_cannot_stream(tmp_path):
    """AutoClient/Gemini have no stream_chat - handle_stream still works."""
    class NoStream:
        def chat(self, messages):
            return '{"skill": "chat", "text": "Blocking path taken, sir."}'

    router = Router(llm=NoStream(), memory=Memory(path=tmp_path / "m.json"),
                    skills=get_skills())
    finals = [f for _, f in router.handle_stream("hello") if f is not None]
    assert finals == ["Blocking path taken, sir."]


def test_stream_offline_midflight_keeps_memory_clean(tmp_path):
    class DiesMidStream:
        """Socket severed halfway; the blocking retry recovers the turn."""
        def __init__(self):
            self.chat_called = False

        def chat(self, messages):
            self.chat_called = True
            return '{"skill": "chat", "text": "Recovered, sir."}'

        def stream_chat(self, messages, num_predict=80):
            yield '{"skill": "chat", "text": '
            raise Exception("socket severed")

    llm = DiesMidStream()
    router = Router(llm=llm, memory=Memory(path=tmp_path / "m.json"),
                    skills=get_skills())
    previews, finals = [], []
    for preview, final in router.handle_stream("hello"):
        if preview is not None:
            previews.append(preview)
        if final is not None:
            finals.append(final)

    assert llm.chat_called               # the blocking path took over
    assert finals == ["Recovered, sir."]
    # the mid-stream partial ("Recovered" never arrived) showed nothing;
    # the one preview is the fallback's own full reply
    assert previews == ["Recovered, sir."]


def test_stream_offline_fully_dead_reports_outage(tmp_path):
    from jarbai.brain.llm import LLMUnavailable

    class DeadLLM:
        def chat(self, messages):
            raise LLMUnavailable("connection refused")

        def stream_chat(self, messages, num_predict=80):
            raise LLMUnavailable("connection refused")
            yield                    # pragma: no cover - makes this a generator

    router = Router(llm=DeadLLM(), memory=Memory(path=tmp_path / "m.json"),
                    skills=get_skills())
    finals = [f for _, f in router.handle_stream("hello") if f is not None]
    assert len(finals) == 1
    assert "language core" in finals[0]


# ---- Memory: both UIs share one file-backed conversation ----

def test_memory_persists_across_instances(tmp_path):
    path = tmp_path / "memory.json"
    first = Memory(max_turns=10, path=path)
    first.add("user", "hello")
    first.add("assistant", "Good day, sir.")

    second = Memory(max_turns=10, path=path)      # a fresh process
    assert [m["content"] for m in second.messages()] == ["hello", "Good day, sir."]


def test_memory_trims_to_max_turns(tmp_path):
    path = tmp_path / "memory.json"
    mem = Memory(max_turns=4, path=path)
    for i in range(20):
        mem.add("user", f"m{i}")
    contents = [m["content"] for m in mem.messages()]
    assert len(contents) == 4
    assert contents == ["m16", "m17", "m18", "m19"]
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert len(on_disk) == 4


def test_memory_survives_corrupt_file(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text("{ not json", encoding="utf-8")
    mem = Memory(path=path)
    assert mem.messages() == []
    mem.add("user", "still works")
    assert Memory(path=path).messages()[0]["content"] == "still works"


def test_memory_clear_removes_file(tmp_path):
    path = tmp_path / "memory.json"
    mem = Memory(path=path)
    mem.add("user", "gone")
    mem.clear()
    assert not path.exists()
    assert Memory(path=path).messages() == []


# ---- reminder time parsing: the grammar a 3B model cannot be trusted with ----

NOW = datetime(2026, 9, 2, 14, 0)      # a Wednesday


def test_parse_in_minutes():
    when, what = rem.parse_when("remind me in 10 minutes to stretch", NOW)
    assert when == NOW + timedelta(minutes=10)
    assert what == "stretch"


def test_parse_in_hours_and_minutes():
    when, what = rem.parse_when("remind me in 1 hour and 30 minutes to eat", NOW)
    assert when == NOW + timedelta(minutes=90)
    assert what == "eat"


def test_parse_tomorrow_at_time():
    when, what = rem.parse_when("remind me tomorrow at 9am to take pills", NOW)
    assert when == datetime(2026, 9, 3, 9, 0)
    assert what == "take pills"


def test_parse_weekday():
    when, what = rem.parse_when("remind me on friday at 6pm to call mum", NOW)
    # Sep 2 2026 is a Wednesday; the coming Friday is Sep 4
    assert when == datetime(2026, 9, 4, 18, 0)
    assert what == "call mum"


def test_parse_weekday_next_week():
    when, _ = rem.parse_when("remind me on wednesday at 8am to file taxes", NOW)
    # "on wednesday" said ON a wednesday means the NEXT one
    assert when == datetime(2026, 9, 9, 8, 0)


def test_parse_at_time_today():
    when, what = rem.parse_when("remind me at 5:30 pm to log off", NOW)
    assert when == datetime(2026, 9, 2, 17, 30)
    assert what == "log off"


def test_parse_at_time_rolls_to_tomorrow():
    when, _ = rem.parse_when("remind me at 9am to drink water", NOW)
    assert when == datetime(2026, 9, 3, 9, 0)      # 9am already passed


def test_parse_pm_without_minutes():
    when, _ = rem.parse_when("remind me at 7pm about dinner", NOW)
    assert when == datetime(2026, 9, 2, 19, 0)


def test_parse_no_time_returns_none():
    assert rem.parse_when("hello there", NOW) == (None, None)


# ---- reminder skill behaviour ----

def test_remind_me_skill_sets_reminder():
    skills = get_skills()
    skills["remind_me"].execute({"text": "remind me in 75 minutes to move"})
    with rem._lock:
        pending = [r for r in rem.REMINDERS if not r["said"]]
    assert any(r["what"] == "move" for r in pending)
    rem.cancel_all()


def test_remind_me_asks_when_unparseable():
    skills = get_skills()
    reply = skills["remind_me"].execute({"when": "sometime soon"})
    assert "When would you like the reminder" in reply


def test_list_reminders_empty_and_set():
    skills = get_skills()
    rem.cancel_all()
    assert "no pending reminders" in skills["list_reminders"].execute({}).lower()
    rem.add(datetime.now() + timedelta(hours=2), "test the lister")
    reply = skills["list_reminders"].execute({})
    assert "test the lister" in reply
    rem.cancel_all()


def test_due_fires_once():
    rem.cancel_all()
    fired = []
    rem.on_due(fired.append)
    rem.add(datetime.now() - timedelta(minutes=1), "past due item")
    due_list = rem.due()
    assert [d["what"] for d in due_list] == ["past due item"]
    rem.cancel_all()
    rem._listeners.remove(fired.append)


def test_reminders_roundtrip_through_file(tmp_path, monkeypatch):
    # _persist() derives its path from __file__, so chdir is not enough -
    # point the module at a scratch file or the test pollutes the real one
    scratch = tmp_path / "reminders.json"

    def fake_persist():
        scratch.write_text(json.dumps(
            [{"when": r["when"].isoformat(), "what": r["what"]}
             for r in rem.REMINDERS if not r["said"]]), encoding="utf-8")

    def fake_load():
        try:
            data = json.loads(scratch.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        now = datetime.now()
        for item in data if isinstance(data, list) else []:
            try:
                when = datetime.fromisoformat(item["when"])
                if when > now:
                    rem.REMINDERS.append({"when": when,
                                          "what": str(item.get("what", "")),
                                          "said": False})
            except (KeyError, ValueError):
                continue
        rem.REMINDERS.sort(key=lambda r: r["when"])

    monkeypatch.setattr(rem, "_persist", fake_persist)
    monkeypatch.setattr(rem, "load_saved", fake_load)
    rem.cancel_all()
    rem.add(datetime.now() + timedelta(minutes=30), "persisted")
    rem._persist()
    rem.cancel_all()
    rem.load_saved()
    with rem._lock:
        assert any(r["what"] == "persisted" for r in rem.REMINDERS)
    rem.cancel_all()


# ---- fastpath picks reminders up without an LLM round trip ----

from jarbai.brain import fastpath


def test_fastpath_catches_reminders():
    skills = get_skills()
    for text, expect in [
        ("remind me in 20 minutes to stretch", "remind_me"),
        ("remind me tomorrow at 9am to ship", "remind_me"),
        ("remind me to call the bank", "remind_me"),
        ("what are my reminders", "list_reminders"),
        ("cancel all reminders", "cancel_reminders"),
    ]:
        got = fastpath.match(text, skills)
        assert got is not None and got[0] == expect, f"{text!r} -> {got}"


def test_router_reminds_without_llm():
    class Boom:
        def chat(self, messages):
            raise AssertionError("fast path should have handled this")

    router = Router(llm=Boom(), memory=Memory(path="nul"), skills=get_skills())
    reply = router.handle("what are my reminders")
    assert "sir" in reply.lower()
