import json
import re

import requests


class LLMUnavailable(Exception):
    pass


class LLMClient:
    def __init__(self, model, base_url, temperature=0.4):
        self.model = model
        # "localhost" costs ~2.1s per call on Windows: it resolves to ::1
        # first, Ollama listens on IPv4, the connection is refused and only
        # then does it retry 127.0.0.1. Measured 3.87s vs 1.80s per request.
        self.base_url = base_url.rstrip("/").replace("//localhost:", "//127.0.0.1:")
        self.temperature = temperature
        # Reusing the connection avoids a fresh TCP handshake every turn.
        self.session = requests.Session()

    def chat(self, messages):
        try:
            response = self.session.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "format": "json",
                    "keep_alive": "30m",
                    # a skill call is ~20 tokens; without a cap the model can
                    # ramble and every extra token costs ~0.13s on this CPU
                    "options": {"temperature": self.temperature, "num_predict": 80},
                },
                timeout=60,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise LLMUnavailable(str(exc)) from exc
        return response.json().get("message", {}).get("content", "")

    def complete(self, messages, num_predict=260):
        """Free-text reply, without the JSON forcing that chat() uses.

        chat() sets format="json" so the router can parse a skill call. Skills
        that need prose back - answering a question about the screen, say -
        must not go through that.
        """
        try:
            response = self.session.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "keep_alive": "30m",
                    "options": {
                        "temperature": self.temperature,
                        "num_predict": num_predict,
                    },
                },
                timeout=120,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise LLMUnavailable(str(exc)) from exc
        return response.json().get("message", {}).get("content", "").strip()

    def stream_chat(self, messages, num_predict=80):
        """Yield incremental chunks of the reply as Ollama produces them.

        Same request shape as chat(), but stream=True and reading
        line-delimited JSON off the socket. Each yielded string is only the
        NEW text since the previous yield, so ''.join(chunks) equals the full
        reply. On a connection failure mid-stream the chunks already yielded
        are kept and the error is raised - callers can show what they have.
        """
        try:
            response = self.session.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": True,
                    "format": "json",
                    "keep_alive": "30m",
                    "options": {"temperature": self.temperature,
                                "num_predict": num_predict},
                },
                stream=True,
                timeout=(5, 90),
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise LLMUnavailable(str(exc)) from exc
        with response:
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not event.get("done", False):
                    chunk = event.get("message", {}).get("content", "")
                    if chunk:
                        yield chunk


def parse_response(raw, skills=None):
    text = raw.strip()
    if not text:
        return {"skill": "chat", "text": ""}
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {"skill": "chat", "text": raw.strip()}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {"skill": "chat", "text": raw.strip()}
    return _normalise(parsed, skills or (), raw)


NAME_KEYS = ("skill", "name", "tool", "function", "action")
TEXT_KEYS = ("text", "message", "reply", "response")


class LiveTextFilter:
    """Extract speakable text from a PARTIAL skill-call JSON stream.

    The router's replies arrive as {"skill": "chat", "text": "..."} built up
    token by token. Showing that raw would flash braces and quotes at the
    user. This filter walks the partial string with a forgiving scanner and
    emits only the prose inside the text field - or, for skill calls, brief
    progress captions instead of the JSON envelope.
    """

    CAPTIONS = {
        "open_app": "Opening it, sir\u2026",
        "close_app": "Closing it, sir\u2026",
        "set_volume": "Adjusting volume, sir\u2026",
        "take_screenshot": "Capturing the screen, sir\u2026",
        "lock_pc": "Locking the workstation, sir\u2026",
        "weather": "Checking the weather relay, sir\u2026",
        "search_web": "Searching, sir\u2026",
        "open_url": "Opening it, sir\u2026",
        "look_at_screen": "Reading the screen, sir\u2026",
        "read_screen": "Reading the screen, sir\u2026",
    }

    def __init__(self):
        self.full = ""

    def push(self, chunk):
        """Feed one chunk; return the speakable text so far, or None."""
        self.full += chunk
        return self.render()

    def render(self):
        text = LiveTextFilter._extract_text(self.full)
        if text is not None:
            return text
        skill = LiveTextFilter._extract_skill(self.full)
        return self.CAPTIONS.get(skill) if skill else None

    @staticmethod
    def _in_text_field(partial):
        """True if the scan cursor sits inside the text field's string."""
        marker = re.search(r'"(?:text|message|reply|response)"\s*:\s*"', partial)
        return marker is not None and marker.end() > partial.rfind('"', 0, len(partial) - 1)

    @staticmethod
    def _extract_text(partial):
        """The text field's value so far, or None if it has not started.

        Escapes are decoded once, at the end, so a half-written \\uXXXX never
        renders as garbage mid-stream.
        """
        marker = re.search(r'"(?:text|message|reply|response)"\s*:\s*"', partial)
        if not marker:
            return None
        body = partial[marker.end():]
        out = []
        i = 0
        while i < len(body):
            ch = body[i]
            if ch == "\\" and i + 1 < len(body):
                out.append(body[i:i + 2])
                i += 2
                continue
            if ch == '"':
                break
            out.append(ch)
            i += 1
        raw = "".join(out)
        try:
            return json.loads(f'"{raw}"')
        except json.JSONDecodeError:
            return raw

    @staticmethod
    def _extract_skill(partial):
        marker = re.search(r'"(?:skill|name|tool|function|action)"\s*:\s*"([^"]*)', partial)
        return marker.group(1) if marker else None


def _normalise(parsed, skills, raw):
    """Coerce the near-miss JSON shapes small models emit into our envelope.

    qwen2.5:3b routes correctly but often drops the wrapper, producing
    {"write_file": {...}} or flattening args to the top level. Rejecting those
    as chat made the model look far dumber than it is, so accept them.
    """
    if not isinstance(parsed, dict):
        return {"skill": "chat", "text": raw.strip()}

    name = next((parsed[k] for k in NAME_KEYS if isinstance(parsed.get(k), str)), None)

    # {"write_file": {"path": ...}} - a single key naming a real skill
    if name is None and len(parsed) == 1:
        key, value = next(iter(parsed.items()))
        if key in skills:
            return {"skill": key, "args": value if isinstance(value, dict) else {}}

    if name is None:
        text = next((parsed[k] for k in TEXT_KEYS if isinstance(parsed.get(k), str)), None)
        return {"skill": "chat", "text": text if text else raw.strip()}

    if name == "chat":
        text = next((parsed[k] for k in TEXT_KEYS if isinstance(parsed.get(k), str)), "")
        return {"skill": "chat", "text": text}

    args = parsed.get("args")
    if not isinstance(args, dict):
        # args flattened alongside the skill name
        args = {
            k: v for k, v in parsed.items()
            if k not in NAME_KEYS and k not in TEXT_KEYS and k != "args"
        }
    return {"skill": name, "args": args}
