"""Language model providers: local Ollama, or the Gemini API.

Local is private and works with no internet, but generates at ~5 tokens/sec on
this laptop. Gemini flash-lite answers the same prompt in about a second.
So the default is "auto": use the cloud when it is reachable, and fall back to
the local model when it is not, which keeps JARBAI working offline.

Every client exposes the same two methods the rest of the code already uses:
    chat(messages)                 -> JSON string for the skill router
    complete(messages, num_predict)-> free text
"""

import json
import os
import time

import requests

from .llm import LLMClient, LLMUnavailable

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_GEMINI_MODEL = "gemini-flash-lite-latest"


class GeminiClient:
    """Gemini via the AI Studio REST API."""

    def __init__(self, model=None, api_key=None, temperature=0.4, timeout=30):
        self.model = model or DEFAULT_GEMINI_MODEL
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.temperature = temperature
        self.timeout = timeout
        self.session = requests.Session()

    @property
    def available(self):
        return bool(self.api_key)

    @staticmethod
    def _convert(messages):
        """OpenAI-style messages -> Gemini contents + systemInstruction."""
        system, contents = [], []
        for message in messages:
            role = message.get("role")
            text = message.get("content", "")
            if role == "system":
                system.append(text)
            else:
                # Gemini calls the assistant "model"
                contents.append({
                    "role": "model" if role == "assistant" else "user",
                    "parts": [{"text": text}],
                })
        return system, contents

    def _post(self, messages, *, as_json, max_tokens):
        if not self.api_key:
            raise LLMUnavailable("no GEMINI_API_KEY set")
        system, contents = self._convert(messages)
        body = {
            "contents": contents or [{"role": "user", "parts": [{"text": ""}]}],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": "\n".join(system)}]}
        if as_json:
            body["generationConfig"]["responseMimeType"] = "application/json"
        try:
            response = self.session.post(
                f"{GEMINI_BASE}/{self.model}:generateContent",
                params={"key": self.api_key},
                json=body,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise LLMUnavailable(f"gemini: {exc}") from exc
        except ValueError as exc:
            raise LLMUnavailable(f"gemini: bad response: {exc}") from exc

        try:
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip()
        except (KeyError, IndexError):
            # blocked by a safety filter, or an empty candidate
            raise LLMUnavailable(f"gemini returned no text: {json.dumps(data)[:180]}")

    def chat(self, messages):
        return self._post(messages, as_json=True, max_tokens=400)

    def complete(self, messages, num_predict=260):
        return self._post(messages, as_json=False, max_tokens=max(num_predict, 64))


class AutoClient:
    """Prefer one provider, fall back to the other when it fails.

    A failure is remembered for COOLDOWN seconds so that being offline costs
    one timeout, not a timeout on every single request.
    """

    COOLDOWN = 60

    def __init__(self, primary, fallback, on_switch=None):
        self.primary = primary
        self.fallback = fallback
        self.on_switch = on_switch
        self._blocked_until = 0.0
        self.last_used = None

    def _run(self, method, *args, **kwargs):
        now = time.monotonic()
        order = [("cloud", self.primary), ("local", self.fallback)]
        if now < self._blocked_until:
            order.reverse()          # primary recently failed - don't wait on it again

        errors = []
        for label, client in order:
            if client is None:
                continue
            try:
                result = getattr(client, method)(*args, **kwargs)
                if self.last_used != label and self.on_switch:
                    self.on_switch(label)
                self.last_used = label
                return result
            except LLMUnavailable as exc:
                errors.append(f"{label}: {exc}")
                if client is self.primary:
                    self._blocked_until = time.monotonic() + self.COOLDOWN
        raise LLMUnavailable("; ".join(errors) or "no provider configured")

    def chat(self, messages):
        return self._run("chat", messages)

    def complete(self, messages, num_predict=260):
        return self._run("complete", messages, num_predict=num_predict)


def make_llm(config, on_switch=None):
    """Build the client named by brain.provider: auto | local | cloud."""
    brain = config.get("brain", {}) or {}
    provider = str(brain.get("provider", "auto")).lower().strip()
    temperature = brain.get("temperature", 0.4)

    def local():
        return LLMClient(
            model=brain.get("model", "qwen2.5:3b"),
            base_url=brain.get("base_url", "http://127.0.0.1:11434"),
            temperature=temperature,
        )

    def cloud():
        return GeminiClient(
            model=brain.get("gemini_model", DEFAULT_GEMINI_MODEL),
            api_key=os.environ.get("GEMINI_API_KEY", ""),
            temperature=temperature,
        )

    if provider in ("local", "ollama"):
        return local()
    if provider in ("cloud", "gemini", "api"):
        return cloud()

    remote = cloud()
    if not remote.available:
        return local()               # no key - local is the only option
    return AutoClient(remote, local(), on_switch=on_switch)
