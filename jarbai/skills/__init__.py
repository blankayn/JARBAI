from .base import REGISTRY, Skill, register
from . import apps, files, reminders, system, vision, volume, weather, web


def get_skills():
    return dict(REGISTRY)
