import argparse
import sys

from jarbai.utils.config import load_config
from jarbai.brain.providers import make_llm
from jarbai.brain.memory import Memory
from jarbai.brain.router import Router
from jarbai.skills import get_skills


def build_router(config):
    brain_cfg = config.get("brain", {}) or {}
    llm = make_llm(config, on_switch=lambda where: print(f"[brain: {where}]"))
    memory = Memory(max_turns=brain_cfg.get("max_history", 10))
    return Router(llm=llm, memory=memory, skills=get_skills())


def run_text_mode(config):
    router = build_router(config)
    print("JARBAI text mode. Type 'exit' to quit.\n")
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit", "goodbye", "bye"}:
            break
        try:
            reply = router.handle(user_input)
        except Exception as exc:
            reply = f"Something went wrong, sir: {exc}"
        print(f"JARBAI: {reply}\n")


# Whisper hears an invented name loosely; accept what it actually produces.
WAKE_WORDS = ["jarbai", "jarbi", "jar bai", "jar by", "jar bye", "jarvai", "jarvis", "jarvi", "jabai", "job ai"]


def run_snap_tuning(config):
    """Print snap metrics so the thresholds can be matched to your microphone."""
    import numpy as np

    from jarbai.ears.ambient import BLOCK, AmbientListener

    print("Snap tuning. Snap your fingers a few times, clap, talk, then Ctrl+C.")
    print("Set ears.snap.min_peak in config.yaml below your snaps, above everything else.\n")
    print(f"{'peak':>7} {'crest':>7} {'high':>6}   verdict")
    with AmbientListener(config) as ears:
        try:
            while True:
                data, _ = ears.stream.read(BLOCK)
                chunk = data.flatten()
                peak, crest, high = ears.snap_metrics(chunk)
                if peak < 0.05:
                    continue
                rms = float(np.sqrt(np.mean(np.square(chunk))))
                verdict = "SNAP" if ears._is_snap(chunk, rms) else "-"
                print(f"{peak:7.3f} {crest:7.1f} {high*100:5.0f}%   {verdict}")
        except KeyboardInterrupt:
            print("\nDone, sir.")


def run_ambient_mode(config, speak=True):
    """Always listening: say "Jarbai ..." or snap. No wake-word key needed."""
    from jarbai.ears.ambient import AmbientListener, command_after_wake
    from jarbai.ears.stt import Transcriber
    from jarbai.skills import reminders as rem
    from jarbai.voice.tts import Speaker

    router = build_router(config)
    speaker = Speaker(config) if speak else None
    ears_cfg = config.get("ears", {}) or {}
    transcriber = Transcriber(config)
    # The ambient loop transcribes every utterance just to check for the wake
    # word, so it defaults to a smaller model than a deliberate command needs.
    transcriber.model_size = ears_cfg.get("ambient_model", "base")

    wake_words = list(WAKE_WORDS)
    configured = str(ears_cfg.get("wake_word", "") or "").lower().strip()
    if configured and configured not in wake_words:
        wake_words.insert(0, configured)

    listener = AmbientListener(config)

    def say(text):
        print(f"JARBAI: {text}")
        if speaker:
            listener.mute()          # never transcribe our own reply
            try:
                speaker.speak(text)
            finally:
                listener.unmute()

    # Reminders fire while JARBAI listens; speak them through the same path
    # as normal replies, with the mic muted so it never hears itself.
    def announce_reminder(what):
        say(f"Reminder, sir: {what}")

    rem.on_due(announce_reminder)
    rem.start_checker()

    def respond(text):
        print(f"You: {text}")
        try:
            reply = router.handle(text)
        except Exception as exc:
            reply = f"Something went wrong, sir: {exc}"
        say(reply)

    print("Loading speech model...")
    transcriber._load()
    if speaker:
        # cache the acknowledgements said every time, so they play instantly
        speaker.prewarm([config.get("behavior.wake_response", "Yes, sir?"),
                         "Yes, sir?",
                         'Ambient mode online. Say "Jarbai", or snap, sir.'])

    with listener:
        say('Ambient mode online. Say "Jarbai", or snap, sir.')
        for kind, audio in listener.listen():
            if kind == "snap":
                say("Yes, sir?")
                follow = listener.next_utterance()
                if follow is None:
                    continue
                text = transcriber.transcribe(follow).strip()
                if text:
                    respond(text)
                continue

            try:
                heard = transcriber.transcribe(audio).strip()
            except Exception as exc:
                print(f"(transcription failed: {exc})")
                continue
            if not heard:
                continue

            command = command_after_wake(heard, wake_words)
            if command is None:
                continue                      # wake word not spoken - ignore
            if command:
                respond(command)
            else:
                say(config.get("behavior.wake_response", "Yes, sir?"))
                follow = listener.next_utterance()
                if follow is None:
                    continue
                text = transcriber.transcribe(follow).strip()
                if text:
                    respond(text)


def run_voice_mode(config, speak=True):
    from jarbai.ears.recorder import Recorder
    from jarbai.ears.stt import Transcriber
    from jarbai.ears.wake_word import WakeWordListener, WakeWordNotConfigured
    from jarbai.voice.tts import Speaker

    router = build_router(config)
    speaker = Speaker(config) if speak else None
    recorder = Recorder(config)
    transcriber = Transcriber(config)

    def say(text):
        print(f"JARBAI: {text}")
        if speaker:
            speaker.speak(text)

    try:
        wake = WakeWordListener(config)
    except WakeWordNotConfigured as exc:
        print(exc)
        print("Falling back to text mode.\n")
        run_text_mode(config)
        return

    say("JARBAI online. Say the wake word when you need me, sir.")
    with wake:
        while True:
            wake.wait()
            say(config.get("behavior.wake_response", "Yes, sir?"))
            audio = recorder.record()
            if audio is None:
                say("I didn't catch that, sir.")
                continue
            try:
                text = transcriber.transcribe(audio)
            except Exception as exc:
                say(f"My speech recognition is unavailable, sir: {exc}")
                continue
            if not text:
                say("I couldn't understand that, sir.")
                continue
            print(f"You: {text}")
            try:
                reply = router.handle(text)
            except Exception as exc:
                reply = f"Something went wrong, sir: {exc}"
            say(reply)


def main():
    parser = argparse.ArgumentParser(description="JARBAI voice assistant")
    parser.add_argument("--text", action="store_true", help="text-only mode, no audio devices needed")
    parser.add_argument("--no-speak", action="store_true", help="run without spoken replies")
    parser.add_argument("--porcupine", action="store_true",
                        help="use the old Porcupine wake word instead of ambient listening")
    parser.add_argument("--tune-snap", action="store_true",
                        help="print snap metrics so you can calibrate ears.snap.* in config.yaml")
    args = parser.parse_args()

    try:
        config = load_config()
        if args.tune_snap:
            run_snap_tuning(config)
        elif args.text:
            run_text_mode(config)
        elif args.porcupine:
            run_voice_mode(config, speak=not args.no_speak)
        else:
            run_ambient_mode(config, speak=not args.no_speak)
    except KeyboardInterrupt:
        print("\nJARBAI shutting down, sir.")
        sys.exit(0)


if __name__ == "__main__":
    main()
