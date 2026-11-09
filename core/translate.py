"""Translate an SRT file into a target language using Gemini (chunked by lines)."""

import os
import re
import subprocess
import sys
import tempfile
import time

from . import config
from .transcribe import KeyRotator, GEMINI_HELPER

CHUNK_SIZE = 40


class TranslateError(Exception):
    pass


def parse_srt(content):
    """Return list of dicts: {index, time, text}."""
    items = []
    for block in re.split(r"\r?\n\r?\n", (content or "").strip()):
        lines = block.split("\n")
        if len(lines) < 2:
            continue
        if not lines[0].strip().isdigit():
            continue
        idx = int(lines[0].strip())
        time_line = lines[1].strip()
        if "-->" not in time_line:
            continue
        text = "\n".join(lines[2:]).strip()
        items.append({"index": idx, "time": time_line, "text": text})
    return items


def build_srt(items):
    out = []
    for it in items:
        out.append(f"{it['index']}\n{it['time']}\n{it['text']}")
    return "\n\n".join(out) + "\n"


def _parse_translated(text):
    result = {}
    for block in re.split(r"\r?\n\s*\r?\n", (text or "").strip()):
        lines = block.strip().split("\n")
        if not lines or not lines[0].strip().isdigit():
            continue
        idx = int(lines[0].strip())
        content = "\n".join(lines[1:]).strip()
        if content:
            result[idx] = content
    return result


def _call_gemini_translate(chunk_text, language, style, key, model, use_vpn):
    in_fd, in_path = tempfile.mkstemp(suffix=".txt")
    out_fd, out_path = tempfile.mkstemp(suffix=".txt")
    os.close(in_fd)
    os.close(out_fd)
    try:
        with open(in_path, "w", encoding="utf-8") as f:
            f.write(chunk_text)
        cmd = []
        if use_vpn and config.YT_NETNS:
            cmd += ["ip", "netns", "exec", config.YT_NETNS]
        cmd += [sys.executable, GEMINI_HELPER,
                "--translate-in", in_path, "--translate-out", out_path,
                "--model", model, "--key", key,
                "--language", language, "--style", style]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode == 0 and os.path.exists(out_path):
            with open(out_path, encoding="utf-8") as f:
                return 0, f.read()
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    finally:
        for p in (in_path, out_path):
            try:
                os.remove(p)
            except OSError:
                pass


def translate_srt(srt_text, target_language, style="casual", keys=None, progress=None):
    """Translate srt_text; returns translated SRT text. 'keys' = list of Gemini keys."""
    items = parse_srt(srt_text)
    if not items:
        raise TranslateError("SRT معتبر نبود / خطی پیدا نشد.")

    if keys is None:
        try:
            import keypool
            keys = keypool.load_keys("gemini")
        except Exception:
            keys = []
    keys = [k for k in keys if k]
    if not keys:
        raise TranslateError("هیچ کلید Gemini برای ترجمه تنظیم نشده است.")

    models = config.GEMINI_MODELS
    use_vpn = config.GEMINI_USE_VPN and bool(config.YT_NETNS)
    rot = KeyRotator(keys)

    def report(pct, label):
        if progress:
            try:
                progress(pct, label)
            except Exception:
                pass

    chunks = [items[i:i + CHUNK_SIZE] for i in range(0, len(items), CHUNK_SIZE)]
    translated = {}
    total = len(chunks)
    for ci, chunk in enumerate(chunks):
        report(int(ci / max(1, total) * 100), f"🌍 ترجمه بخش {ci + 1}/{total}...")
        prompt = "".join(f"{it['index']}\n{it['text']}\n\n" for it in chunk)
        got = {}
        last = "unknown"
        for attempt in range(1, 4):
            for model in models:
                key = rot.current()
                rc, payload = _call_gemini_translate(prompt, target_language, style, key, model, use_vpn)
                if rc == 0:
                    got = _parse_translated(payload)
                    if got:
                        break
                    last = "پاسخ خالی"
                    rot.advance()
                    continue
                if rc == 4:
                    last = "IP توسط گوگل بلاک شده (VPN لازم است)"
                elif rc == 1:
                    last = (payload or "model")[-120:]
                    continue  # try next model, keep key
                else:
                    last = (payload or f"rc={rc}")[-160:]
                    rot.advance()
            if got:
                break
            time.sleep(3 * attempt)
        if not got:
            raise TranslateError(f"ترجمه بخش {ci + 1} ناموفق بود: {last}")
        translated.update(got)
        rot.advance()

    missing = 0
    for it in items:
        if it["index"] in translated:
            it["text"] = translated[it["index"]]
        else:
            missing += 1
    report(100, f"✅ ترجمه کامل شد ({len(items) - missing}/{len(items)} خط)")
    return build_srt(items)
