"""Web skills: open a search in the browser, or answer from the web directly."""

import subprocess
import webbrowser
from urllib.parse import quote_plus, urlparse

import requests

from ..utils.config import load_config
from .base import Skill, register

SEARCH = "https://www.google.com/search?q={}"


def _open(url):
    """Open in the configured browser, falling back to the system default."""
    browser = (load_config().get("apps", {}) or {}).get("browser")
    if browser:
        try:
            subprocess.Popen([browser, url])
            return
        except OSError:
            pass
    webbrowser.open(url)


@register
class SearchWeb(Skill):
    name = "search_web"
    description = 'Open a web search in the browser. args: {"query": "what to search for"}'

    def execute(self, args):
        query = ((args or {}).get("query") or "").strip()
        if not query:
            return "What would you like me to search for, sir?"
        _open(SEARCH.format(quote_plus(query)))
        return f"Searching the web for {query}, sir."


@register
class OpenUrl(Skill):
    name = "open_url"
    description = 'Open a website. args: {"url": "example.com"}'

    def execute(self, args):
        url = ((args or {}).get("url") or "").strip()
        if not url:
            return "Which site should I open, sir?"
        if not urlparse(url).scheme:
            url = "https://" + url
        if urlparse(url).scheme not in ("http", "https"):
            return "I only open web addresses, sir."
        _open(url)
        return f"Opening {urlparse(url).netloc or url}, sir."


@register
class WebAnswer(Skill):
    name = "web_answer"
    description = (
        'Look up a quick factual answer online and say it, without opening a browser. '
        'args: {"query": "who invented the telephone"}'
    )

    def execute(self, args):
        query = ((args or {}).get("query") or "").strip()
        if not query:
            return "What should I look up, sir?"
        try:
            data = requests.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
                timeout=15,
            ).json()
        except (requests.RequestException, ValueError):
            return "I couldn't reach the web, sir."

        answer = (data.get("AbstractText") or data.get("Answer") or "").strip()
        if not answer:
            for topic in data.get("RelatedTopics", []):
                if isinstance(topic, dict) and topic.get("Text"):
                    answer = topic["Text"].strip()
                    break
        if not answer:
            return f"I found nothing definitive on that, sir. Shall I search the web for {query}?"
        if len(answer) > 400:
            answer = answer[:400].rsplit(" ", 1)[0] + "..."
        return answer
