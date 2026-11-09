"""Run a single Gemini generateContent call (optionally inside the VPN netns).

Returns exit codes to let the caller rotate keys / try other models:
  0 = success (SRT written to --out)
  1 = model not found / unsupported (try another model)
  2 = quota / rate limit -> rotate key (caller may ask user for a new key)
  3 = network error -> rotate key / retry
  4 = IP blocked by Google (needs VPN)
  6 = invalid / forbidden key -> rotate key
"""

import argparse
import base64
import json
import os
import re
import sys

import requests

try:
    from audio import get_duration
except Exception:  # pragma: no cover
    def get_duration(_p):
        return 0.0

try:
    from srt_utils import seconds_to_srt_time
except Exception:  # pragma: no cover
    def seconds_to_srt_time(s):
        ms = int(round(float(s) * 1000))
        h, rem = divmod(ms, 3600000)
        m, rem = divmod(rem, 60000)
        sec, ms = divmod(rem, 1000)
        return f"{h:02}:{m:02}:{sec:02},{ms:03}"

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

_STYLE_HINT = {
    "sentence": "Prefer one full sentence per subtitle block.",
    "short": "Keep each subtitle line short (max ~7 words).",
    "word": "Prefer very short blocks (1-3 words).",
}


def build_prompt(language, style):
    lang = "" if not language or language == "auto" else f"The spoken language is '{language}'. "
    hint = _STYLE_HINT.get(style, "")
    return (
        "You are a professional subtitle generator. "
        "Transcribe the audio EXACTLY in its ORIGINAL spoken language — do NOT translate. "
        "If the speaker mixes in English words, technical terms, brand names, or idioms, "
        "keep them in English exactly as spoken — do NOT translate them. "
        + lang
        + "Return ONLY valid SRT (SubRip): numbered blocks, a timing line "
        "'HH:MM:SS,mmm --> HH:MM:SS,mmm', then the text. "
        "Timestamps must follow the audio. No explanations, no markdown code fences. "
        + hint
    )


def extract_text(resp):
    try:
        data = resp.json()
        cands = data.get("candidates") or []
        parts = cands[0].get("content", {}).get("parts", []) if cands else []
        return "".join(p.get("text", "") for p in parts)
    except Exception:
        return ""


def extract_srt(text, duration):
    text = (text or "").strip()
    text = re.sub(r"^```[a-zA-Z0-9]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    m = re.search(r"(?m)^\s*\d+\s*$\n\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->", text)
    if m:
        text = text[m.start():]
    blocks = [b.strip() for b in text.strip().split("\n\n") if "-->" in b]
    if blocks:
        return "\n\n".join(blocks) + "\n"
    clean = " ".join(text.split())
    if not clean:
        return ""
    return f"1\n{seconds_to_srt_time(0)} --> {seconds_to_srt_time(duration)}\n{clean}\n"


def _do_refine(a):
    """Text-only refinement pass: polish an existing SRT (keep timestamps)."""
    try:
        text = open(a.refine_in, encoding="utf-8").read()
    except OSError:
        print("NOREAD")
        return 3
    prompt = (
        "You are a professional subtitle editor. Below is an SRT file. "
        "Improve it: fix spelling, punctuation and line segmentation, and make the "
        "text clean and natural. DO NOT translate; keep the ORIGINAL language. "
        "Keep any English words, technical terms, names or idioms in English — do not translate them. "
        "Keep the exact same timestamps, order, and number of blocks. "
        "Return ONLY valid SRT, no explanations, no markdown fences.\n\n" + text
    )
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0}}
    url = URL.format(model=a.model, key=a.key)
    try:
        resp = requests.post(url, json=body, timeout=600)
    except Exception as e:
        print("NETERR " + repr(e))
        return 3
    if resp.status_code == 200:
        raw = extract_text(resp)
        if "-->" not in raw:
            print("EMPTY")
            return 3
        out = extract_srt(raw, 0)
        with open(a.refine_out, "w", encoding="utf-8") as f:
            f.write(out)
        print("OK")
        return 0

    low = (resp.text or "").lower()
    if "<html" in low and "forbidden" in low:
        print("BLOCKED")
        return 4
    if "api key not valid" in low or "api_key_invalid" in low:
        print("BADKEY")
        return 6
    if resp.status_code in (401, 403):
        print(f"KEY {resp.status_code}")
        return 6
    if resp.status_code == 429 or "quota" in low or "rate" in low:
        print(f"QUOTA {resp.status_code}")
        return 2
    if resp.status_code in (400, 404):
        print(f"MODEL {resp.status_code}")
        return 1
    print(f"HTTP {resp.status_code}")
    return 3



_MIME_BY_EXT = {
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".mp4": "audio/mp4",
    ".wav": "audio/wav", ".ogg": "audio/ogg", ".opus": "audio/ogg",
    ".flac": "audio/flac", ".webm": "audio/webm", ".aac": "audio/aac",
}


def _audio_mime(path):
    return _MIME_BY_EXT.get(os.path.splitext(path)[1].lower(), "audio/mpeg")


def _rc_from_response(resp):
    """Map a Gemini HTTP response to this helper's exit codes.

    Same classification the transcription path uses, so the caller can rotate
    keys / try another model exactly as it does elsewhere.
    """
    low = (resp.text or "").lower()
    if "<html" in low and "forbidden" in low:
        print("BLOCKED")
        return 4
    if "api key not valid" in low or "api_key_invalid" in low:
        print("BADKEY")
        return 6
    if resp.status_code in (401, 403):
        print(f"KEY {resp.status_code}")
        return 6
    if resp.status_code == 429 or "quota" in low or "rate" in low or "resource_exhausted" in low:
        retry = ""
        try:
            for d in resp.json().get("error", {}).get("details", []):
                if "retryDelay" in d:
                    retry = str(d["retryDelay"])
        except Exception:
            pass
        print(f"QUOTA {resp.status_code} retry={retry}")
        return 2
    if resp.status_code in (400, 404):
        print(f"MODEL {resp.status_code}: {(resp.text or '')[:160]}")
        return 1
    print(f"HTTP {resp.status_code}: {(resp.text or '')[:160]}")
    return 3


def _do_refine_audio(a):
    """Audio-aware refine: the model HEARS the audio and rewrites the SRT to match it.

    Unlike _do_refine (text only), the source of truth here is the audio itself:
    the model listens, compares it with the automatic transcript and writes the
    subtitle it actually hears.
    """
    try:
        srt_text = open(a.refine_in, encoding="utf-8").read()
    except OSError:
        print("NOREAD")
        return 3
    try:
        with open(a.audio, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
    except OSError:
        print("NOAUDIO")
        return 3
    try:
        duration = get_duration(a.audio)
    except Exception:
        duration = 0.0

    lang = "" if not a.language or a.language == "auto" else f"The spoken language is '{a.language}'. "
    hint = _STYLE_HINT.get(a.style or "sentence", "")
    prompt = (
        "You can HEAR the attached audio, and below it is an SRT transcript of that SAME audio "
        "made by automatic speech recognition, which may contain misheard words, wrong word "
        "boundaries, broken sentences and poor segmentation.\n"
        "Listen to the audio carefully, compare it with the SRT, and rewrite the subtitle so that "
        "it matches what is actually being said.\n"
        + lang +
        "Rules:\n"
        "- Keep the ORIGINAL spoken language: never translate.\n"
        "- Keep English words, technical terms, brand names and idioms in English exactly as spoken.\n"
        "- Fix misheard or misspelled words, punctuation and sentence boundaries; merge or split "
        "blocks so every block is one clear, complete, readable unit that matches the audio.\n"
        "- Timestamps must follow the audio, stay in order, never overlap and never run past the "
        "end of the audio.\n"
        "- Never invent content that is not in the audio and never drop anything that is said.\n"
        "Return ONLY valid SRT (SubRip): numbered blocks, a timing line "
        "'HH:MM:SS,mmm --> HH:MM:SS,mmm', then the text. No explanations, no markdown code fences.\n"
        + hint +
        "\n\n--- SRT to correct ---\n" + srt_text
    )
    body = {
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": _audio_mime(a.audio), "data": b64}},
        ]}],
        "generationConfig": {"temperature": 0},
    }
    url = URL.format(model=a.model, key=a.key)
    try:
        resp = requests.post(url, json=body, timeout=1800)
    except Exception as e:
        print("NETERR " + repr(e))
        return 3

    if resp.status_code == 200:
        raw = extract_text(resp)
        if "-->" not in (raw or ""):
            print("EMPTY")
            return 3
        srt = extract_srt(raw, duration)
        if not srt.strip():
            print("EMPTY")
            return 3
        with open(a.refine_out, "w", encoding="utf-8") as f:
            f.write(srt)
        print("OK")
        return 0
    return _rc_from_response(resp)


_TRANS_STYLES = {
    "casual": "Use a highly conversational, casual, street-smart tone suitable for movies/series, with natural everyday idioms.",
    "formal": "Use a clean, prestigious, standard, fully formal tone suitable for official media/news/literature.",
    "educational": "Use a clear, informative, precise, balanced tone suitable for tutorials and educational content.",
}


def _do_translate(a):
    """Translate a chunk of subtitle lines (format: 'ID\\ntext\\n\\n')."""
    try:
        text = open(a.translate_in, encoding="utf-8").read()
    except OSError:
        print("NOREAD")
        return 3
    style = _TRANS_STYLES.get((a.style or "casual").lower(), _TRANS_STYLES["casual"])
    system = (
        "You are a professional subtitle translator. "
        f"Translate the provided subtitle lines into {a.language or 'the target language'}. "
        + style
        + " Strict rules: do NOT change, merge, skip, or renumber any subtitle IDs; "
        "keep the exact number and order of lines; preserve meaning fully (no omissions). "
        "Keep English technical terms and proper names in English when appropriate. "
        "Output ONLY the translated lines, each as 'ID' on its own line followed by the "
        "translated text line(s), separated by a blank line. No notes, no explanations."
    )
    body = {
        "contents": [{"parts": [{"text": text}]}],
        "systemInstruction": {"parts": [{"text": system}]},
        "generationConfig": {"temperature": 0.3},
    }
    url = URL.format(model=a.model, key=a.key)
    try:
        resp = requests.post(url, json=body, timeout=600)
    except Exception as e:
        print("NETERR " + repr(e))
        return 3
    if resp.status_code == 200:
        raw = extract_text(resp)
        if not raw.strip():
            print("EMPTY")
            return 3
        with open(a.translate_out, "w", encoding="utf-8") as f:
            f.write(raw)
        print("OK")
        return 0

    low = (resp.text or "").lower()
    if "<html" in low and "forbidden" in low:
        print("BLOCKED")
        return 4
    if "api key not valid" in low or "api_key_invalid" in low:
        print("BADKEY")
        return 6
    if resp.status_code in (401, 403):
        print(f"KEY {resp.status_code}")
        return 6
    if resp.status_code == 429 or "quota" in low or "rate" in low:
        print(f"QUOTA {resp.status_code}")
        return 2
    if resp.status_code in (400, 404):
        print(f"MODEL {resp.status_code}")
        return 1
    print(f"HTTP {resp.status_code}")
    return 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio")
    ap.add_argument("--refine-in")
    ap.add_argument("--refine-audio", action="store_true",
                    help="with --refine-in: also send --audio so the model can listen")
    ap.add_argument("--refine-out")
    ap.add_argument("--translate-in")
    ap.add_argument("--translate-out")
    ap.add_argument("--model", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--language", default="")
    ap.add_argument("--style", default="sentence")
    ap.add_argument("--out")
    a = ap.parse_args()

    if a.refine_in and getattr(a, "refine_audio", False):
        return _do_refine_audio(a)

    if a.refine_in:
        return _do_refine(a)

    if a.translate_in:
        return _do_translate(a)

    if not a.audio or not a.out:
        print("MISSING --audio/--out")
        return 3

    with open(a.audio, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    try:
        duration = get_duration(a.audio)
    except Exception:
        duration = 0.0

    body = {
        "contents": [{"parts": [
            {"text": build_prompt(a.language, a.style)},
            {"inline_data": {"mime_type": "audio/mpeg", "data": b64}},
        ]}],
        "generationConfig": {"temperature": 0},
    }
    url = URL.format(model=a.model, key=a.key)

    try:
        resp = requests.post(url, json=body, timeout=1800)
    except Exception as e:
        print("NETERR " + repr(e))
        return 3

    if resp.status_code == 200:
        srt = extract_srt(extract_text(resp), duration)
        if not srt.strip():
            print("EMPTY")
            return 3
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(srt)
        print("OK")
        return 0

    low = (resp.text or "").lower()
    if "<html" in low and "forbidden" in low:
        print("BLOCKED")
        return 4
    if "api key not valid" in low or "api_key_invalid" in low:
        print("BADKEY")
        return 6
    if resp.status_code in (401, 403):
        print(f"KEY {resp.status_code}")
        return 6
    if resp.status_code == 429 or "quota" in low or "rate" in low or "resource_exhausted" in low:
        retry = ""
        try:
            for d in resp.json().get("error", {}).get("details", []):
                if "retryDelay" in d:
                    retry = str(d["retryDelay"])
        except Exception:
            pass
        print(f"QUOTA {resp.status_code} retry={retry}")
        return 2
    if resp.status_code in (400, 404):
        print(f"MODEL {resp.status_code}: {(resp.text or '')[:160]}")
        return 1
    print(f"HTTP {resp.status_code}: {(resp.text or '')[:160]}")
    return 3


if __name__ == "__main__":
    sys.exit(main())