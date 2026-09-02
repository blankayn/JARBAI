import numpy as np
import sounddevice as sd


class Recorder:
    def __init__(self, config):
        ears_cfg = config.get("ears", {}) or {}
        self.samplerate = 16000
        self.threshold = float(ears_cfg.get("silence_threshold", 0.02))
        self.timeout = float(ears_cfg.get("speech_timeout", 12))
        self.silence_after_speech = float(ears_cfg.get("silence_after_speech", 1.2))
        self.blocksize = 1024

    def record(self):
        frames = []
        speech_started = False
        silent_seconds = 0.0
        spoken_seconds = 0.0
        elapsed = 0.0
        block_seconds = self.blocksize / self.samplerate
        print("Listening...")
        with sd.InputStream(
            samplerate=self.samplerate,
            channels=1,
            dtype="float32",
            blocksize=self.blocksize,
        ) as stream:
            while elapsed < self.timeout:
                data, _ = stream.read(self.blocksize)
                elapsed += block_seconds
                chunk = data.flatten()
                rms = float(np.sqrt(np.mean(np.square(chunk))))
                if not speech_started:
                    if rms > self.threshold:
                        speech_started = True
                        print("Heard you.")
                    else:
                        continue
                frames.append(chunk)
                spoken_seconds += block_seconds
                if rms < self.threshold:
                    silent_seconds += block_seconds
                    if silent_seconds >= self.silence_after_speech and spoken_seconds > 0.4:
                        break
                else:
                    silent_seconds = 0.0
        if not speech_started or not frames:
            return None
        audio = np.concatenate(frames)
        if audio.size < int(0.4 * self.samplerate):
            return None
        return audio
