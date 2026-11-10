import os
import re
import subprocess
import sys
import time

import requests

from i18n import t

from . import config
from . import keypool
from . import openrouter
from .audio import compress_to_mp3, get_duration, split_audio
from .srt_utils import STYLE_SENTENCE, build_srt, merge_srt_chunks, srt_to_plain_text

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODEL = "whisper-large-v3"
QUOTA_MARKERS = ["quota", "exceeded", "429", "resource_exhausted", "rate limit", "overloaded", "pausing"]

# Soft hint so mixed-language speech keeps English terms in English (no translation).
MIXED_LANG_PROMPT = (
    "Transcribe in the original spoken language. If the speaker mixes in English words, "
    "technical terms, brand names, or idioms, keep them in English exactly as spoken — "
    "do NOT translate them."
)

GEMINI_HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gemini_worker.py")


class TranscriptionError(Exception):
    """Raised when the transcription API itself fails."""


class RateLimitedError(TranscriptionError):
    """Raised when all keys hit the API rate/quota limit."""

    def __init__(self, detail, retry_after=None):
        super().__init__(detail)
        self.detail = detail
        self.retry_after = retry_after
        # filled in by transcribe_file so the job can be resumed
        self.work_dir = None
        self.base = None
        self.base_name = None
        self.language = None
        self.output_format = None
        self.style = None
        self.provider = None
        self.chunk_index = 0
        self.total = 0


class ProcessingError(Exception):
    """Raised when a pipeline stage fails. Carries the stage name for the user."""

    def __init__(self, stage, detail):
        self.stage = stage
        self.detail = detail
        super().__init__(f"[{stage}] {detail}")


class KeyRotator:
    """Rotates through API keys; advances on auth/quota failures."""

    def __init__(self, keys):
        clean = [k for k in (keys or []) if k and k.strip()]
        self.keys = clean or [""]
        self.i = 0

    def current(self):
        return self.keys[self.i % len(self.keys)]

    def advance(self):
        self.i += 1

    def label(self):
        if len(self.keys) <= 1:
            return ""
        return t("tr.progress.key", index=self.i % len(self.keys) + 1,
                 total=len(self.keys))


# ---------------- Groq / Whisper ----------------

def _sleep(seconds, cancel_check=None):
    """Sleep that wakes up immediately when the user cancels."""
    remaining = float(seconds)
    while remaining > 0:
        if cancel_check:
            cancel_check()
        step = min(0.5, remaining)
        time.sleep(step)
        remaining -= step


def _post(rotator, chunk_path, data, max_attempts=None, cancel_check=None):
    n = len(rotator.keys)
    if max_attempts is None:
        max_attempts = max(5, 4 * n)
    last_error = "unknown error"
    saw_quota = False
    retry_hint = None
    for attempt in range(1, max_attempts + 1):
        if cancel_check:
            cancel_check()
        key = rotator.current()
        headers = {"Authorization": f"Bearer {key}"}
        try:
            with open(chunk_path, "rb") as f:
                files = {"file": (os.path.basename(chunk_path), f, "audio/mpeg")}
                resp = requests.post(GROQ_URL, headers=headers, files=files, data=data, timeout=1800)
        except Exception as e:
            last_error = t("tr.err.network", error=e)
            _sleep(min(30, 3 * attempt), cancel_check)
            continue

        if resp.status_code == 200:
            return resp

        body = resp.text or ""
        last_error = f"HTTP {resp.status_code}: {body[:180]}"
        if resp.status_code in (401, 403):
            rotator.advance()
            continue
        if resp.status_code == 413:
            raise TranscriptionError(t("tr.err.chunk_too_large"))
        if resp.status_code == 429 or any(m in body.lower() for m in QUOTA_MARKERS):
            saw_quota = True
            m = re.search(r"try again in ([\d.]+)\s*s", body, re.I)
            if m:
                retry_hint = t("tr.retry.seconds", seconds=m.group(1))
            ra = resp.headers.get("retry-after")
            if ra:
                retry_hint = t("tr.retry.seconds", seconds=ra) if ra.isdigit() else ra
            rotator.advance()
            _sleep(min(30, 3 * attempt), cancel_check)
            continue
        rotator.advance()
        if attempt >= max(2, 2 * n):
            raise TranscriptionError(last_error)
    if saw_quota:
        raise RateLimitedError(t("tr.err.rate_limited", detail=last_error), retry_hint)
    raise TranscriptionError(t("tr.err.all_failed", detail=last_error))


def _transcribe_chunk_groq(rotator, chunk_path, language, style, cancel_check=None):
    data = {
        "model": MODEL,
        "response_format": "verbose_json",
        "temperature": "0",
        "timestamp_granularities[]": ["segment", "word"],
        "prompt": MIXED_LANG_PROMPT,
    }
    if language and language != "auto":
        data["language"] = language

    resp = _post(rotator, chunk_path, data, cancel_check=cancel_check)
    try:
        obj = resp.json()
    except ValueError:
        obj = {}

    detected = (obj.get("language") or "").strip() or None
    content = build_srt(obj.get("segments") or [], obj.get("words") or [], style)
    if content.strip():
        return content, detected

    data2 = {"model": MODEL, "response_format": "srt", "temperature": "0",
             "prompt": MIXED_LANG_PROMPT}
    if language and language != "auto":
        data2["language"] = language
    resp2 = _post(rotator, chunk_path, data2, cancel_check=cancel_check)
    if resp2.text.strip():
        return resp2.text.strip() + "\n", detected
    raise TranscriptionError(t("tr.err.empty_response"))


# ---------------- Gemini (via helper process, optionally inside the VPN netns) ----------------

def _gemini_call(model, key, audio_path, language, style, use_vpn):
    out_path = audio_path + ".gsrt"
    if os.path.exists(out_path):
        try:
            os.remove(out_path)
        except OSError:
            pass
    cmd = []
    if use_vpn and config.YT_NETNS:
        cmd += ["ip", "netns", "exec", config.YT_NETNS]
    cmd += [
        sys.executable, GEMINI_HELPER,
        "--audio", audio_path, "--model", model, "--key", key,
        "--language", language or "", "--style", style, "--out", out_path,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except Exception as e:
        return 3, t("tr.err.run", error=e)
    if r.returncode == 0 and os.path.exists(out_path):
        try:
            with open(out_path, encoding="utf-8") as f:
                return 0, f.read()
        except OSError as e:
            return 3, str(e)
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def _transcribe_chunk_gemini(rotator, models, chunk_path, language, style, use_vpn,
                             cancel_check=None):
    nkeys = len(rotator.keys)
    last = "unknown"
    saw_quota = False
    retry_hint = None
    for model in (models or ["gemini-3.5-flash"]):
        for _ in range(nkeys):
            if cancel_check:
                cancel_check()
            key = rotator.current()
            rc, payload = _gemini_call(model, key, chunk_path, language, style, use_vpn)
            if rc == 0:
                srt = (payload or "").strip()
                if srt:
                    return srt if srt.endswith("\n") else srt + "\n"
                last = t("tr.err.empty_gemini")
                rotator.advance()
                continue
            last = (payload or f"rc={rc}")[-200:]
            if rc == 1:      # model not found/unsupported -> try next model
                break
            if rc == 2:      # quota / rate limit
                saw_quota = True
                m = re.search(r"retry[^\d]*([\d.]+)s", payload or "", re.I)
                if m:
                    retry_hint = t("tr.retry.seconds", seconds=m.group(1))
                rotator.advance()
                continue
            if rc == 6:      # invalid/forbidden key
                rotator.advance()
                continue
            if rc == 4:      # IP blocked by Google
                last = t("tr.err.ip_blocked")
                rotator.advance()
                continue
            rotator.advance()  # rc==3 network -> rotate
            continue
    if saw_quota:
        raise RateLimitedError(t("tr.err.gemini_rate_limited", detail=last), retry_hint)
    raise TranscriptionError(t("tr.err.gemini_failed", detail=last))


def _audio_refine_call(model, key, audio_path, in_path, out_path, language, style, use_vpn):
    """Ask Gemini to LISTEN to the chunk audio and rewrite the chunk SRT accordingly."""
    cmd = []
    if use_vpn and config.YT_NETNS:
        cmd += ["ip", "netns", "exec", config.YT_NETNS]
    cmd += [
        sys.executable, GEMINI_HELPER,
        "--refine-audio", "--audio", audio_path,
        "--refine-in", in_path, "--refine-out", out_path,
        "--language", language or "", "--style", style or STYLE_SENTENCE,
        "--model", model, "--key", key,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except Exception as e:
        return 3, repr(e)
    if r.returncode == 0 and os.path.exists(out_path):
        return 0, "OK"
    payload = (r.stdout or "").strip() or (r.stderr or "").strip()
    return r.returncode, payload[-200:]


def _srt_plain(path):
    try:
        with open(path, encoding="utf-8") as f:
            return srt_to_plain_text(f.read()).strip()
    except Exception:
        return ""


def _audio_refine_ok(orig_path, new_path):
    """Reject obviously broken refine output (empty or badly truncated), so the
    original transcript is kept instead of losing text."""
    if not new_path or not os.path.exists(new_path):
        return False
    new = _srt_plain(new_path)
    if not new:
        return False
    old = _srt_plain(orig_path)
    if old and len(new) < max(10, int(0.55 * len(old))):
        return False
    return True


def _refine_chunks_with_audio(chunk_files, chunk_srt_paths, out_dir, report, keys, models,
                              language, style, use_vpn, cancel_check=None):
    """Deep pass: for every audio chunk, let the model HEAR the audio and rewrite its SRT.

    Returns (paths_to_merge, refined_count). A chunk whose refine failed keeps its
    original transcript, so this pass can never lose text.
    """
    keys = [k for k in (keys or []) if k]
    if not keys:
        return list(chunk_srt_paths), 0
    os.makedirs(out_dir, exist_ok=True)
    rot = KeyRotator(keys)
    total = len(chunk_files)
    final_paths, refined = [], 0
    for i, (audio, srt_path) in enumerate(zip(chunk_files, chunk_srt_paths), 1):
        if cancel_check:
            cancel_check()
        out = os.path.join(out_dir, f"refined_{i:04d}.srt")
        try:
            if os.path.exists(out):
                os.remove(out)
        except OSError:
            pass
        report(int(100 * (i - 1) / max(1, total)),
               t("tr.progress.audio_review", index=i, total=total),
               88 + 7 * ((i - 1) / max(1, total)))
        ok = False
        for model in (models or ["gemini-3.5-flash"]):
            for _ in range(len(rot.keys)):
                if cancel_check:
                    cancel_check()
                key = rot.current()
                rc, _payload = _audio_refine_call(
                    model, key, audio, srt_path, out, language, style, use_vpn)
                if rc == 0:
                    ok = True
                    break
                if rc == 1:      # model cannot take audio / not found -> next model
                    break
                rot.advance()
            if ok:
                break
        if ok and _audio_refine_ok(srt_path, out):
            final_paths.append(out)
            refined += 1
        else:
            final_paths.append(srt_path)
    report(100, t("tr.progress.audio_review_done", done=refined, total=total), 95)
    return final_paths, refined


def _gemini_refine_call(model, key, in_path, out_path, use_vpn):
    cmd = []
    if use_vpn and config.YT_NETNS:
        cmd += ["ip", "netns", "exec", config.YT_NETNS]
    cmd += [
        sys.executable, GEMINI_HELPER,
        "--refine-in", in_path, "--refine-out", out_path,
        "--model", model, "--key", key,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except Exception:
        return 3
    if r.returncode == 0 and os.path.exists(out_path):
        return 0
    return r.returncode


def _refine_srt_openrouter(srt_text, report, keys, models=None):
    """Deep-mode reviewer on a free OpenRouter model (text only, no audio).

    Every free model is tried in order, and each one is retried with the next key
    when it reports a rate limit or a rejected key.  The transcript is returned
    unchanged if nothing succeeds, so a reviewer can never lose text.
    """
    keys = [k for k in (keys or []) if k and k.strip()]
    if not keys:
        return srt_text
    rot = KeyRotator(keys)
    for model in (models or openrouter.models()):
        for _ in range(len(rot.keys)):
            status, payload = openrouter.refine(srt_text, rot.current(), model)
            if status == openrouter.OK:
                if report:
                    report(100, t("tr.progress.deep_refine_model", model=model), 98)
                return payload
            if status == openrouter.MODEL:
                break                 # this model is unavailable: next one
            rot.advance()             # rate limit / bad key / network: next key
    return srt_text


def _refine_srt(srt_text, work_dir, report, keys=None, provider="gemini",
                models=None):
    """Deep-mode second pass: polish the SRT text, keeping timings.

    ``provider`` picks the reviewer: ``gemini`` (text, via the helper process) or
    ``openrouter`` (a free text-only model, in-process).
    """
    if (provider or "gemini") == "openrouter":
        if keys is None:
            try:
                keys = keypool.load_keys("openrouter")
            except Exception:
                keys = []
        return _refine_srt_openrouter(srt_text, report, keys, models)
    if keys is None:
        try:
            keys = keypool.load_keys("gemini")
        except Exception:
            keys = []
    keys = [k for k in keys if k]
    if not keys:
        return srt_text
    in_path = os.path.join(work_dir, "refine_in.srt")
    out_path = os.path.join(work_dir, "refine_out.srt")
    try:
        with open(in_path, "w", encoding="utf-8") as f:
            f.write(srt_text)
    except OSError:
        return srt_text

    use_vpn = config.GEMINI_USE_VPN and bool(config.YT_NETNS)
    rot = KeyRotator(keys)
    for model in (config.GEMINI_MODELS or ["gemini-3.5-flash"]):
        for _ in range(len(rot.keys)):
            key = rot.current()
            rc = _gemini_refine_call(model, key, in_path, out_path, use_vpn)
            if rc == 0 and os.path.exists(out_path):
                try:
                    with open(out_path, encoding="utf-8") as f:
                        out = f.read().strip()
                    if out:
                        return out + "\n"
                except OSError:
                    pass
                return srt_text
            if rc == 1:
                break
            rot.advance()
    return srt_text


# ---------------- pipeline ----------------

def transcribe_file(api_keys, input_path, work_dir, language="fa", output_format="srt",
                    style=STYLE_SENTENCE, progress=None, base_name=None,
                    provider="groq", gemini_models=None, skip_existing=False, deep=False,
                    cancel_check=None, refine_keys=None, stats=None, final_dir=None,
                    refine_provider="gemini", refine_models=None):
    """Full pipeline with stage-accurate errors and API-key rotation.

    provider: "groq" (Whisper) or "gemini".
    ``work_dir`` holds the intermediate chunks/SRTs; ``final_dir`` (defaults to
    work_dir) receives the finished .srt/.txt so the user finds the result in
    the folder they actually chose.
    Returns {"srt": path, "txt": path} depending on output_format.
    """
    if isinstance(api_keys, str):
        api_keys = [api_keys]
    rotator = KeyRotator(api_keys)
    models = gemini_models or config.GEMINI_MODELS
    gem_use_vpn = provider == "gemini" and config.GEMINI_USE_VPN and bool(config.YT_NETNS)
    refine_vpn = config.GEMINI_USE_VPN and bool(config.YT_NETNS)

    def report(stage_pct, label, overall):
        note = rotator.label()
        if progress:
            try:
                progress(stage_pct, label, overall, note)
            except TypeError:
                try:
                    progress(stage_pct, label, overall)
                except Exception:
                    pass
            except Exception:
                pass

    os.makedirs(work_dir, exist_ok=True)
    if final_dir:
        os.makedirs(final_dir, exist_ok=True)
    base = base_name or os.path.splitext(os.path.basename(input_path))[0]

    def check_cancel():
        # ``cancel_check`` is expected to *raise* (engine.Cancelled); calling it
        # unconditionally is what makes Stop work during slow stages.
        if cancel_check:
            cancel_check()

    def audio_progress(stage_pct, label=None):
        report(stage_pct, label or t("tr.progress.audio_processing"),
               3 + (stage_pct or 0) * 0.07)

    check_cancel()
    report(0, t("tr.progress.compressing"), 3)
    try:
        audio_path = compress_to_mp3(
            input_path, os.path.join(work_dir, "audio.mp3"),
            progress=audio_progress, cancel_check=check_cancel)
    except Exception as e:
        raise ProcessingError(t("tr.stage.compress"), str(e))
    report(100, t("tr.progress.compressing_done"), 10)

    if provider == "gemini":
        chunk_minutes = (config.GEMINI_CHUNK_MINUTES // 2) if deep else config.GEMINI_CHUNK_MINUTES
    else:
        chunk_minutes = (config.CHUNK_MINUTES // 2) if deep else config.CHUNK_MINUTES
    chunk_minutes = max(1, chunk_minutes)
    try:
        chunks, starts = split_audio(
            audio_path, os.path.join(work_dir, "chunks"), max_minutes=chunk_minutes,
            progress=lambda p, lbl=None: report(p, lbl or t("tr.progress.splitting"),
                                               10 + (p or 0) * 0.06),
            cancel_check=check_cancel)
    except Exception as e:
        raise ProcessingError(t("tr.stage.split"), str(e))
    if not chunks:
        raise ProcessingError(t("tr.stage.split"), t("tr.err.no_chunks"))
    report(100, t("tr.progress.splitting_done", count=len(chunks), minutes=chunk_minutes), 16)

    chunk_srt_paths, windows = [], []
    total_chunks = len(chunks)
    engine = "Gemini" if provider == "gemini" else "Whisper large-v3"
    # For auto language, detect once (first chunk) and lock it for the rest.
    locked_lang = None if (not language or language == "auto") else language
    for i, chunk in enumerate(chunks):
        check_cancel()
        srt_path = os.path.splitext(chunk)[0] + ".srt"
        win_end = starts[i + 1] if (i + 1) < total_chunks else (starts[i] + get_duration(chunk))
        if skip_existing and os.path.exists(srt_path) and os.path.getsize(srt_path) > 0:
            chunk_srt_paths.append(srt_path)
            windows.append((starts[i], win_end))
            continue
        stage_pct = (i / max(1, total_chunks)) * 100
        overall = 16 + (i / max(1, total_chunks)) * 72
        icons = " ".join("✅" if j < i else ("🔄" if j == i else "▫️") for j in range(total_chunks))
        label = t("tr.progress.transcribe_chunk", index=i + 1,
                  total=total_chunks, engine=engine, icons=icons)
        report(stage_pct, label, overall)
        try:
            if provider == "gemini":
                srt_content = _transcribe_chunk_gemini(
                    rotator, models, chunk, locked_lang or "auto", style, gem_use_vpn,
                    cancel_check=check_cancel)
            else:
                srt_content, detected = _transcribe_chunk_groq(
                    rotator, chunk, locked_lang or "auto", style,
                    cancel_check=check_cancel)
                if locked_lang is None and detected:
                    locked_lang = detected
        except RateLimitedError as e:
            e.work_dir = work_dir
            e.base = base
            e.base_name = base_name
            e.language = language
            e.output_format = output_format
            e.style = style
            e.provider = provider
            e.chunk_index = i
            e.total = total_chunks
            raise
        except TranscriptionError as e:
            raise ProcessingError(t("tr.stage.transcribe_chunk", index=i + 1,
                                    total=total_chunks), str(e))
        except Exception as e:
            raise ProcessingError(t("tr.stage.transcribe_chunk", index=i + 1,
                                    total=total_chunks), repr(e))
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)
        chunk_srt_paths.append(srt_path)
        windows.append((starts[i], win_end))
        report(100, t("tr.progress.chunk", index=i + 1, total=total_chunks),
               16 + ((i + 1) / max(1, total_chunks)) * 72)
    refined = 0
    refine_provider = (refine_provider or "gemini").strip().lower()
    if deep:
        if refine_provider != "openrouter":
            # Gemini can listen to each chunk; the free OpenRouter models cannot,
            # so they review the merged text further down instead.
            if refine_keys is None:
                refine_keys = (list(api_keys) if provider == "gemini"
                               else keypool.load_keys("gemini"))
            refine_keys = [k for k in refine_keys if k]
            refined_paths, refined = _refine_chunks_with_audio(
                chunks, chunk_srt_paths, os.path.join(work_dir, "refined"),
                report, refine_keys, models, language, style, refine_vpn,
                cancel_check=check_cancel,
            )
            if refined:
                chunk_srt_paths = refined_paths
            if stats is not None:
                stats["audio_refined"] = refined
        elif refine_keys is None:
            refine_keys = keypool.load_keys("openrouter")
    if stats is not None:
        stats["chunk_count"] = len(chunk_srt_paths)
        stats["chunks"] = total_chunks
        stats["provider"] = provider
        stats["language"] = locked_lang or language
        stats["refine_provider"] = refine_provider if deep else None

    # Merge AFTER the audio-aware pass so the merge still owns the offsets/windows.
    report(0, t("tr.progress.merging"), 95)
    try:
        merged = merge_srt_chunks(chunk_srt_paths, starts, windows)
    except Exception as e:
        raise ProcessingError(t("tr.stage.merge"), str(e))
    check_cancel()
    report(100, t("tr.progress.merging_done"), 97)

    # Text pass: the OpenRouter reviewer always works here; Gemini only as a
    # fallback for when its audio pass could not run.
    if deep and (refined == 0 or refine_provider == "openrouter"):
        report(30, t("tr.progress.deep_refine"), 97)
        merged = _refine_srt(merged, work_dir, report, refine_keys,
                             provider=refine_provider, models=refine_models)
        report(100, t("tr.progress.deep_refine_done"), 98)

    results = {}
    out_dir_final = final_dir or work_dir
    try:
        if output_format in ("srt", "both"):
            srt_out = os.path.join(out_dir_final, base + ".srt")
            with open(srt_out, "w", encoding="utf-8") as f:
                f.write(merged)
            results["srt"] = srt_out
        if output_format in ("txt", "both"):
            txt_out = os.path.join(out_dir_final, base + ".txt")
            with open(txt_out, "w", encoding="utf-8") as f:
                f.write(srt_to_plain_text(merged) + "\n")
            results["txt"] = txt_out
    except Exception as e:
        raise ProcessingError(t("tr.stage.write_output"), str(e))
    report(100, t("tr.progress.output_written"), 99)
    return results