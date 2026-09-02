"""Rule-based dispatch for the commands you actually say most.

An LLM round trip costs ~1.8s on this machine even with the model resident,
and routing "what time is it" through a 3B model is pure waste. These patterns
answer the common cases with no LLM call at all - the reply is instant.

Anything that does not match falls through to the router, so this only ever
makes JARBAI faster, never less capable. Keep the patterns strict: a false
match here silently steals a request the model would have handled better.
"""

import re

# (compiled pattern, skill name, builder taking the match -> args dict)
RULES = []


def rule(pattern, skill, args=None):
    RULES.append((re.compile(pattern, re.I), skill, args or (lambda m: {})))


# --- time -------------------------------------------------------------
rule(r"^(?:what(?:'s| is)? )?(?:the )?time(?: is it)?\??$", "get_time")
rule(r"^what(?:'s| is)? the (?:date|day)\??$", "get_time")
rule(r"^what time is it\??$", "get_time")

# --- screen -----------------------------------------------------------
rule(r"^(?:what(?:'s| is)?(?: on)? (?:my |the )?screen|"
     r"what am i (?:looking at|seeing)|read (?:my |the )?screen|"
     r"look at (?:my |the )?screen|what(?:'s| is) this)\b.*",
     "look_at_screen", lambda m: {"question": m.group(0)})

# --- volume -----------------------------------------------------------
rule(r"^(?:turn (?:it )?up|volume up|louder|turn the volume up)\b\.?$",
     "set_volume", lambda m: {"level": "+"})
rule(r"^(?:turn (?:it )?down|volume down|quieter|turn the volume down)\b\.?$",
     "set_volume", lambda m: {"level": "-"})
rule(r"^(?:set )?volume(?: to)? (?P<n>\d{1,3})\b.*", "set_volume",
     lambda m: {"level": int(m.group("n"))})
rule(r"^(?:what(?:'s| is)? the )?volume\??$", "get_volume")
rule(r"^(?:un)?mute\b.*", "toggle_mute")

# --- system -----------------------------------------------------------
rule(r"^lock(?: the)?(?: pc| computer| workstation| screen)?\b\.?$", "lock_pc")
rule(r"^(?:take a )?screenshot\b.*", "take_screenshot")

# --- apps -------------------------------------------------------------
rule(r"^(?:open|launch|start|run) (?:up )?(?P<name>[\w .+-]{2,40})$",
     "open_app", lambda m: {"name": m.group("name").strip()})
rule(r"^(?:close|quit|exit|kill) (?P<name>[\w .+-]{2,40})$",
     "close_app", lambda m: {"name": m.group("name").strip()})

# --- web --------------------------------------------------------------
rule(r"^(?:search|google|look up)(?: the web)?(?: for)? (?P<q>.+)$",
     "search_web", lambda m: {"query": m.group("q").strip()})
rule(r"^(?:open|go to) (?P<url>(?:https?://|www\.)[^\s]+|[\w-]+\.(?:com|org|net|io|dev|ph)(?:/\S*)?)$",
     "open_url", lambda m: {"url": m.group("url").strip()})

# --- weather ----------------------------------------------------------
rule(r"^(?:what(?:'s| is)? the )?weather(?: like)?(?: in| for| at) (?P<city>[\w .'-]{2,40})\??$",
     "weather", lambda m: {"city": m.group("city").strip(" ?.")})

# --- files ------------------------------------------------------------
rule(r"^(?:read|open|show me)(?: the)?(?: file)? (?P<path>[\w./\\ -]+\.\w{1,5})$",
     "read_file", lambda m: {"path": m.group("path").strip()})
rule(r"^(?:list|show)(?: me)?(?: my)? files\b.*", "list_files")
rule(r"^(?:where(?:'s| is)? (?:my |the )?workspace|workspace path)\??$", "workspace_path")

# --- reminders --------------------------------------------------------
rule(r"^remind me in\b.*", "remind_me", lambda m: {"text": m.group(0)})
rule(r"^remind me (?:tomorrow|on \w+day|at \d)\b.*", "remind_me",
     lambda m: {"text": m.group(0)})
rule(r"^remind me to\b.*", "remind_me", lambda m: {"text": m.group(0)})
rule(r"^(?:what|list)(?: are)?(?: my)? reminders\??$", "list_reminders")
rule(r"^(?:cancel|clear|forget) (?:all )?(?:my )?reminders\b.*", "cancel_reminders")


def match(text, skills=None):
    """Return (skill_name, args) for a recognised command, else None."""
    cleaned = (text or "").strip().strip(".!")
    if not cleaned:
        return None
    for pattern, skill, build in RULES:
        found = pattern.match(cleaned)
        if not found:
            continue
        if skills is not None and skill not in skills:
            continue
        try:
            return skill, build(found)
        except (ValueError, IndexError):
            return None
    return None
