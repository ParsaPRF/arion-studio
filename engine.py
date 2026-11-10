"""Engine — bridges the desktop GUI to the Arion core modules.

Every heavy job (transcription, download, translation) runs synchronously in a
worker thread. The GUI hands us callbacks and marshals them to the Tk loop.

Progress model
--------------
``Job.report(...)`` carries a *monotonically increasing* overall percentage
(never goes backwards, even when a stage restarts its own 0-100 counter) plus a
human label. ``Job.snapshot()`` exposes elapsed time, a smoothed ETA and the
current transfer speed, which is what the GUI renders in its status line.

Cancellation
------------
``Job.cancel_event`` is set from the GUI thread; ``job._check()`` raises
``Cancelled`` and is passed into the core modules as ``cancel_check``. Downloader
child processes are killed through ``cancel_event``.
"""

import os
import re
import threading
import time

from core import config, downloader, keypool, srt_utils, transcribe, translate
from i18n import t

# --- Choice tables (mirrors of the bot's menus) ------------------------------
# Labels are i18n keys: resolve each one with ``t(label)`` before displaying it.

LANGUAGES = [
    ("auto", "engine.lang.auto"),
    ("fa", "engine.lang.fa"),
    ("en", "engine.lang.en"),
    ("de", "engine.lang.de"),
    ("ar", "engine.lang.ar"),
    ("tr", "engine.lang.tr"),
    ("ru", "engine.lang.ru"),
]

SUBTITLE_STYLES = [
    (srt_utils.STYLE_SENTENCE, "engine.style.sentence"),
    (srt_utils.STYLE_SHORT, "engine.style.short"),
    (srt_utils.STYLE_WORD, "engine.style.word"),
]

PROVIDERS = [
    ("groq", "engine.provider.groq"),
    ("gemini", "engine.provider.gemini"),
]

DL_AUDIO_QUALITIES = [
    ("audio", "engine.quality.audio.audio"),
    ("m4a", "engine.quality.audio.m4a"),
    ("opus", "engine.quality.audio.opus"),
    ("flac", "engine.quality.audio.flac"),
]

DL_VIDEO_QUALITIES = [
    ("best", "engine.quality.video.best"),
    ("2160", "engine.quality.video.2160"),
    ("1440", "engine.quality.video.1440"),
    ("1080", "engine.quality.video.1080"),
    ("720", "engine.quality.video.720"),
    ("480", "engine.quality.video.480"),
    ("360", "engine.quality.video.360"),
    ("240", "engine.quality.video.240"),
    ("144", "engine.quality.video.144"),
]

# Short labels used when showing size estimates.
DL_VIDEO_LABELS = {
    "best": "engine.quality.video_short.best",
    "2160": "engine.quality.video_short.2160",
    "1440": "engine.quality.video_short.1440",
    "1080": "engine.quality.video_short.1080",
    "720": "engine.quality.video_short.720",
    "480": "engine.quality.video_short.480",
    "360": "engine.quality.video_short.360",
    "240": "engine.quality.video_short.240",
    "144": "engine.quality.video_short.144",
}
DL_AUDIO_LABELS = {
    "mp3": "engine.quality.audio_short.mp3",
    "m4a": "engine.quality.audio_short.m4a",
    "opus": "engine.quality.audio_short.opus",
    "flac": "engine.quality.audio_short.flac",
    "audio": "engine.quality.audio_short.audio",
}

TRANSLATE_LANGUAGES = [
    ("fa", "engine.lang.fa", "Persian"),
    ("en", "engine.lang.en", "English"),
    ("ar", "engine.lang.ar", "Arabic"),
    ("tr", "engine.lang.tr", "Turkish"),
    ("de", "engine.lang.de", "German"),
    ("fr", "engine.lang.fr", "French"),
    ("es", "engine.lang.es", "Spanish"),
    ("ru", "engine.lang.ru", "Russian"),
    ("it", "engine.lang.it", "Italian"),
]

TRANSLATE_STYLES = [
    ("casual", "engine.translate_style.casual"),
    ("formal", "engine.translate_style.formal"),
    ("educational", "engine.translate_style.educational"),
]

_URL_SUFFIX = {"fa": "fa", "en": "en", "ar": "ar", "tr": "tr", "de": "de",
               "fr": "fr", "es": "es", "ru": "ru", "it": "it"}


class Cancelled(Exception):
    """Raised when the user presses Stop; every tab treats it as a soft stop."""


class Job:
    """One cancellable job with progress/ETA plumbing for the GUI."""

    def __init__(self, progress_cb=None, log_cb=None):
        self.progress_cb = progress_cb
        self.log_cb = log_cb
        self.cancel_event = threading.Event()
        self.running = False
        self.started = time.monotonic()
        self.overall = 0.0
        self.stage_pct = 0.0
        self.label = ""
        self.note = ""
        self.speed = ""
        self.detail = ""
        self._log_lock = threading.Lock()

    # -- cancellation --------------------------------------------------------
    def cancel(self):
        self.cancel_event.set()

    @property
    def cancelled(self):
        return self.cancel_event.is_set()

    def _check(self):
        if self.cancel_event.is_set():
            raise Cancelled()

    # -- reporting -----------------------------------------------------------
    def log(self, line):
        """Worker-safe log line (the GUI queues it onto the Tk loop)."""
        if not self.log_cb:
            return
        try:
            with self._log_lock:
                self.log_cb(str(line))
        except Exception:
            pass

    def report(self, stage_pct, label, overall=None, note=""):
        base = overall if overall is not None else stage_pct
        try:
            ov = float(base)
        except (TypeError, ValueError):
            ov = self.overall
        ov = max(0.0, min(100.0, ov))
        # Never tick backwards: some stages restart their own 0-100 counter.
        if ov + 0.05 < self.overall:
            ov = self.overall
        self.overall = ov
        try:
            self.stage_pct = float(stage_pct)
        except (TypeError, ValueError):
            self.stage_pct = ov
        if label:
            self.label = str(label)
        self.note = str(note or "")
        if self.progress_cb:
            try:
                self.progress_cb(self.stage_pct, self.label, self.overall, self.note)
            except Exception:
                pass

    def snapshot(self):
        elapsed = max(0.0, time.monotonic() - self.started)
        eta = None
        if self.overall >= 3.0 and elapsed >= 3.0:
            eta = max(0.0, elapsed * (100.0 - self.overall) / self.overall)
        return {
            "overall": self.overall,
            "stage_pct": self.stage_pct,
            "label": self.label,
            "note": self.note,
            "elapsed": elapsed,
            "eta": eta,
            "speed": self.speed,
            "detail": self.detail,
        }

    def dl_progress(self, start=0.0, span=100.0):
        """Adapter for the downloader's (pct, speed, eta, message) callback."""
        def cb(pct=None, speed="", eta="", message=""):
            if message:
                self.log(message)
            if pct is None:
                if message:
                    self.report(self.overall, message, self.overall)
                return
            try:
                pct = max(0.0, min(100.0, float(pct)))
            except (TypeError, ValueError):
                return
            if speed:
                self.speed = speed
            ov = start + (pct / 100.0) * span
            parts = [t("engine.progress.download_percent", pct=pct)]
            if speed:
                parts.append(speed)
            if eta:
                parts.append(t("engine.progress.eta", eta=eta))
            self.report(pct, "  ·  ".join(parts), ov)
        return cb


def _mapped(job, start, span):
    """Wrap job.report so a core module's 0-100 progress maps into [start, start+span]."""
    def cb(stage_pct, label, overall=None, note=""):
        base = overall if overall is not None else stage_pct
        try:
            base = float(base)
        except (TypeError, ValueError):
            base = job.overall
        job.report(stage_pct, label, start + (max(0.0, min(100.0, base)) / 100.0) * span,
                   note)
    return cb


# --- Key helpers --------------------------------------------------------------

def groq_keys(user_key=None):
    """The user's saved key first, then the pool, then an .env default."""
    keys = []
    if user_key:
        keys.append(user_key.strip())
    keys += keypool.load_keys("groq")
    if config.DEFAULT_GROQ_API_KEY:
        keys.append(config.DEFAULT_GROQ_API_KEY)
    seen, out = set(), []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def gemini_keys(user_key=None):
    keys = []
    if user_key:
        keys.append(user_key.strip())
    keys += keypool.load_keys("gemini")
    seen, out = set(), []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def save_key(provider, key):
    added, total = keypool.add_key(key, provider)
    return added, total


def cookie_paths(user_cookie_path=None):
    path = (user_cookie_path or "").strip() or config.YT_COOKIES_FILE
    if path and os.path.exists(path):
        return path
    return None


def _safe_stem(path):
    stem = os.path.splitext(os.path.basename(path or "input"))[0]
    stem = re.sub(r"[^\w\u0600-\u06FF.-]+", "_", stem).strip("._")
    return (stem or "input")[:60]


# --- Environment checks -------------------------------------------------------

def environment_status():
    """Facts the GUI shows in its log/settings: ffmpeg, yt-dlp, folders."""
    from core import audio as audio_mod
    return {
        "ffmpeg": audio_mod.available(),
        "ytdlp": downloader.ytdlp_available(),
        "work_dir": config.WORK_DIR,
        "keys_groq": len(groq_keys()),
        "keys_gemini": len(gemini_keys()),
    }


# --- 1) Transcription (file / YouTube audio) ----------------------------------

def transcribe_file(job: Job, api_keys, input_path, out_dir, language="auto",
                    output_format="srt", style=srt_utils.STYLE_SENTENCE,
                    provider="groq", deep=False, refine_keys=None, cookies=None,
                    progress_start=0.0, progress_span=100.0):
    """Run the full subtitle pipeline on a local media file. Returns dict of paths."""
    job._check()
    if not api_keys:
        raise RuntimeError(t("engine.err.no_api_keys"))
    if not os.path.exists(input_path):
        raise RuntimeError(t("engine.err.input_missing", path=input_path))
    os.makedirs(out_dir, exist_ok=True)

    work_dir = os.path.join(config.WORK_DIR, "transcribe",
                            f"{_safe_stem(input_path)}_{time.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(work_dir, exist_ok=True)

    job.log(t("engine.log.input_file", path=input_path))
    job.log(t("engine.log.out_dir", path=out_dir))
    job.log(t("engine.log.engine_info", provider=provider, language=language,
              fmt=output_format))
    job.report(0, t("engine.progress.start_processing"), progress_start + 1)

    progress = _mapped(job, progress_start, progress_span)
    result = transcribe.transcribe_file(
        api_keys=api_keys,
        input_path=input_path,
        work_dir=work_dir,
        language=language,
        output_format=output_format,
        style=style,
        progress=progress,
        provider=provider,
        deep=deep,
        cancel_check=job._check,
        refine_keys=refine_keys,
        final_dir=out_dir,
    )
    for key, path in (result or {}).items():
        job.log(t("engine.log.artifact_saved", kind=key.upper(), path=path))
    job.report(100, t("engine.progress.done"), 100)
    return result


def transcribe_youtube(job: Job, api_keys, url, out_dir, language="auto",
                       output_format="srt", style=srt_utils.STYLE_SENTENCE,
                       provider="groq", deep=False, refine_keys=None,
                       cookies=None):
    """Download the YouTube audio track first, then transcribe it."""
    job._check()
    os.makedirs(out_dir, exist_ok=True)
    dl_dir = os.path.join(config.WORK_DIR, "downloads")
    os.makedirs(dl_dir, exist_ok=True)
    job.log(t("engine.log.link", url=url))
    job.report(0, t("engine.progress.youtube_audio_start"), 1)

    audio_path = downloader.download_youtube_audio(
        url, dl_dir, cookies_path=cookie_paths(cookies), use_vpn=False,
        progress=job.dl_progress(start=0, span=15), cancel_event=job.cancel_event)
    job.log(t("engine.log.audio_downloaded", path=audio_path))
    job.report(15, t("engine.progress.audio_ready"), 16)

    return transcribe_file(
        job, api_keys, audio_path, out_dir, language=language,
        output_format=output_format, style=style, provider=provider, deep=deep,
        refine_keys=refine_keys, progress_start=16, progress_span=84)


# --- 2) YouTube downloads -------------------------------------------------------

def download_media(job: Job, url, out_dir, quality="audio", cookies=None):
    """Download audio or video. Returns the local file path."""
    job._check()
    os.makedirs(out_dir, exist_ok=True)
    job.log(t("engine.log.download_started", quality=quality))
    job.report(0, t("engine.progress.download_preparing"), 1)
    try:
        if str(quality) == "audio":
            return downloader.download_youtube_audio(
                url, out_dir, cookies_path=cookie_paths(cookies), use_vpn=False,
                progress=job.dl_progress(), cancel_event=job.cancel_event)
        return downloader.download_youtube_video(
            url, out_dir, quality=quality, cookies_path=cookie_paths(cookies),
            use_vpn=False, progress=job.dl_progress(),
            cancel_event=job.cancel_event)
    except downloader.DownloadCancelled as exc:
        raise Cancelled() from exc


def download_subtitles(job: Job, url, out_dir, lang=None, cookies=None):
    """Grab YouTube's own (auto/manual) SRT. Returns (path, target, kind, title)."""
    job._check()
    os.makedirs(out_dir, exist_ok=True)
    job.report(0, t("engine.progress.subtitle_fetch"), 1)
    try:
        path, target, kind, title = downloader.download_youtube_subtitle(
            url, out_dir, lang=lang, cookies_path=cookie_paths(cookies),
            use_vpn=False, progress=job.dl_progress())
    except downloader.DownloadCancelled as exc:
        raise Cancelled() from exc
    job.log(t("engine.log.subtitle_info", target=target, kind=kind))
    job.report(100, t("engine.progress.subtitle_ready"), 100)
    return path, target, kind, title


def download_info_txt(job: Job, url, out_dir, cookies=None):
    """Export title / metadata / description as .txt. Returns (path, title)."""
    job._check()
    os.makedirs(out_dir, exist_ok=True)
    job.report(0, t("engine.progress.info_reading"), 1)
    try:
        path, title = downloader.download_youtube_info_txt(
            url, out_dir, cookies_path=cookie_paths(cookies), use_vpn=False,
            progress=job.dl_progress())
    except downloader.DownloadCancelled as exc:
        raise Cancelled() from exc
    job.report(100, t("engine.progress.info_saved"), 100)
    return path, title


def probe_sizes(url, cookies=None, job=None):
    """Size estimates per quality key (runs as a background task)."""
    return downloader.probe_sizes(url, cookies_path=cookie_paths(cookies),
                                  use_vpn=False,
                                  progress=job.dl_progress() if job else None)


def playlist_items(url, cookies=None, max_items=25):
    return downloader.list_playlist(url, cookies_path=cookie_paths(cookies),
                                    use_vpn=False, max_items=max_items)


# --- 3) Translation -----------------------------------------------------------

def translate_srt_file(job: Job, srt_path, out_dir, target_language="Persian",
                       style="casual", lang_code="en", gemini_keys_list=None):
    """Translate an SRT file with Gemini. Returns the new SRT file path."""
    job._check()
    keys = gemini_keys_list or gemini_keys()
    if not keys:
        raise RuntimeError(t("engine.err.no_gemini_keys"))
    if not os.path.exists(srt_path):
        raise RuntimeError(t("engine.err.srt_missing", path=srt_path))

    with open(srt_path, encoding="utf-8", errors="ignore") as f:
        srt_text = f.read()
    items = translate.parse_srt(srt_text)
    if not items:
        raise RuntimeError(t("engine.err.srt_invalid"))
    job.log(t("engine.log.translate_start", lines=len(items), keys=len(keys),
              target=target_language))
    job.report(0, t("engine.progress.translate_start"), 1)

    def progress(pct, label):
        # Reserve the last percent for writing the file.
        job.report(pct, label, max(1.0, min(99.0, float(pct))))

    out_text = translate.translate_srt(
        srt_text, target_language, style=style, keys=keys,
        progress=progress, cancel_check=job._check)
    job._check()

    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(srt_path))[0]
    suffix = (_URL_SUFFIX.get((lang_code or "").lower())
              or (target_language or "lang")[:3].lower())
    out_path = os.path.join(out_dir, f"{base}_{suffix}.srt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out_text)
    job.log(t("engine.log.translation_saved", path=out_path))
    job.report(100, t("engine.progress.translate_done"), 100)
    return out_path


# --- 4) Key diagnostics (Settings tab "test" buttons) -------------------------

def test_api_key(provider, key):
    """Cheap live check so users can see WHY a key does not work."""
    import requests
    key = (key or "").strip()
    if not key:
        return False, t("engine.err.empty_key")
    try:
        if provider == "groq":
            r = requests.get("https://api.groq.com/openai/v1/models",
                             headers={"Authorization": f"Bearer {key}"}, timeout=25)
            if r.status_code == 200:
                return True, t("engine.key.groq_ok")
            return False, t("engine.key.groq_http", code=r.status_code, body=r.text[:200])
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                         params={"key": key}, timeout=25)
        if r.status_code == 200:
            names = [m.get("name", "") for m in (r.json().get("models") or [])]
            has_flash = any("flash" in n for n in names)
            extra = "" if has_flash else t("engine.key.no_flash")
            return True, t("engine.key.gemini_ok", extra=extra)
        return False, t("engine.key.gemini_http", code=r.status_code, body=r.text[:200])
    except Exception as exc:
        return False, t("engine.key.network_error", error=exc)