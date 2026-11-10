"""Free OpenRouter models as the deep-mode subtitle reviewer.

Deep mode is a second opinion: the main engine produces the subtitle, and a
different model then reviews it - spelling, punctuation, line segmentation and
block boundaries - without translating and without touching the timestamps.

Gemini can also *listen* to the audio during that pass.  The free OpenRouter
models are text-only, so this reviewer works on the transcript itself.  It is
plain HTTP in this process: no helper subprocess (there is no VPN/netns to enter)
and no audio upload, which also keeps a free model's context small.
"""

import re

import requests

from . import config

REFINE_SYSTEM = (
    "You are a meticulous subtitle editor. You receive a machine-generated SRT "
    "transcript and return a corrected SRT."
)

REFINE_TEMPLATE = (
    "Below is an SRT file produced by automatic speech recognition. Rewrite it, "
    "changing only what is actually wrong:\n"
    "- fix spelling, punctuation, capitalisation and misheard words;\n"
    "- merge or split blocks so every block is one complete, readable unit;\n"
    "- keep the ORIGINAL spoken language: never translate;\n"
    "- keep English words, technical terms, brand names and idioms in English;\n"
    "- keep every timestamp exactly as it is: same values, same order, one "
    "timing line per block, no overlaps, nothing past the end;\n"
    "- never invent content and never drop a line.\n"
    "Return ONLY valid SRT (numbered blocks: the number, a timing line "
    "'HH:MM:SS,mmm --> HH:MM:SS,mmm', then the text). "
    "No explanations and no markdown fences.\n\n"
    "--- SRT to review ---\n"
)

# refine() outcomes, so the caller can rotate keys / try the next model.
OK = "ok"
RATE = "rate"
BAD_KEY = "bad_key"
MODEL = "model"
ERROR = "error"

_BLOCK_START = re.compile(
    r"(?m)^\s*\d+\s*$\n\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->")


def models():
    """The free models to try, in order (config / OPENROUTER_MODELS overridable)."""
    return [m for m in config.OPENROUTER_MODELS if m]


def _clean_srt(text):
    """Strip fences / chatter around the SRT and keep only real subtitle blocks."""
    text = (text or "").strip()
    text = re.sub(r"^```[a-zA-Z0-9]*[ \t]*\n?", "", text)   # fence around the whole answer
    text = re.split(r"(?m)^\s*```\s*$", text)[0]            # chatter after a closing fence
    match = _BLOCK_START.search(text)
    if match:
        text = text[match.start():]
    blocks = [b.strip() for b in text.strip().split("\n\n") if "-->" in b]
    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n"


def refine(srt_text, api_key, model, timeout=None, session=None):
    """Review ``srt_text`` with one model.

    Returns ``(status, payload)``: on ``OK`` the payload is the corrected SRT,
    otherwise a short detail string for the log.
    """
    key = (api_key or "").strip()
    if not key:
        return BAD_KEY, "empty key"
    url = config.OPENROUTER_BASE.rstrip("/") + "/chat/completions"
    max_tokens = max(1024, min(60000, len(srt_text or "") // 2 + 512))
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": REFINE_SYSTEM},
            {"role": "user", "content": REFINE_TEMPLATE + (srt_text or "")},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/ParsaPRF/arion-studio",
        "X-Title": "Arion Studio",
    }
    client = session or requests
    try:
        resp = client.post(url, json=payload, headers=headers,
                           timeout=timeout or config.OPENROUTER_TIMEOUT)
    except Exception as exc:
        return ERROR, repr(exc)

    if resp.status_code == 200:
        try:
            choice = (resp.json().get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content") or ""
        except Exception:
            return ERROR, "unreadable response"
        srt = _clean_srt(content)
        if not srt:
            return ERROR, "the model returned no SRT"
        return OK, srt

    detail = (resp.text or "")[:300]
    low = detail.lower()
    if resp.status_code == 429 or "rate limit" in low:
        return RATE, detail
    if resp.status_code in (401, 403) or "invalid api key" in low:
        return BAD_KEY, detail
    if resp.status_code == 404 or "model" in low:
        return MODEL, detail
    return ERROR, f"HTTP {resp.status_code}: {detail}"


def check_key(api_key, timeout=25):
    """Cheap validity check for the settings page: (ok, detail)."""
    key = (api_key or "").strip()
    if not key:
        return False, "empty key"
    url = config.OPENROUTER_BASE.rstrip("/") + "/key"
    try:
        resp = requests.get(url, headers={"Authorization": "Bearer " + key},
                            timeout=timeout)
    except Exception as exc:
        return False, str(exc)
    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code}: {(resp.text or '')[:200]}"
    try:
        data = resp.json().get("data") or {}
    except Exception:
        return True, ""
    usage = data.get("usage")
    limit = data.get("limit")
    if usage is None and limit is None:
        return True, ""
    return True, f"usage={usage} limit={limit}"