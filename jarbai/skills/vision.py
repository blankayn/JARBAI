"""Screen vision.

Uses the OCR engine built into Windows (Windows.Media.Ocr via winsdk) rather
than a vision model. For a screen full of text - a search result, an error
dialog, a document - OCR is far faster and reads the characters exactly,
where a small VLM would take tens of seconds and paraphrase them.

The capture happens in memory when you ask. Nothing is written to disk and no
screenshot button is involved.
"""

import asyncio
import threading

import pyautogui

from ..brain.llm import LLMClient, LLMUnavailable
from ..utils.config import load_config
from .base import Skill, register

MAX_TEXT = 6000


OCR_TIMEOUT = 30


def _ocr_sync(png_bytes):
    """Run the WinRT OCR pipeline: PNG bytes -> SoftwareBitmap -> text.

    Runs on its own thread that calls init_apartment() first: awaiting a WinRT
    IAsyncOperation needs the thread in an MTA apartment, and without it the
    await never completes. The thread is also a hard timeout boundary, so a
    wedged OCR call can never hang the dashboard request that triggered it.
    """
    out = {}

    def worker():
        try:
            from winsdk import system
            from winsdk.windows.graphics.imaging import BitmapDecoder
            from winsdk.windows.media.ocr import OcrEngine
            from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

            try:
                system.init_apartment()
            except Exception:
                pass  # already initialised on this thread

            async def run():
                stream = InMemoryRandomAccessStream()
                writer = DataWriter(stream)
                writer.write_bytes(png_bytes)
                await writer.store_async()
                await writer.flush_async()
                writer.detach_stream()
                stream.seek(0)

                decoder = await BitmapDecoder.create_async(stream)
                bitmap = await decoder.get_software_bitmap_async()

                engine = OcrEngine.try_create_from_user_profile_languages()
                if engine is None:
                    raise RuntimeError("no OCR language pack is installed")
                result = await engine.recognize_async(bitmap)
                return result.text or ""

            out["text"] = asyncio.run(run())
        except Exception as exc:
            out["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(OCR_TIMEOUT)
    if thread.is_alive():
        raise TimeoutError(f"OCR did not finish within {OCR_TIMEOUT}s")
    if "error" in out:
        raise out["error"]
    return out.get("text", "")


def read_screen_text():
    """Capture the screen and return whatever text is on it."""
    import io

    shot = pyautogui.screenshot()
    # OCR accuracy drops on very large images and the engine caps dimensions,
    # so keep it near 1080p rather than sending a raw 4K grab.
    if shot.width > 1920:
        ratio = 1920 / shot.width
        shot = shot.resize((1920, int(shot.height * ratio)))
    buf = io.BytesIO()
    shot.save(buf, format="PNG")
    return _ocr_sync(buf.getvalue()).strip()


def _llm():
    brain = load_config().get("brain", {}) or {}
    return LLMClient(
        model=brain.get("model", "qwen2.5:3b"),
        base_url=brain.get("base_url", "http://localhost:11434"),
        temperature=brain.get("temperature", 0.4),
    )


@register
class LookAtScreen(Skill):
    name = "look_at_screen"
    description = (
        'Look at what is on the screen right now and answer a question about it. '
        'Use for "what is this", "what did I search", "read this error". '
        'args: {"question": "what the user asked about the screen"}'
    )

    def execute(self, args):
        question = ((args or {}).get("question") or "What is on the screen?").strip()
        try:
            text = read_screen_text()
        except Exception as exc:
            return f"I couldn't read the screen, sir: {exc}"
        if not text:
            return "I can see the screen, sir, but there's no legible text on it."
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT] + "\n...(truncated)"

        prompt = (
            "You are JARBAI. Below is the text currently visible on the user's screen, "
            "captured by OCR so it may be slightly garbled.\n\n"
            f"--- SCREEN ---\n{text}\n--- END ---\n\n"
            f"Answer this in one or two short sentences, addressing the user as 'sir': {question}"
        )
        try:
            return _llm().complete([{"role": "user", "content": prompt}])
        except LLMUnavailable:
            return "I can read your screen, sir, but my language core is offline."


@register
class ReadScreen(Skill):
    name = "read_screen"
    description = "Read out the raw text currently visible on screen, unsummarised. args: {}"

    def execute(self, args):
        try:
            text = read_screen_text()
        except Exception as exc:
            return f"I couldn't read the screen, sir: {exc}"
        if not text:
            return "There's no legible text on screen, sir."
        return text[:1500] + ("..." if len(text) > 1500 else "")
