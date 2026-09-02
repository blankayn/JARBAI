"""File skills, confined to a workspace folder.

Everything here resolves paths against files.workspace from config.yaml and
refuses anything that escapes it. A 3B model picks these arguments, so the
sandbox is the whole safety story - never widen it to bare absolute paths.
Overwrites keep a .bak, and deletes go to a _trash folder rather than
vanishing, so a wrong call is always recoverable.
"""

import shutil
import time
from pathlib import Path

from ..utils.config import load_config
from .base import Skill, register

MAX_READ = 20_000          # characters returned to the model
MAX_WRITE = 200_000
TRASH = "_trash"


def workspace():
    root = load_config().get("files.workspace") or "~/Documents/JARBAI"
    path = Path(root).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def resolve(relative, must_exist=False):
    """Resolve inside the workspace or raise."""
    if not relative or not str(relative).strip():
        raise ValueError("no file name given")
    root = workspace()
    candidate = (root / str(relative).strip()).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("that path is outside the workspace")
    if must_exist and not candidate.is_file():
        raise FileNotFoundError(f"{relative} does not exist")
    return candidate


def _rel(path):
    try:
        return str(path.relative_to(workspace()))
    except ValueError:
        return str(path)


def _backup(path):
    if path.is_file():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))


@register
class ListFiles(Skill):
    name = "list_files"
    description = 'List files in the workspace. args: {"folder": "optional subfolder"}'

    def execute(self, args):
        folder = (args or {}).get("folder", "") or ""
        try:
            target = resolve(folder) if folder else workspace()
        except ValueError as exc:
            return f"I can't look there, sir: {exc}."
        if not target.is_dir():
            return f"{folder} isn't a folder, sir."
        entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        entries = [e for e in entries if e.name != TRASH][:25]
        if not entries:
            return "That folder is empty, sir."
        listed = ", ".join(f"{e.name}/" if e.is_dir() else e.name for e in entries)
        return f"In {_rel(target) or 'the workspace'}: {listed}"


@register
class FindFile(Skill):
    name = "find_file"
    description = 'Search the workspace for files by name. args: {"query": "part of a file name"}'

    def execute(self, args):
        query = ((args or {}).get("query") or "").strip().lower()
        if not query:
            return "What should I search for, sir?"
        hits = [
            _rel(p) for p in workspace().rglob("*")
            if p.is_file() and query in p.name.lower()
            and TRASH not in p.parts and p.suffix != ".bak"
        ][:15]
        if not hits:
            return f"I found nothing matching '{query}', sir."
        return f"Found {len(hits)}: " + ", ".join(hits)


@register
class ReadFile(Skill):
    name = "read_file"
    description = 'Read a text file from the workspace. args: {"path": "notes.txt"}'

    def execute(self, args):
        try:
            path = resolve((args or {}).get("path"), must_exist=True)
            text = path.read_text(encoding="utf-8", errors="replace")
        except (ValueError, FileNotFoundError) as exc:
            return f"I couldn't read that, sir: {exc}."
        except OSError as exc:
            return f"I couldn't read that, sir: {exc}"
        if len(text) > MAX_READ:
            text = text[:MAX_READ] + "\n... (truncated)"
        return text or "That file is empty, sir."


@register
class WriteFile(Skill):
    name = "write_file"
    description = (
        'Create a file, or replace its whole contents. Keeps a .bak of the old version. '
        'args: {"path": "notes.txt", "content": "text to write"}'
    )

    def execute(self, args):
        args = args or {}
        content = args.get("content")
        if content is None:
            return "What should I write in it, sir?"
        content = str(content)
        if len(content) > MAX_WRITE:
            return "That's larger than I'm willing to write in one go, sir."
        try:
            path = resolve(args.get("path"))
            path.parent.mkdir(parents=True, exist_ok=True)
            existed = path.is_file()
            _backup(path)
            path.write_text(content, encoding="utf-8")
        except ValueError as exc:
            return f"I can't write there, sir: {exc}."
        except OSError as exc:
            return f"I couldn't write that, sir: {exc}"
        verb = "Updated" if existed else "Created"
        return f"{verb} {_rel(path)}, sir."


@register
class AppendFile(Skill):
    name = "append_file"
    description = 'Add text to the end of a file. args: {"path": "notes.txt", "content": "text"}'

    def execute(self, args):
        args = args or {}
        content = args.get("content")
        if content is None:
            return "What should I add, sir?"
        try:
            path = resolve(args.get("path"))
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(("" if str(content).startswith("\n") else "\n") + str(content))
        except ValueError as exc:
            return f"I can't write there, sir: {exc}."
        except OSError as exc:
            return f"I couldn't append to that, sir: {exc}"
        return f"Appended to {_rel(path)}, sir."


@register
class EditFile(Skill):
    name = "edit_file"
    description = (
        'Replace text inside an existing file. Keeps a .bak. '
        'args: {"path": "notes.txt", "find": "old text", "replace": "new text"}'
    )

    def execute(self, args):
        args = args or {}
        find = args.get("find")
        replace = args.get("replace")
        if not find:
            return "What text should I look for, sir?"
        if replace is None:
            return "What should I replace it with, sir?"
        try:
            path = resolve(args.get("path"), must_exist=True)
            text = path.read_text(encoding="utf-8", errors="replace")
        except (ValueError, FileNotFoundError) as exc:
            return f"I couldn't edit that, sir: {exc}."
        except OSError as exc:
            return f"I couldn't edit that, sir: {exc}"
        count = text.count(str(find))
        if not count:
            return f"I couldn't find that text in {_rel(path)}, sir."
        _backup(path)
        path.write_text(text.replace(str(find), str(replace)), encoding="utf-8")
        return f"Replaced {count} occurrence(s) in {_rel(path)}, sir."


@register
class DeleteFile(Skill):
    name = "delete_file"
    description = 'Move a workspace file to the _trash folder. args: {"path": "notes.txt"}'

    def execute(self, args):
        try:
            path = resolve((args or {}).get("path"), must_exist=True)
        except (ValueError, FileNotFoundError) as exc:
            return f"I couldn't delete that, sir: {exc}."
        trash = workspace() / TRASH
        trash.mkdir(exist_ok=True)
        try:
            shutil.move(str(path), str(trash / f"{int(time.time())}_{path.name}"))
        except OSError as exc:
            return f"I couldn't delete that, sir: {exc}"
        return f"Moved {_rel(path)} to {TRASH}, sir. Nothing is permanently gone."


@register
class WorkspacePath(Skill):
    name = "workspace_path"
    description = "Say where the file workspace folder is. args: {}"

    def execute(self, args):
        return f"My workspace is {workspace()}, sir."
