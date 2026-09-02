import os
import subprocess
from pathlib import Path

import psutil

from ..utils.config import load_config
from .base import Skill, register


def _start_menu_dirs():
    for var, tail in (
        ("APPDATA", r"Microsoft\Windows\Start Menu\Programs"),
        ("PROGRAMDATA", r"Microsoft\Windows\Start Menu\Programs"),
    ):
        root = os.environ.get(var)
        if root:
            path = Path(root) / tail
            if path.is_dir():
                yield path


def _find_shortcut(name):
    """Look for a Start Menu .lnk matching name, so any installed app opens.

    Exact stem match wins over a substring one, so "code" does not resolve to
    "Visual Studio Code Insiders" when plain VS Code is installed.
    """
    wanted = name.lower().removesuffix(".exe").strip()
    if not wanted:
        return None
    exact, partial = None, None
    for root in _start_menu_dirs():
        for lnk in root.rglob("*.lnk"):
            stem = lnk.stem.lower()
            if stem == wanted:
                exact = exact or lnk
            elif wanted in stem and partial is None:
                partial = lnk
    return exact or partial


def _resolve_target(name):
    apps_map = load_config().get("apps", {}) or {}
    mapped = apps_map.get(name.lower())
    if mapped:
        return mapped
    shortcut = _find_shortcut(name)
    return str(shortcut) if shortcut else name


@register
class OpenApp(Skill):
    name = "open_app"
    description = 'Open an application. args: {"name": "browser | editor | spotify | <executable name>"}'

    def execute(self, args):
        target = (args or {}).get("name", "").strip()
        if not target:
            return "Which application would you like me to open, sir?"
        exe = _resolve_target(target)
        try:
            subprocess.Popen(f'start "" "{exe}"', shell=True)
            return f"Opening {target}, sir."
        except Exception as exc:
            return f"I couldn't open {target}, sir. {exc}"


@register
class CloseApp(Skill):
    name = "close_app"
    description = 'Close a running application. args: {"name": "browser | editor | spotify | <executable name>"}'

    def execute(self, args):
        target = (args or {}).get("name", "").strip()
        if not target:
            return "Which application should I close, sir?"
        exe = _resolve_target(target)
        base = exe.lower().removesuffix(".exe")
        killed = 0
        for proc in psutil.process_iter(["name"]):
            try:
                proc_name = proc.info.get("name")
                if proc_name and proc_name.lower().removesuffix(".exe") == base:
                    proc.terminate()
                    killed += 1
            except (psutil.Error, psutil.AccessDenied):
                continue
        if killed:
            return f"Closed {killed} {target} process(es), sir."
        return f"{target} isn't running, sir."
