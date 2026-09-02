import asyncio
import hashlib
import tempfile
from pathlib import Path

import miniaudio
import numpy as np
import sounddevice as sd
import edge_tts

# edge-tts is a network round trip - measured 0.72s for "Yes, sir?" and ~1.0s
# for a sentence. JARBAI repeats itself constantly ("Yes, sir?", volume and
# file confirmations), so synthesised audio is cached on disk and replayed.
CACHE = Path(__file__).resolve().parents[2] / ".cache" / "tts"
CACHE_LIMIT = 400


def _play_file(path):
    decoded = miniaudio.decode_file(str(path))
    samples = np.frombuffer(decoded.samples, dtype=np.int16).reshape(-1, decoded.nchannels)
    sd.play(samples, decoded.sample_rate)
    sd.wait()


def _prune(folder, limit=CACHE_LIMIT):
    files = sorted(folder.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
    for old in files[:-limit]:
        old.unlink(missing_ok=True)


class Speaker:
    def __init__(self, config):
        voice_cfg = config.get("voice", {}) or {}
        self.engine = voice_cfg.get("tts_engine", "edge-tts")
        self.edge_voice = voice_cfg.get("edge_voice", "en-GB-RyanNeural")
        self.rate = voice_cfg.get("rate", "+12%")
        self.pyttsx3_voice_index = int(voice_cfg.get("pyttsx3_voice_index", 0))

    def speak(self, text):
        if not text:
            return
        if self.engine == "edge-tts":
            try:
                self._speak_edge(text)
                return
            except Exception:
                pass
        self._speak_pyttsx3(text)

    def _cache_path(self, text):
        key = f"{self.edge_voice}|{self.rate}|{text}"
        return CACHE / (hashlib.sha1(key.encode("utf-8")).hexdigest() + ".mp3")

    def _speak_edge(self, text):
        cached = self._cache_path(text)
        if cached.is_file() and cached.stat().st_size > 0:
            _play_file(cached)          # no network at all
            return

        CACHE.mkdir(parents=True, exist_ok=True)
        # synthesise to a temp file first so an interrupted run cannot leave a
        # truncated file in the cache that would be replayed forever
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=CACHE) as tmp:
            staging = Path(tmp.name)
        try:
            asyncio.run(self._save_edge(text, staging))
            if staging.stat().st_size > 0:
                staging.replace(cached)
                _play_file(cached)
                _prune(CACHE)
            else:
                raise RuntimeError("edge-tts returned no audio")
        finally:
            staging.unlink(missing_ok=True)

    def prewarm(self, phrases):
        """Synthesise phrases said on every interaction, before they're needed."""
        for phrase in phrases:
            try:
                if not self._cache_path(phrase).is_file():
                    CACHE.mkdir(parents=True, exist_ok=True)
                    asyncio.run(self._save_edge(phrase, self._cache_path(phrase)))
            except Exception:
                return          # offline or unavailable - not worth retrying

    async def _save_edge(self, text, path):
        communicate = edge_tts.Communicate(text, self.edge_voice, rate=self.rate)
        await communicate.save(str(path))

    def _speak_pyttsx3(self, text):
        import pyttsx3

        engine = pyttsx3.init()
        voices = engine.getProperty("voices")
        if voices and 0 <= self.pyttsx3_voice_index < len(voices):
            engine.setProperty("voice", voices[self.pyttsx3_voice_index].id)
        engine.say(text)
        engine.runAndWait()
