import threading
import tkinter as tk
from tkinter import scrolledtext, ttk

from jarbai.utils.config import load_config
from jarbai.brain.llm import LLMClient
from jarbai.brain.memory import Memory
from jarbai.brain.router import Router
from jarbai.skills import get_skills
from jarbai.voice.tts import Speaker
from .reactor import Reactor, STATES


class JarbaiUI:
    STATE_COLORS = {
        "idle": "#7f8c8d",
        "listening": "#f39c12",
        "thinking": "#3498db",
        "speaking": "#2ecc71",
        "error": "#e74c3c",
    }

    def __init__(self, config, router, speaker):
        self.router = router
        self.speaker = speaker
        self.state = "idle"

        self.root = tk.Tk()
        self.root.title("JARBAI")
        self.root.geometry("520x640")
        self.root.configure(bg="#1b2733")
        self.root.minsize(420, 480)

        header = tk.Frame(self.root, bg="#1b2733")
        header.pack(fill=tk.X, padx=16, pady=(10, 0))
        self.reactor = Reactor(header, size=150, bg="#1b2733")
        self.reactor.pack(pady=(0, 2))
        self.status_label = tk.Label(header, text="online", font=("Segoe UI", 9),
                                     fg="#22d3ee", bg="#1b2733")
        self.status_label.pack()

        self.chat = scrolledtext.ScrolledText(
            self.root, wrap=tk.WORD, state=tk.DISABLED, font=("Segoe UI", 11),
            bg="#22303f", fg="#e0e6ed", relief=tk.FLAT, padx=12, pady=10,
        )
        self.chat.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
        self.chat.tag_configure("you", foreground="#95a5b3", justify="right")
        self.chat.tag_configure("jarbai", foreground="#eceff1", justify="left")

        entry_frame = tk.Frame(self.root, bg="#1b2733")
        entry_frame.pack(fill=tk.X, padx=16, pady=(0, 6))
        self.entry = ttk.Entry(entry_frame, font=("Segoe UI", 11))
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6)
        self.entry.bind("<Return>", self._submit)
        self.send_btn = tk.Button(entry_frame, text="Send", command=self._submit,
                                 bg="#0e7490", fg="white", relief=tk.FLAT,
                                 activebackground="#22d3ee", padx=14)
        self.send_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.status_bar = tk.Label(self.root, text="", anchor=tk.W, font=("Segoe UI", 9),
                                   fg="#5d7285", bg="#1b2733")
        self.status_bar.pack(fill=tk.X, padx=16, pady=(0, 8))

        self.dot_id = None
        self.set_state("idle")
        self.entry.focus_set()

    def set_state(self, state, message=None):
        self.state = state
        cfg = STATES.get(state, STATES["idle"])
        color = cfg["color"]
        self.reactor.set_state(state)
        self.status_label.configure(text=cfg["label"], fg=color)
        if message is not None:
            self.status_bar.configure(text=message)

    def add_message(self, who, text):
        tag = "you" if who == "you" else "jarbai"
        name = "You" if who == "you" else "JARBAI"
        self.chat.configure(state=tk.NORMAL)
        self.chat.insert(tk.END, f"{name}: ", tag)
        self.chat.insert(tk.END, f"{text}\n\n", tag)
        self.chat.configure(state=tk.DISABLED)
        self.chat.see(tk.END)

    def _submit(self, event=None):
        text = self.entry.get().strip()
        if not text or self.state == "thinking":
            return
        self.entry.delete(0, tk.END)
        self.add_message("you", text)
        self.send_btn.configure(state=tk.DISABLED)
        self.set_state("thinking", "Processing...")
        threading.Thread(target=self._think, args=(text,), daemon=True).start()

    def _think(self, text):
        try:
            reply = self.router.handle(text)
            error = None
        except Exception as exc:
            reply = f"Something went wrong, sir: {exc}"
            error = str(exc)
        self.root.after(0, lambda r=reply, e=error: self._deliver(r, e))

    def _deliver(self, reply, error=None):
        self.add_message("jarbai", reply)
        self.send_btn.configure(state=tk.NORMAL)
        self.set_state("error" if error else "idle", error or "")
        if self.speaker:
            threading.Thread(target=self._speak, args=(reply,), daemon=True).start()

    def _speak(self, text):
        self.root.after(0, lambda: self.set_state("speaking", "Speaking..."))
        try:
            self.speaker.speak(text)
        finally:
            self.root.after(0, lambda: self.set_state("idle", ""))

    def run(self):
        self.root.mainloop()


def main():
    config = load_config()
    brain_cfg = config.get("brain", {}) or {}
    llm = LLMClient(
        model=brain_cfg.get("model", "qwen2.5:3b"),
        base_url=brain_cfg.get("base_url", "http://localhost:11434"),
        temperature=brain_cfg.get("temperature", 0.4),
    )
    memory = Memory(max_turns=brain_cfg.get("max_history", 10))
    router = Router(llm=llm, memory=memory, skills=get_skills())
    speaker = Speaker(config)

    ui = JarbaiUI(config, router, speaker)
    ui.add_message("jarbai", "Good day, sir. All systems online. How may I assist you?")
    ui.run()


if __name__ == "__main__":
    main()
