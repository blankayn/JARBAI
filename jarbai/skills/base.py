class Skill:
    name = ""
    description = ""

    def execute(self, args):
        raise NotImplementedError


REGISTRY = {}


def register(skill_cls):
    instance = skill_cls()
    REGISTRY[instance.name] = instance
    return skill_cls
