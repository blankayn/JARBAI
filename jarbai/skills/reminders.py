"""Reminders and alarms, with a checker thread that fires on time.

The parse is deliberately hand-rolled: "remind me in 10 minutes" needs
arithmetic ("now + 10min"), which datetime.strptime cannot express, and a
3B model asked to output ISO timestamps gets them wrong often enough to
matter. A regex grammar handles every phrasing the tests cover and never
hallucinates a date.
"""

import re
import threading
import time
from datetime import datetime, timedelta

from .base import Skill, register


def parse_when(text, now=None):
    """Extract a due datetime from natural speech. Returns (when, what).

    Accepts: "in 10 minutes/3 hours/2 days", "at 5pm", "at 17:30",
    "tomorrow at 9am", "on friday at 6", and bare "tomorrow".
    Returns (None, None) when nothing parses.
    """
    now = now or datetime.now()
    text = text.strip().rstrip(".!?")
    lowered = text.lower()

    def find_what(pattern, original):
        """The reminder message is whatever the pattern did not consume."""
        used = re.sub(pattern, "", original, flags=re.I)
        # drop the leading "remind me (to|about)" the grammar leaves behind
        used = re.sub(r"^,*\s*remind\s+me(?:\s+(?:to|about))?\b", "", used, flags=re.I)
        used = used.strip(" ,.-")
        return used or "your reminder"

    # in N (minutes|hours|days|secs) -- optionally repeated ("in 2 hours 30 minutes")
    units = {"second": 1, "sec": 1, "minute": 60, "min": 60,
             "hour": 3600, "hr": 3600, "day": 86400}
    span = re.compile(r"in (\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?)"
                      r"(?:\s+(?:and\s+)?(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?))?"
                      r"(?:\s+to\s+(.+))?", re.I)
    found = span.search(lowered)
    if found:
        seconds = int(found.group(1)) * units[re.sub(r"s$", "", found.group(2).lower())]
        if found.group(3):
            seconds += int(found.group(3)) * units[re.sub(r"s$", "", found.group(4).lower())]
        when = now + timedelta(seconds=seconds)
        what = (found.group(5) or find_what(span.pattern, text)).strip()
        return when, what

    # (on )tomorrow( at H[:MM][am|pm])?
    m = re.search(r"(?:on\s+)?tomorrow"
                  r"(?:\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?)?", lowered)
    if m:
        when = (now + timedelta(days=1)).replace(
            hour=_hour(m.group(1), m.group(3)), minute=int(m.group(2) or 0),
            second=0, microsecond=0)
        what = find_what(r"(?:on\s+)?tomorrow(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(am|pm)?)?", text)
        return when, what

    # (on )<weekday>( at H[:MM][am|pm])? -- day name, next occurrence
    m = re.search(r"(?:on\s+)?(mon|tues|wednes|thurs|fri|satur|sun)day"
                  r"(?:\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?)?", lowered)
    if m:
        days = {"mon": 0, "tues": 1, "wednes": 2, "thurs": 3,
                "fri": 4, "satur": 5, "sun": 6}
        target = days[m.group(1)]
        delta = (target - now.weekday()) % 7
        if delta == 0:
            delta = 7               # "on friday" said on a friday means next one
        when = (now + timedelta(days=delta)).replace(
            hour=_hour(m.group(2), m.group(4)), minute=int(m.group(3) or 0),
            second=0, microsecond=0)
        what = find_what(
            r"(?:on\s+)?(?:mon|tues|wednes|thurs|fri|satur|sun)day"
            r"(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(am|pm)?)?", text)
        return when, what

    # at H[:MM] (am|pm)? -- today, or tomorrow if the time already passed
    m = re.search(r"at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", lowered)
    if m:
        hour = _hour(m.group(1), m.group(3))
        minute = int(m.group(2) or 0)
        when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if when <= now:
            when += timedelta(days=1)
        what = find_what(r"at\s+\d{1,2}(?::\d{2})?\s*(am|pm)?", text)
        return when, what

    return None, None


def _hour(raw, meridiem):
    hour = int(raw) % 24
    if meridiem:
        if hour == 12:
            hour = 0
        if meridiem.lower() == "pm":
            hour = 12 if hour == 12 else (hour + 12) % 24
    return hour


REMINDERS = []            # [{when: datetime, what: str, said: bool}]
_lock = threading.Lock()
_listeners = []          # callbacks fired with the reminder text, for TTS
_wake = threading.Event()


def on_due(callback):
    """Register fn(what) fired when a reminder comes due."""
    _listeners.append(callback)


def due(now=None):
    """Due, unspoken reminders, oldest first."""
    now = now or datetime.now()
    with _lock:
        return [r for r in REMINDERS if not r["said"] and r["when"] <= now]


def add(when, what):
    with _lock:
        REMINDERS.append({"when": when, "what": what, "said": False})
        REMINDERS.sort(key=lambda r: r["when"])
    _wake.set()
    return when


def cancel_all():
    with _lock:
        count = len(REMINDERS)
        REMINDERS.clear()
    return count


def load_saved():
    """Load reminders.json left by a previous run, dropping expired ones."""
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "reminders.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    now = datetime.now()
    loaded = []
    for item in data if isinstance(data, list) else []:
        try:
            when = datetime.fromisoformat(item["when"])
            if when > now:
                loaded.append({"when": when, "what": str(item.get("what", "")),
                               "said": False})
        except (KeyError, ValueError):
            continue
    with _lock:
        REMINDERS.extend(loaded)
        REMINDERS.sort(key=lambda r: r["when"])


def _persist():
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "reminders.json"
    with _lock:
        pending = [{"when": r["when"].isoformat(), "what": r["what"]}
                   for r in REMINDERS if not r["said"]]
    try:
        path.write_text(json.dumps(pending, indent=1), encoding="utf-8")
    except OSError:
        pass


def _checker(interval=15):
    """Fire reminders on time and persist the queue after changes.

    The loop parks on an Event instead of sleeping the full interval so an
    newly added reminder is picked up immediately, and the 15s ceiling keeps
    the fire time honest when the machine sleeps and wakes past due dates.
    """
    while True:
        _wake.wait(timeout=interval)
        _wake.clear()
        try:
            for reminder in due():
                with _lock:
                    reminder["said"] = True
                for callback in list(_listeners):
                    try:
                        callback(reminder["what"])
                    except Exception:
                        pass
            _persist()
        except Exception:
            pass             # a reminder must never kill the thread


def start_checker():
    thread = threading.Thread(target=_checker, daemon=True)
    thread.start()
    load_saved()
    return thread


def _fmt(when):
    return when.strftime("%I:%M %p on %A").lstrip("0")


@register
class RemindMe(Skill):
    name = "remind_me"
    description = ('Set a reminder. args: {"when": "natural time like '
                   '"in 10 minutes", "what": "the reminder text"}')

    def execute(self, args):
        args = args or {}
        when = None
        if args.get("when"):
            when, _ = parse_when(f"remind me {args['when']}")
        if when is None and args.get("text"):
            when, what = parse_when(str(args["text"]))
            if when is not None and not args.get("what"):
                args["what"] = what
        if when is None:
            when, parsed_what = parse_when(str(args.get("what") or ""))

        what = (args.get("what") or parsed_what or "your reminder").strip()
        if "remind" in what.lower():
            what = re.sub(r"^.*?remind me( to)?", "", what, flags=re.I).strip(" ,.") or "your reminder"

        if when is None:
            return ("When would you like the reminder, sir? "
                    "Say something like 'in 20 minutes' or 'tomorrow at 9am'.")
        add(when, what)
        return f"Reminder set for {_fmt(when)}, sir: {what}."


@register
class ListReminders(Skill):
    name = "list_reminders"
    description = "List pending reminders. args: {}"

    def execute(self, args):
        with _lock:
            pending = [r for r in REMINDERS if not r["said"]]
        if not pending:
            return "You have no pending reminders, sir."
        now = datetime.now()
        lines = []
        for r in pending[:6]:
            delta = r["when"] - now
            if delta.total_seconds() < 60:
                in_ = "momentarily"
            elif delta.total_seconds() < 3600:
                in_ = f"in {max(1, round(delta.total_seconds() / 60))} minutes"
            elif delta.total_seconds() < 86400:
                in_ = f"in {round(delta.total_seconds() / 3600, 1):g} hours"
            else:
                in_ = f"in {round(delta.total_seconds() / 86400, 1):g} days"
            lines.append(f"{in_}: {r['what']}")
        return "Your reminders, sir: " + "; ".join(lines) + "."


@register
class CancelReminders(Skill):
    name = "cancel_reminders"
    description = "Cancel all pending reminders. args: {}"

    def execute(self, args):
        count = cancel_all()
        _persist()
        if count:
            return f"Cancelled {count} reminder(s), sir."
        return "There were no reminders to cancel, sir."
