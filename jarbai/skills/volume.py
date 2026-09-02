from pycaw.pycaw import AudioUtilities

from .base import Skill, register


def _volume_interface():
    return AudioUtilities.GetSpeakers().EndpointVolume


@register
class SetVolume(Skill):
    name = "set_volume"
    description = 'Set the system volume. args: {"level": 0-100}'

    STEP = 10

    def execute(self, args):
        level = (args or {}).get("level")
        if level is None:
            return "What volume level would you like, sir?"

        interface = _volume_interface()
        # Accept relative steps as well as an absolute level, so "louder" and
        # "turn it down" work without first asking what the volume is.
        token = str(level).strip().lower()
        if token in ("+", "up", "louder", "increase"):
            level = round(interface.GetMasterVolumeLevelScalar() * 100) + self.STEP
        elif token in ("-", "down", "quieter", "decrease"):
            level = round(interface.GetMasterVolumeLevelScalar() * 100) - self.STEP
        try:
            level = max(0, min(100, int(level)))
        except (TypeError, ValueError):
            return "Please give me a number between 0 and 100, sir."
        interface.SetMasterVolumeLevelScalar(level / 100, None)
        return f"Volume set to {level} percent, sir."


@register
class GetVolume(Skill):
    name = "get_volume"
    description = "Report the current system volume. args: {}"

    def execute(self, args):
        level = round(_volume_interface().GetMasterVolumeLevelScalar() * 100)
        return f"Volume is currently at {level} percent, sir."


@register
class ToggleMute(Skill):
    name = "toggle_mute"
    description = "Toggle system audio mute. args: {}"

    def execute(self, args):
        interface = _volume_interface()
        new_state = not interface.GetMute()
        interface.SetMute(new_state, None)
        return "Muted, sir." if new_state else "Unmuted, sir."
