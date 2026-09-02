import json
import mimetypes
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import psutil
import requests

ROOT = Path(__file__).resolve().parent
DASH = ROOT / "dashboard"
PORT = 8470
OLLAMA = "http://127.0.0.1:11434"   # not localhost: IPv6 fallback costs ~2s/call
MODEL = "qwen2.5:3b"
PERSONA = (
    "You are JARBAI, a highly capable British AI butler. "
    "Reply in one to three short, witty sentences. "
    "Address the user as 'sir'. Plain text only, no emojis, no markdown."
)

class _Sampler(threading.Thread):
    """Poll CPU and network on a fixed cadence, off the request path.

    psutil.cpu_percent(interval=None) stores its sampling window in module
    globals, so two concurrent requests (a refresh, a second tab) steal each
    other's window and read 0.0 or 100.0. The network counters had the same
    race. Sampling in one thread and serving the cached value fixes both.
    """

    INTERVAL = 1.0
    PROC_EVERY = 2          # scan processes every Nth tick - it is the slow part

    def __init__(self):
        super().__init__(daemon=True)
        self._lock = threading.Lock()
        self._cpu = 0.0
        self._cores = [0.0] * (psutil.cpu_count() or 1)
        self._up = 0.0
        self._down = 0.0
        self._procs = []
        self._net = psutil.net_io_counters()
        self._net_t = time.time()

    @staticmethod
    def _scan_procs():
        """Top 8 processes by RSS.

        Asks process_iter for memory_info directly so psutil batches the work;
        calling proc.memory_info() separately opens a fresh Windows handle per
        process, which takes seconds when AV or OneDrive is busy.
        """
        rows = []
        for proc in psutil.process_iter(["pid", "name", "memory_info"]):
            mem = proc.info.get("memory_info")
            if mem is None:
                continue
            rows.append((mem.rss, proc.info["pid"], proc.info["name"] or "?"))
        rows.sort(reverse=True)
        return [
            {"pid": pid, "name": name[:20], "mem": round(rss / 2**20, 1)}
            for rss, pid, name in rows[:8]
        ]

    def run(self):
        tick = 0
        while True:
            # blocking interval: this thread is the only caller, so no race
            cores = psutil.cpu_percent(interval=self.INTERVAL, percpu=True)
            cpu = sum(cores) / len(cores) if cores else 0.0
            net = psutil.net_io_counters()
            now = time.time()
            dt = max(now - self._net_t, 1e-6)
            down = max(0.0, (net.bytes_recv - self._net.bytes_recv) / dt)
            up = max(0.0, (net.bytes_sent - self._net.bytes_sent) / dt)
            self._net, self._net_t = net, now

            procs = None
            if tick % self.PROC_EVERY == 0:
                try:
                    procs = self._scan_procs()
                except Exception:
                    procs = []
            tick += 1

            with self._lock:
                self._cpu, self._cores = cpu, cores
                self._up, self._down = up, down
                if procs is not None:
                    self._procs = procs

    def read(self):
        with self._lock:
            return self._cpu, list(self._cores), self._up, self._down, list(self._procs)


_sampler = _Sampler()
_sampler.start()

# Reminder events pushed to every connected dashboard (SSE), plus the checker
# thread that fires them on time. _notify_reminders is what bridges the two:
# the checker calls it, and it fans out to both the browser and Python
# callbacks (used by the voice loop's TTS).
_event_lock = threading.Lock()
_event_queues = []


def _subscribe_events():
    import queue

    q = queue.Queue(maxsize=50)
    with _event_lock:
        _event_queues.append(q)
    return q


def _unsubscribe_events(q):
    with _event_lock:
        try:
            _event_queues.remove(q)
        except ValueError:
            pass


def _push_event(kind, data):
    with _event_lock:
        for q in list(_event_queues):
            try:
                q.put_nowait((kind, data))
            except Exception:
                pass          # a full queue means a dead client; it will be GC'd


def _notify_reminders(what):
    _push_event("reminder", {"what": what})
    say = _reminder_sink
    if say:
        try:
            say(what)
        except Exception:
            pass


# set by the voice loop (main.py) so reminders are spoken aloud too
_reminder_sink = None


def set_reminder_sink(fn):
    global _reminder_sink
    _reminder_sink = fn


def _start_reminders():
    from jarbai.skills import reminders as rem

    rem.on_due(_notify_reminders)
    rem.start_checker()


def _watch_settings():
    """Rebuild the router the moment settings.json changes.

    The dashboard's brain switch writes settings.json; without a watcher the
    change only takes effect on the next /api/ask, which is fine, but a
    stale router could also serve one request with the previous brain. A 2s
    poll on a stat call is cheap and makes the switch feel instant.
    """
    import threading as _t

    path = ROOT / "settings.json"
    last = path.stat().st_mtime if path.exists() else 0

    def watch():
        nonlocal last
        while True:
            time.sleep(2)
            try:
                mtime = path.stat().st_mtime if path.exists() else 0
            except OSError:
                continue
            if mtime != last:
                last = mtime
                global _router, _active_brain
                with _router_lock:
                    _router = None
                    _active_brain = None

    _t.Thread(target=watch, daemon=True).start()

# The router is what gives the dashboard access to the skills. Built lazily so
# a missing model or config cannot stop the server from serving the UI, and
# guarded by a lock because Memory is mutated per turn and requests are threaded.
_router = None
_router_lock = threading.Lock()
_active_brain = None      # "cloud" or "local" - whichever answered last


def _ollama_up():
    try:
        requests.get(f"{OLLAMA}/api/tags", timeout=1.5).raise_for_status()
        return True
    except requests.RequestException:
        return False


def get_router():
    global _router, _active_brain
    if _router is None:
        from jarbai.brain.memory import Memory
        from jarbai.brain.providers import make_llm
        from jarbai.brain.router import Router
        from jarbai.skills import get_skills
        from jarbai.utils.config import load_config

        cfg = load_config(str(ROOT / "config.yaml"))
        brain = cfg.get("brain", {}) or {}
        def note(where):
            global _active_brain
            _active_brain = where

        llm = make_llm(cfg, on_switch=note)
        # AutoClient only knows which brain it used after a call; a client
        # pinned to one provider is known straight away.
        _active_brain = {"LLMClient": "local", "GeminiClient": "cloud"}.get(
            type(llm).__name__)
        _router = Router(
            llm=llm,
            memory=Memory(max_turns=brain.get("max_history", 10)),
            skills=get_skills(),
        )
    return _router

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")


def _volume_action(action):
    """Run a pycaw volume action with COM set up for the calling thread.

    ThreadingHTTPServer hands every request to a fresh thread, and COM must be
    initialised on each one, so a shared endpoint object raises
    "CoInitialize has not been called" on the second request onward.
    """
    import comtypes
    from pycaw.pycaw import AudioUtilities

    comtypes.CoInitialize()
    try:
        vol = AudioUtilities.GetSpeakers().EndpointVolume
        if action == "mute":
            state = not vol.GetMute()
            vol.SetMute(state, None)
            return "Audio muted" if state else "Audio unmuted"
        level = vol.GetMasterVolumeLevelScalar()
        level = min(1.0, level + 0.1) if action == "vol_up" else max(0.0, level - 0.1)
        vol.SetMasterVolumeLevelScalar(level, None)
        return f"Volume at {round(level * 100)} percent"
    finally:
        comtypes.CoUninitialize()


class Handler(BaseHTTPRequestHandler):
    server_version = "JARBAI/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, obj, status=200):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path):
        try:
            data = path.read_bytes()
        except OSError:
            self._send_json({"ok": False, "error": "File not found"}, 404)
            return
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/stats":
            self._stats()
        elif url.path == "/api/weather":
            self._weather(url)
        elif url.path == "/api/skills":
            self._skills()
        elif url.path == "/api/reminders":
            self._list_reminders()
        elif url.path == "/api/events":
            self._events()
        elif url.path == "/api/settings":
            self._get_settings()
        else:
            self._static(url)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            body = {}
        if self.path == "/api/ask":
            self._ask(body)
        elif self.path == "/api/command":
            self._command(body)
        elif self.path == "/api/settings":
            self._set_settings(body)
        elif self.path == "/api/reminders":
            self._add_reminder(body)
        elif self.path == "/api/reminders/clear":
            self._clear_reminders(body)
        else:
            self._send_json({"ok": False, "error": "Unknown endpoint"}, 404)

    def _static(self, url):
        rel = url.path.lstrip("/") or "index.html"
        path = (DASH / rel).resolve()
        if not str(path).startswith(str(DASH)) or not path.is_file():
            path = DASH / "index.html"
        self._send_file(path)

    def _stats(self):
        cpu, cores, up, down, procs = _sampler.read()
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        now = time.time()
        uptime = int(now - psutil.boot_time())
        self._send_json(
            {
                "ok": True,
                "cpu": round(cpu, 1),
                "cores": [round(c, 1) for c in cores],
                "ram": mem.percent,
                "ramUsed": round(mem.used / 2**30, 1),
                "ramTotal": round(mem.total / 2**30, 1),
                "disk": disk.percent,
                "up": up,
                "down": down,
                "uptime": uptime,
                "procs": procs,
            }
        )

    def _weather(self, url):
        city = (parse_qs(url.query).get("city") or ["Manila"])[0]
        try:
            geo = requests.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1},
                timeout=10,
            ).json()
            if not geo.get("results"):
                self._send_json({"ok": False, "error": f"City '{city}' not found"})
                return
            loc = geo["results"][0]
            wx = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": loc["latitude"],
                    "longitude": loc["longitude"],
                    "current": "temperature_2m,weather_code,wind_speed_10m,"
                    "relative_humidity_2m,apparent_temperature",
                },
                timeout=10,
            ).json()
            cur = wx.get("current", {})
            self._send_json(
                {
                    "ok": True,
                    "city": loc["name"],
                    "temp": cur.get("temperature_2m"),
                    "code": cur.get("weather_code"),
                    "wind": cur.get("wind_speed_10m"),
                    "humidity": cur.get("relative_humidity_2m"),
                    "feels": cur.get("apparent_temperature"),
                }
            )
        except requests.RequestException as exc:
            self._send_json({"ok": False, "error": f"Weather link down: {exc}"})

    def _ask(self, body):
        text = (body.get("text") or "").strip()
        if not text:
            self._send_json({"ok": False, "error": "Empty command"})
            return

        # Server-sent events: partial previews stream in as they are produced,
        # then a final event carries the authoritative reply. The client falls
        # back to plain JSON if the connection is not EventSource-compatible.
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        def emit(event, data):
            payload = json.dumps(data)
            self.wfile.write(f"event: {event}\ndata: {payload}\n\n".encode("utf-8"))

        # client disconnects show up as broken pipes; never crash the thread
        def safe_emit(event, data):
            try:
                emit(event, data)
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, OSError):
                return False

        last_preview = None
        try:
            with _router_lock:
                for preview, final in get_router().handle_stream(text):
                    if preview is not None and preview != last_preview:
                        last_preview = preview
                        if not safe_emit("delta", {"text": preview}):
                            return
            reply = last_preview or "..."
        except Exception as exc:
            safe_emit("error", {"error": f"Skill routing failed: {exc}"})
            return
        safe_emit("final", {"ok": True, "reply": reply, "brain": _active_brain})

    def _skills(self):
        """Live capabilities, read from the registry - the panel data source."""
        try:
            skills = get_router().skills
            payload = [
                {"name": name, "description": skill.description}
                for name, skill in sorted(skills.items())
            ]
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)})
            return
        self._send_json({"ok": True, "skills": payload})

    def _list_reminders(self):
        from datetime import datetime

        from jarbai.skills.reminders import REMINDERS, _lock

        with _lock:
            pending = [
                {"when": r["when"].isoformat(), "what": r["what"], "said": r["said"]}
                for r in REMINDERS if not r["said"]
            ]
        self._send_json({"ok": True, "reminders": pending, "now": datetime.now().isoformat()})

    def _add_reminder(self, body):
        from datetime import datetime

        from jarbai.skills.reminders import add, parse_when

        text = (body.get("text") or "").strip()
        if not text:
            self._send_json({"ok": False, "error": "Empty reminder"})
            return
        when, what = parse_when(text)
        if when is None:
            self._send_json({"ok": False,
                             "error": "Could not read the time. Try 'in 10 minutes' or 'tomorrow at 9am'."})
            return
        add(when, what)
        self._send_json({"ok": True, "when": when.isoformat(), "what": what})

    def _clear_reminders(self, body):
        from jarbai.skills.reminders import cancel_all, _persist

        count = cancel_all()
        _persist()
        self._send_json({"ok": True, "cancelled": count})

    def _events(self):
        """SSE channel: reminder fires are pushed here as they happen."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        queue = _subscribe_events()
        try:
            # an initial ping both confirms the stream and flushes headers
            self.wfile.write(b"event: ping\ndata: {}\n\n")
            self.wfile.flush()
            while True:
                try:
                    kind, data = queue.get(timeout=20)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    continue
                payload = json.dumps(data)
                self.wfile.write(f"event: {kind}\ndata: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            _unsubscribe_events(queue)

    def _get_settings(self):
        import os

        from jarbai.utils.config import load_config, mask_secret

        cfg = load_config(str(ROOT / "config.yaml"))
        brain = cfg.get("brain", {}) or {}
        ears = cfg.get("ears", {}) or {}
        self._send_json({
            "ok": True,
            "provider": brain.get("provider", "auto"),
            "sttProvider": ears.get("stt_provider", "auto"),
            "localModel": brain.get("model", MODEL),
            "cloudModel": brain.get("gemini_model", ""),
            "hasKey": bool(os.environ.get("GEMINI_API_KEY")),
            # a masked hint only - the key itself is never sent to the browser
            "keyHint": mask_secret(os.environ.get("GEMINI_API_KEY", "")),
            "active": _active_brain,
            "ollamaUp": _ollama_up(),
        })

    def _set_settings(self, body):
        global _router, _active_brain

        from jarbai.utils.config import save_env_var, save_override

        if "geminiKey" in body:
            self._set_key(body)
            return

        allowed = {"provider": "brain.provider", "sttProvider": "ears.stt_provider"}
        valid = {"auto", "local", "cloud"}
        changed = {}
        for key, dotted in allowed.items():
            if key not in body:
                continue
            value = str(body[key]).lower().strip()
            if value not in valid:
                self._send_json({"ok": False, "error": f"{key} must be auto, local or cloud"})
                return
            save_override(dotted, value)
            changed[key] = value
        if not changed:
            self._send_json({"ok": False, "error": "nothing to change"})
            return
        with _router_lock:
            _router = None            # rebuilt from the new settings next turn
            _active_brain = None
        self._send_json({"ok": True, "changed": changed})

    def _set_key(self, body):
        """Store (or clear) the Gemini API key, after checking it works."""
        global _router, _active_brain

        from jarbai.utils.config import mask_secret, save_env_var

        key = str(body.get("geminiKey") or "").strip()

        if not key:                       # empty means "forget my key"
            save_env_var("GEMINI_API_KEY", "")
            with _router_lock:
                _router = None
                _active_brain = None
            self._send_json({"ok": True, "hasKey": False, "detail": "API key removed."})
            return

        try:
            probe = requests.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": key}, timeout=20,
            )
        except requests.RequestException as exc:
            self._send_json({"ok": False, "error": f"Could not reach Google: {exc}"})
            return
        if probe.status_code != 200:
            reason = "The key was rejected by Google."
            try:
                reason = probe.json().get("error", {}).get("message", reason)
            except ValueError:
                pass
            # never echo the key back, even inside an error message
            self._send_json({"ok": False, "error": reason.replace(key, "<key>")[:200]})
            return

        save_env_var("GEMINI_API_KEY", key)
        with _router_lock:
            _router = None                # rebuild with the new credentials
            _active_brain = None
        self._send_json({
            "ok": True, "hasKey": True,
            "keyHint": mask_secret(key),
            "detail": "API key verified and saved.",
        })

    def _command(self, body):
        action = body.get("action")
        try:
            if action in ("mute", "vol_up", "vol_down"):
                detail = _volume_action(action)
            elif action == "lock":
                subprocess.run(
                    ["rundll32.exe", "user32.dll,LockWorkStation"], check=False
                )
                detail = "Workstation lock initiated"
            elif action == "screenshot":
                import pyautogui

                folder = ROOT / "Screenshots"
                folder.mkdir(exist_ok=True)
                path = folder / f"dash_{int(time.time())}.png"
                pyautogui.screenshot(str(path))
                detail = f"Screenshot captured: {path.name}"
            elif action == "browser":
                webbrowser.open("https://www.google.com")
                detail = "Browser launched"
            else:
                self._send_json({"ok": False, "error": f"Unknown action '{action}'"})
                return
            self._send_json({"ok": True, "detail": detail})
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)})


class Server(ThreadingHTTPServer):
    # Windows honours SO_REUSEADDR differently from Linux: with it enabled two
    # processes can bind 8470 at once and requests are split between them at
    # random, so a half-dead instance silently answers some of them. Refusing
    # reuse makes a duplicate start fail loudly instead.
    allow_reuse_address = False
    daemon_threads = True


def main():
    try:
        server = Server(("127.0.0.1", PORT), Handler)
    except OSError as exc:
        print(f"Port {PORT} is already in use - JARBAI is probably running. ({exc})")
        return 1
    try:
        _start_reminders()
        _watch_settings()
    except Exception as exc:
        print(f"reminders/events did not start: {exc}")
    print(f"JARBAI dashboard: http://127.0.0.1:{PORT}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
