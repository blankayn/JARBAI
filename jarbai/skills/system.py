import datetime
import subprocess
import time
from pathlib import Path

import pyautogui

from .base import Skill, register


@register
class GetTime(Skill):
    name = "get_time"
    description = "Report the current time and date. args: {}"

    def execute(self, args):
        now = datetime.datetime.now()
        hour = now.strftime("%I").lstrip("0")
        return (
            f"It's {hour}:{now.strftime('%M')} {now.strftime('%p')}, "
            f"{now.strftime('%A')} the {int(now.strftime('%d'))} of {now.strftime('%B')}, sir."
        )


@register
class LockPC(Skill):
    name = "lock_pc"
    description = "Lock the workstation. args: {}"

    def execute(self, args):
        subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=False)
        return "Locking the workstation, sir."


@register
class Screenshot(Skill):
    name = "take_screenshot"
    description = "Take a screenshot and save it to the Screenshots folder. args: {}"

    def execute(self, args):
        folder = Path("Screenshots")
        folder.mkdir(exist_ok=True)
        path = folder / f"screenshot_{int(time.time())}.png"
        pyautogui.screenshot(str(path))
        return f"Screenshot saved, sir: {path}"


@register
class ShutdownPC(Skill):
    name = "shutdown_pc"
    description = "Begin a 30-second shutdown. Run 'shutdown /a' to abort. args: {}"

    def execute(self, args):
        subprocess.run(["shutdown", "/s", "/t", "30"], check=False)
        return "Shutting down in 30 seconds, sir. Run shutdown /a to abort."
