"""Translate an SRT file into a target language using Gemini (chunked by lines).

Progress is reported per chunk and per translated line, retries are cancellable,
and lines the model skipped in one pass are retried in a second pass instead of
being silently left in the source language.
"""

import os
import re
import subprocess
import sys
import tempfile
import time

from . import config, keypool
from .transcribe import KeyRotator, GEMINI_HELPER

CHUNK_SIZE = 40


class TranslateError(Exception):
    pass


def parse_srt(content):
    """Return list of dicts: {index, time, text}."""
    items = []
    for block in re.split(r"\r?\n\r?\n", (content or "").lstrip("\ufeff").strip()):
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


def _terminate(proc):
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _call_gemini_translate(chunk_text, language, style, key, model, use_vpn,
                           cancel_check=None):
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
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
        except FileNotFoundError as exc:
            return 3, f"اجرای gemini_worker ناموفق: {exc}"
        try:
            while proc.poll() is None:
                if cancel_check:
                    try:
                        cancel_check()
                    except BaseException:
                        _terminate(proc)
                        raise
                time.sleep(0.15)
        finally:
            try:
                out, err = proc.communicate(timeout=5)
            except Exception:
                out, err = "", ""
        if proc.returncode == 0 and os.path.exists(out_path):
            with open(out_path, encoding="utf-8") as f:
                return 0, f.read()
        return proc.returncode, ((out or "") + (err or "")).strip()
    finally:
        for p in (in_path, out_path):
            try:
                os.remove(p)
            except OSError:
                pass


def _translate_chunk(chunk, target_language, style, rot, models, use_vpn,
                     cancel_check=None, attempts=3):
    """Translate one chunk of SRT items; returns {index: text}."""
    prompt = "".join(f"{it['index']}\n{it['text']}\n\n" for it in chunk)
    last = "unknown"
    for attempt in range(1, attempts + 1):
        if cancel_check:
            cancel_check()
        got = {}
        for model in models:
            key = rot.current()
            rc, payload = _call_gemini_translate(
                prompt, target_language, style, key, model, use_vpn, cancel_check)
            if rc == 0:
                got = _parse_translated(payload)
                if got:
                    return got
                last = "پاسخ خالی از مدل"
                rot.advance()
                continue
            if rc == 4:
                last = "IP توسط گوگل بلاک شده (VPN لازم است)"
            elif rc == 1:
                last = (payload or "model")[-120:]
                continue  # model unsupported: try the next model, keep the key
            else:
                last = (payload or f"rc={rc}")[-160:]
                rot.advance()
        time.sleep(min(10, 2 * attempt))
    raise TranslateError(last)


def translate_srt(srt_text, target_language, style="casual", keys=None, progress=None,
                  cancel_check=None):
    """Translate srt_text; returns translated SRT text. 'keys' = list of Gemini keys."""
    items = parse_srt(srt_text)
    if not items:
        raise TranslateError("SRT معتبر نبود / خطی پیدا نشد.")

    if keys is None:
        try:
            keys = keypool.load_keys("gemini")
        except Exception:
            keys = []
    keys = [k for k in keys if k]
    if not keys:
        raise TranslateError("هیچ کلید Gemini برای ترجمه تنظیم نشده است.")

    models = config.GEMINI_MODELS
    use_vpn = config.GEMINI_USE_VPN and bool(config.YT_NETNS)
    rot = KeyRotator(keys)
    total_items = len(items)

    def report(pct, label):
        if not progress:
            return
        try:
            progress(int(max(0, min(100, pct))), label)
        except Exception:
            pass

    translated = {}
    pending = list(items)
    for attempt in range(1, 4):
        if not pending:
            break
        if cancel_check:
            cancel_check()
        chunks = [pending[i:i + CHUNK_SIZE] for i in range(0, len(pending), CHUNK_SIZE)]
        total = len(chunks)
        report(int(100 * len(translated) / max(1, total_items)),
               f"🌍 ترجمه به {target_language} — پاس {attempt} · "
               f"{len(translated)}/{total_items} خط")
        for ci, chunk in enumerate(chunks):
            if cancel_check:
                cancel_check()
            done_before = len(translated)
            pct = 100.0 * (done_before + (ci / max(1, total)) * len(chunk)) / max(1, total_items)
            report(int(pct),
                   f"🌍 ترجمه بخش {ci + 1}/{total} (پاس {attempt}) — "
                   f"{len(translated)}/{total_items} خط")
            try:
                got = _translate_chunk(chunk, target_language, style, rot, models,
                                       use_vpn, cancel_check)
            except TranslateError:
                if not translated:
                    raise
                got = {}
            translated.update(got)
        pending = [it for it in items if it["index"] not in translated]
        if pending:
            report(int(100 * len(translated) / max(1, total_items)),
                   f"🔁 {len(pending)} خط ترجمه نشد؛ تلاش دوباره ({attempt}/3)…")

    missing = 0
    for it in items:
        if it["index"] in translated:
            it["text"] = translated[it["index"]]
        else:
            missing += 1
    report(100, f"✅ ترجمه کامل شد ({len(items) - missing}/{len(items)} خط)")
    if missing:
        report(100, f"⚠️ {missing} خط ترجمه نشد و به زبان اصلی ماند "
                    f"({len(items) - missing}/{len(items)} خط ترجمه شد)")
    return build_srt(items)