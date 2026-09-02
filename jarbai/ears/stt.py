import io
import os
import time
import wave

import numpy as np

SAMPLERATE = 16000


def _to_wav_bytes(audio, samplerate=SAMPLERATE):
    """float32 mono -> 16-bit PCM WAV, which the Gemini API accepts directly."""
    pcm = np.clip(np.asarray(audio, dtype=np.float32).flatten(), -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(samplerate)
        handle.writeframes(pcm.tobytes())
    return buffer.getvalue()


class Transcriber:
    """Speech to text, cloud or local.

    ears.stt_provider:
        auto  - Gemini when reachable, local faster-whisper when not
        local - always faster-whisper (private, works offline)
        cloud - always Gemini

    Local Whisper stays the fallback so JARBAI still hears you with no
    internet; it just costs about a second per utterance on this CPU.
    """

    COOLDOWN = 60          # after a cloud failure, stop retrying for this long

    def __init__(self, config):
        ears_cfg = config.get("ears", {}) or {}
        self.model_size = ears_cfg.get("whisper_model", "small")
        self.provider = str(ears_cfg.get("stt_provider", "auto")).lower().strip()
        self.gemini_model = ears_cfg.get(
            "stt_gemini_model",
            (config.get("brain", {}) or {}).get("gemini_model", "gemini-flash-lite-latest"),
        )
        self.model = None
        self._session = None
        self._blocked_until = 0.0
        self.last_used = None

    # ---- local ------------------------------------------------------
    def _load(self):
        if self.model is None:
            from faster_whisper import WhisperModel

            self.model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        return self.model

    def _transcribe_local(self, audio):
        model = self._load()
        audio = np.asarray(audio, dtype=np.float32).flatten()
        if audio.size == 0:
            return ""
        segments, _ = model.transcribe(audio, language="en", beam_size=1, vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments).strip()

    # ---- cloud ------------------------------------------------------
    @property
    def _api_key(self):
        return os.environ.get("GEMINI_API_KEY", "")

    def _transcribe_cloud(self, audio):
        import base64

        import requests

        if not self._api_key:
            raise RuntimeError("no GEMINI_API_KEY set")
        if self._session is None:
            self._session = requests.Session()

        payload = base64.b64encode(_to_wav_bytes(audio)).decode()
        body = {
            "contents": [{"parts": [
                {"text": "Transcribe this audio verbatim in English. "
                         "Output only the transcript, with no commentary. "
                         "If there is no speech, output nothing."},
                {"inline_data": {"mime_type": "audio/wav", "data": payload}},
            ]}],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 256},
        }
        response = self._session.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent",
            params={"key": self._api_key},
            json=body,
            timeout=25,
        )
        response.raise_for_status()
        data = response.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError):
            return ""       # nothing recognised, or filtered
        return "".join(p.get("text", "") for p in parts).strip()

    # ---- dispatch ---------------------------------------------------
    def transcribe(self, audio):
        audio = np.asarray(audio, dtype=np.float32).flatten()
        if audio.size == 0:
            return ""

        use_cloud = self.provider in ("cloud", "gemini", "api") or (
            self.provider == "auto"
            and self._api_key
            and time.monotonic() >= self._blocked_until
        )
        if use_cloud:
            try:
                text = self._transcribe_cloud(audio)
                self.last_used = "cloud"
                return text
            except Exception:
                # offline, rate limited, or refused - fall back and stop
                # retrying the network for a while
                self._blocked_until = time.monotonic() + self.COOLDOWN
                if self.provider in ("cloud", "gemini", "api"):
                    raise

        self.last_used = "local"
        return self._transcribe_local(audio)
