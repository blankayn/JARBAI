# J.A.R.B.A.I

*Just A Rather Brilliant Artificial Intelligence* — a local voice assistant and
dashboard for Windows. Talk to it, and it opens apps, edits files, reads your
screen and answers questions. It works with no internet at all.

---

## Setting it up on a new machine

Copy this folder to the new PC, then in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
```

That creates the virtualenv, installs everything, generates the icon and adds
the **JARBAI** desktop shortcut. It takes a few minutes the first time.

Then double-click **JARBAI**, click the **gear icon**, and paste your API key.
That's it — no files to edit.

### What setup.ps1 needs

| | |
|---|---|
| **Python 3.10+** | from python.org — tick *Add Python to PATH* during install |
| **Ollama** *(optional)* | from [ollama.com/download](https://ollama.com/download), for the offline brain |

If Ollama is missing, setup still finishes — JARBAI just needs the cloud brain
to answer until you install it.

---

## The two brains

JARBAI can think locally or in the cloud. Switch any time with the
**BRAIN** control in the top bar — no restart needed.

| Mode | Uses | Speed | Internet | Privacy |
|---|---|---|---|---|
| **auto** *(default)* | Cloud, local when offline | fast | not required | mixed |
| **cloud** | Gemini flash-lite | ~1.7s | required | sent to Google |
| **local** | Ollama qwen2.5:3b | ~6s | none | stays on your PC |

**auto** is the useful one: it uses the cloud while you have internet and
silently falls back to the local model when you don't. The BRAIN button for
whichever brain actually answered gets a green underline, so you can always
see which one is talking.

### Getting an API key

Optional — skip it entirely if you only want the offline brain.

1. Go to **[aistudio.google.com/apikey](https://aistudio.google.com/apikey)** and sign in
2. Click **Create API key** (the free tier is plenty)
3. Copy it, click the **gear icon** in JARBAI, paste, press **SAVE & TEST**

The key is verified against Google before it's saved, so a bad paste tells you
immediately instead of failing later. It's stored in `.env`, which is
gitignored and never committed. **Remove key** deletes it and drops you to
local-only.

> Treat the key like a password. If it ever leaks, revoke it at the same page
> and paste a new one.

---

## Talking to it

The mic is always on — there is no button to press.

- **"Jarbai, what time is it"** — say the name, then the command
- **Snap your fingers** → *"Yes, sir?"* → then speak
- Or type in the command bar

Speech recognition mangles an invented name, so JARBAI also answers to
*jarbi*, *jar by*, *jar bye* and *jarvis*.

### If snaps don't register

Microphone gain varies between machines. Calibrate yours:

```powershell
.venv\Scripts\python.exe main.py --tune-snap
```

Snap, clap and talk. It prints `peak / crest / high%` for each sound. Set
`ears.snap.min_peak` in `config.yaml` below your snaps and above everything else.

---

## What it can do

**Instant** (no model involved) — time, open/close apps, volume, mute, lock,
screenshot, web search, weather, read/list files, read the screen.

**Via the model** — writing and editing files, answering questions about
what's on screen, and ordinary conversation.

Ask it to *"open blender"*, *"make a file called ideas.txt saying test"*,
*"what's on my screen"*, *"search for cheap flights"*, or *"what's the weather
in Cebu"*.

File skills are sandboxed to `~/Documents/JARBAI` — JARBAI cannot read or write
outside that folder. Overwrites keep a `.bak`, and deletes go to `_trash`.

---

## Running it

Double-click **JARBAI**. That starts Ollama, the dashboard window and the voice
listener together.

From a terminal instead:

```powershell
.\start_jarbai.ps1                     # same as the shortcut
.venv\Scripts\python.exe main.py       # voice only
.venv\Scripts\python.exe main.py --text  # typing only, no microphone
```

---

## Where things live

| File | |
|---|---|
| `config.yaml` | models, wake word, snap sensitivity — safe to edit |
| `.env` | your API key — gitignored, never commit it |
| `settings.json` | brain choice made in the UI — overrides config.yaml |
| `dashboard/` | the web UI |
| `jarbai/skills/` | one file per capability; add a `Skill` subclass to extend |
| `~/Documents/JARBAI` | the file workspace JARBAI is allowed to touch |

Run the tests with:

```powershell
.venv\Scripts\python.exe -m pytest -q
```

---

## Troubleshooting

**"Language core offline"** — Ollama isn't running and there's no API key.
Start Ollama, or add a key in Setup.

**Voice does nothing** — check the console window that opens with JARBAI; it
prints everything it hears. Windows may also be blocking microphone access
under Settings → Privacy → Microphone.

**Replies are slow** — you're on the local brain. `qwen2.5:3b` generates at
about 5 tokens/sec on a low-power laptop CPU. Switch BRAIN to **cloud**.

**Snap fires by itself** — usually keyboard clicks. Raise `ears.snap.min_peak`,
or set `ears.snap_enabled: false` to use the wake word only.
