"""JARBAI desktop launcher.

Double-clicking the desktop shortcut runs this. It brings the whole stack up
and opens the dashboard as a chromeless app window, replacing the old Tk UI:

    1. start Ollama if it is not already listening (needed by /api/ask)
    2. start dashboard_server.py if port 8470 is free
    3. open the dashboard in an app-mode browser window

Run with pythonw.exe so nothing flashes a console. Because there is no console
to print to, failures are reported in a message box.
"""

import ctypes
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8470
URL = f"http://{HOST}:{PORT}"

OLLAMA_PORT = 11434
WINDOW = "1600,1000"

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008


def alert(message, title="JARBAI"):
    try:
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
    except Exception:
        pass


def port_open(port, timeout=0.35):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((HOST, port)) == 0


def wait_for(port, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if port_open(port):
            return True
        time.sleep(0.25)
    return False


def spawn(args, cwd=None):
    """Launch detached so JARBAI outlives this launcher process."""
    subprocess.Popen(
        [str(a) for a in args],
        cwd=str(cwd or ROOT),
        creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def python_exe():
    """Prefer the venv's pythonw.exe — console-free, with the deps installed."""
    for name in ("pythonw.exe", "python.exe"):
        candidate = ROOT / ".venv" / "Scripts" / name
        if candidate.exists():
            return candidate
    return Path(sys.executable)


def start_ollama():
    if port_open(OLLAMA_PORT):
        return
    local = os.environ.get("LOCALAPPDATA", "")
    exe = Path(local) / "Programs" / "Ollama" / "ollama.exe"
    if not exe.exists():
        return  # dashboard still works; only /api/ask needs it
    os.environ.setdefault("OLLAMA_LLM_LIBRARY", str(Path(local) / "Programs" / "Ollama" / "lib" / "ollama"))
    spawn([exe, "serve"])
    wait_for(OLLAMA_PORT, 20)


def start_server():
    if port_open(PORT):
        return True
    server = ROOT / "dashboard_server.py"
    if not server.exists():
        alert(f"dashboard_server.py is missing from\n{ROOT}")
        return False
    spawn([python_exe(), server])
    if wait_for(PORT, 25):
        return True
    alert(
        "The dashboard server did not come up on port 8470.\n\n"
        "Run this in the project folder to see the error:\n"
        r"  .venv\Scripts\python.exe dashboard_server.py"
    )
    return False


def voice_running():
    """True if the ambient listener is already up, so we never double-open the mic."""
    try:
        import psutil
    except ImportError:
        return False
    for proc in psutil.process_iter(["cmdline"]):
        try:
            cmd = proc.info.get("cmdline") or []
        except Exception:
            continue
        if any("main.py" in str(part) for part in cmd):
            return True
    return False


def start_voice():
    """Ambient listening, in a minimised console.

    Deliberately not hidden: the console is where you see what it heard, and
    closing that window is how you stop it listening.
    """
    if voice_running():
        return
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        return
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 7          # SW_SHOWMINNOACTIVE
    subprocess.Popen(
        [str(python), str(ROOT / "main.py")],
        cwd=str(ROOT),
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        startupinfo=startupinfo,
        close_fds=True,
    )


def browsers():
    """Edge first (config.yaml uses it), then Chrome, across install roots."""
    roots = [
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    rel = [
        Path("Microsoft") / "Edge" / "Application" / "msedge.exe",
        Path("Google") / "Chrome" / "Application" / "chrome.exe",
    ]
    for tail in rel:
        for root in roots:
            if not root:
                continue
            exe = Path(root) / tail
            if exe.exists():
                yield exe


def open_window():
    # --app strips the browser chrome, so it reads as a native JARBAI window
    for exe in browsers():
        spawn([exe, f"--app={URL}", f"--window-size={WINDOW}"])
        return True
    webbrowser.open(URL)
    return True


def main():
    start_ollama()
    if not start_server():   # blocks until the port actually accepts
        return 1
    open_window()
    start_voice()            # live mic: say "Jarbai ...", or snap
    return 0


if __name__ == "__main__":
    sys.exit(main())
