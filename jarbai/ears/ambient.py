"""Always-on listening, without Porcupine.

Porcupine only accepts its own built-in keyword list, which is why the wake
word had to stay "jarvis". Here one microphone stream stays open and we decide
locally what is worth transcribing:

  * energy VAD - only actual speech is sent to Whisper, so a quiet room costs
    nothing
  * snap detection - a sharp broadband transient arms the next utterance as a
    command, no wake word needed

Because the wake word is matched against the transcript, it can be any phrase
at all, "jarbai" included.
"""

import time

import numpy as np
import sounddevice as sd

SAMPLERATE = 16000
BLOCK = 1024                     # 64 ms at 16 kHz

# Snap heuristics. A snap lasts ~5-10 ms inside a 64 ms block, so its RMS is
# diluted about 12x and reads as quiet - peak amplitude and crest factor
# (peak/rms) are what actually separate an impulse from sustained speech.
#   snap      : high peak, high crest, bright
#   speech    : high rms,  low  crest, dark
#   door thump: high peak, high crest, dark   <- rejected by the brightness test
SNAP_MIN_PEAK = 0.25
SNAP_MIN_CREST = 6.0
SNAP_MIN_HIGH = 0.45             # share of spectral energy above 2 kHz
SNAP_OVER_BASELINE = 4.0
SNAP_DEBOUNCE = 1.0


class AmbientListener:
    """Yields ("speech", audio) and ("snap", None) events from the microphone."""

    def __init__(self, config):
        ears = config.get("ears", {}) or {}
        self.threshold = float(ears.get("silence_threshold", 0.02))
        self.silence_after = float(ears.get("silence_after_speech", 1.0))
        self.max_utterance = float(ears.get("speech_timeout", 12))
        self.min_utterance = 0.4
        self.snap_enabled = bool(ears.get("snap_enabled", True))

        # Mic gain varies a lot between machines, so these are tunable from
        # config.yaml. Run `python main.py --tune-snap` to read off your values.
        snap = ears.get("snap", {}) or {}
        self.snap_min_peak = float(snap.get("min_peak", SNAP_MIN_PEAK))
        self.snap_min_crest = float(snap.get("min_crest", SNAP_MIN_CREST))
        self.snap_min_high = float(snap.get("min_high", SNAP_MIN_HIGH))

        self.stream = None
        self._muted = False
        self._baseline = 0.01
        self._last_snap = 0.0
        self._window = np.hanning(BLOCK)
        freqs = np.fft.rfftfreq(BLOCK, 1.0 / SAMPLERATE)
        self._high_bins = freqs >= 2000

    # ---- lifecycle -------------------------------------------------
    def __enter__(self):
        self.stream = sd.InputStream(
            samplerate=SAMPLERATE, channels=1, dtype="float32", blocksize=BLOCK
        )
        self.stream.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def close(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def mute(self):
        """Stop reacting while JARBAI talks, or it answers its own voice."""
        self._muted = True

    def unmute(self):
        # Drop whatever queued up while muted so the reply is not transcribed.
        if self.stream is not None:
            try:
                pending = self.stream.read_available
                if pending:
                    self.stream.read(pending)
            except Exception:
                pass
        self._muted = False

    # ---- detection -------------------------------------------------
    def _is_snap(self, chunk, rms):
        peak = float(np.max(np.abs(chunk)))
        if peak < self.snap_min_peak or peak < self._baseline * SNAP_OVER_BASELINE:
            return False
        if peak / max(rms, 1e-6) < self.snap_min_crest:
            return False                      # sustained sound, not an impulse
        spectrum = np.abs(np.fft.rfft(chunk * self._window))
        total = float(spectrum.sum())
        if total <= 0:
            return False
        return float(spectrum[self._high_bins].sum()) / total > self.snap_min_high

    def snap_metrics(self, chunk):
        """peak, crest and brightness for one block - used by --tune-snap."""
        peak = float(np.max(np.abs(chunk)))
        rms = float(np.sqrt(np.mean(np.square(chunk))))
        spectrum = np.abs(np.fft.rfft(chunk * self._window))
        total = float(spectrum.sum())
        high = float(spectrum[self._high_bins].sum()) / total if total > 0 else 0.0
        return peak, peak / max(rms, 1e-6), high

    def listen(self):
        """Generator of ("snap", None) and ("speech", np.ndarray) events."""
        block_seconds = BLOCK / SAMPLERATE
        frames = []
        speaking = False
        silent = 0.0
        spoken = 0.0

        while True:
            data, _ = self.stream.read(BLOCK)
            chunk = data.flatten()

            if self._muted:
                frames, speaking, silent, spoken = [], False, 0.0, 0.0
                continue

            rms = float(np.sqrt(np.mean(np.square(chunk))))

            if self.snap_enabled and not speaking and self._is_snap(chunk, rms):
                now = time.monotonic()
                if now - self._last_snap > SNAP_DEBOUNCE:
                    self._last_snap = now
                    self._baseline = max(self._baseline, 0.01)
                    yield "snap", None
                    continue

            if not speaking:
                # track the room's peak noise floor while nobody is talking
                self._baseline = self._baseline * 0.95 + float(np.max(np.abs(chunk))) * 0.05
                if rms > self.threshold:
                    speaking = True
                    frames = [chunk]
                    spoken = block_seconds
                    silent = 0.0
                continue

            frames.append(chunk)
            spoken += block_seconds
            if rms < self.threshold:
                silent += block_seconds
            else:
                silent = 0.0

            done = silent >= self.silence_after or spoken >= self.max_utterance
            if not done:
                continue

            audio = np.concatenate(frames)
            frames, speaking, silent, spoken = [], False, 0.0, 0.0
            if audio.size >= int(self.min_utterance * SAMPLERATE):
                yield "speech", audio

    def next_utterance(self, timeout=8.0):
        """Block for one utterance - used for the command after a snap."""
        deadline = time.monotonic() + timeout
        block_seconds = BLOCK / SAMPLERATE
        frames = []
        speaking = False
        silent = 0.0
        spoken = 0.0

        while time.monotonic() < deadline:
            data, _ = self.stream.read(BLOCK)
            chunk = data.flatten()
            if self._muted:
                continue
            rms = float(np.sqrt(np.mean(np.square(chunk))))

            if not speaking:
                if rms > self.threshold:
                    speaking = True
                    frames = [chunk]
                    spoken = block_seconds
                continue

            frames.append(chunk)
            spoken += block_seconds
            if rms < self.threshold:
                silent += block_seconds
                if silent >= self.silence_after and spoken > self.min_utterance:
                    break
            else:
                silent = 0.0

        if not frames:
            return None
        audio = np.concatenate(frames)
        return audio if audio.size >= int(self.min_utterance * SAMPLERATE) else None


def command_after_wake(transcript, wake_words):
    """Return the command following the wake word, "" if only the wake word
    was said, or None if it was not spoken at all."""
    lowered = transcript.lower()
    for word in wake_words:
        at = lowered.find(word)
        if at == -1:
            continue
        return transcript[at + len(word):].lstrip(" ,.:;!?-").strip()
    return None
