import numpy as np
import pvporcupine
import sounddevice as sd


class WakeWordNotConfigured(Exception):
    pass


class WakeWordListener:
    def __init__(self, config):
        ears_cfg = config.get("ears", {}) or {}
        access_key = ears_cfg.get("porcupine_access_key", "")
        # pvporcupine.create(keywords=...) only accepts its own built-in list, so
        # a custom name like "jarbai" cannot work here - fall back to "jarvis"
        # rather than crashing. Ambient mode (the default) has no such limit
        # because it matches the wake word against the transcript instead.
        keyword = str(ears_cfg.get("wake_word", "jarvis")).lower().strip()
        if keyword not in pvporcupine.KEYWORDS:
            print(f"Porcupine has no built-in keyword '{keyword}'; using 'jarvis'.")
            print("Ambient mode (the default, no --porcupine) understands 'jarbai'.")
            keyword = "jarvis"
        if not access_key or access_key.startswith("PASTE_YOUR"):
            raise WakeWordNotConfigured(
                "Porcupine access key missing. Sign up free at console.picovoice.ai "
                "and paste your key into config.yaml under ears.porcupine_access_key."
            )
        self.porcupine = pvporcupine.create(access_key=access_key, keywords=[keyword])
        self.keyword = keyword
        print(f"Wake word listener active. Say '{self.keyword}' to wake me, sir.")

    def wait(self):
        with sd.RawInputStream(
            samplerate=self.porcupine.sample_rate,
            blocksize=self.porcupine.frame_length,
            dtype="int16",
            channels=1,
        ) as stream:
            while True:
                data, _ = stream.read(self.porcupine.frame_length)
                pcm = np.frombuffer(data, dtype=np.int16)
                if self.porcupine.process(pcm) >= 0:
                    return

    def close(self):
        if self.porcupine is not None:
            self.porcupine.delete()
            self.porcupine = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
