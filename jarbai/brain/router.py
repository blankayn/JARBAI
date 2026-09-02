from . import fastpath
from .llm import LLMUnavailable, LiveTextFilter, parse_response
from .prompts import build_system_prompt


class Router:
    def __init__(self, llm, memory, skills):
        self.llm = llm
        self.memory = memory
        self.skills = skills
        self.system_prompt = build_system_prompt(skills)

    def handle(self, user_text):
        """Process one turn and return the full reply.

        handle_stream() yields the same reply incrementally; keep the two
        in step or the UIs will diverge.
        """
        for _, reply in self.handle_stream(user_text):
            pass
        return reply

    def handle_stream(self, user_text):
        """Yield (speakable_preview, final_reply) pairs as the LLM streams.

        The first yield may be None while the envelope is still closed; the
        final yield carries the authoritative reply string, identical to what
        handle() returns. Callers must consume the generator to the end or the
        turn is never written to memory.
        """
        shortcut = fastpath.match(user_text, self.skills)
        if shortcut is not None:
            name, args = shortcut
            try:
                reply = self.skills[name].execute(args)
            except Exception as exc:
                reply = f"I encountered a problem running that skill, sir: {exc}"
            self._remember(user_text, reply)
            yield reply, reply
            return

        messages = [{"role": "system", "content": self.system_prompt}]
        messages += self.memory.messages()
        messages.append({"role": "user", "content": user_text})

        if hasattr(self.llm, "stream_chat"):
            reply = None
            try:
                live = LiveTextFilter()
                for chunk in self.llm.stream_chat(messages):
                    yield live.push(chunk), None
                reply = self._execute(live.full)
            except LLMUnavailable:
                reply = None
            except Exception:
                # a socket severed mid-stream, or the generator raised - the
                # blocking retry below either recovers the turn or reports the
                # outage, so a partial preview must not become the answer
                reply = None
            if reply is not None:
                self._remember(user_text, reply)
                yield reply, reply
                return
        else:
            try:
                raw = self.llm.chat(messages)
            except LLMUnavailable as exc:
                reply = self._offline_reply(user_text, exc)
                yield reply, reply
                return
            reply = self._execute(raw)
            self._remember(user_text, reply)
            yield reply, reply
            return

        # streaming unavailable or failed mid-flight - fall back to blocking
        try:
            raw = self.llm.chat(messages)
        except LLMUnavailable as exc:
            reply = self._offline_reply(user_text, exc)
            self._remember(user_text, reply)
            yield reply, reply
            return
        reply = self._execute(raw)
        self._remember(user_text, reply)
        yield reply, reply

    def _offline_reply(self, user_text, exc):
        reply = (
            "My apologies, sir. I cannot reach my language core. "
            "Please make sure Ollama is running and the model is pulled. "
            f"({exc})"
        )
        self._remember(user_text, reply)
        return reply

    def _remember(self, user_text, reply):
        self.memory.add("user", user_text)
        self.memory.add("assistant", reply)

    def _execute(self, raw):
        """Turn one raw LLM response into the user-facing reply, with the
        same one-shot retry and skill execution as the old handle()."""
        parsed = parse_response(raw, self.skills)

        if parsed.get("skill") == "chat" and parsed.get("text", "").strip().startswith("{"):
            messages = [{"role": "system", "content": self.system_prompt}]
            messages += self.memory.messages()
            messages.append({"role": "user", "content": raw})
            try:
                retry = self.llm.chat(messages + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content":
                        'That was not valid. Reply with exactly '
                        '{"skill": "<skill_name>", "args": {...}} using one of the listed skill names.'},
                ])
                candidate = parse_response(retry, self.skills)
                if candidate.get("skill") != "chat":
                    parsed = candidate
            except LLMUnavailable:
                pass

        skill_name = parsed.get("skill", "chat")
        if skill_name == "chat":
            reply = (parsed.get("text") or "").strip()
            if not reply:
                reply = "I'm not quite sure how to respond to that, sir."
        elif skill_name in self.skills:
            try:
                reply = self.skills[skill_name].execute(parsed.get("args") or {})
            except Exception as exc:
                reply = f"I encountered a problem running that skill, sir: {exc}"
        else:
            reply = f"I'm afraid I don't have a '{skill_name}' capability yet, sir."
        return reply
