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

# --- Choice tables (mirrors of the bot's menus) ------------------------------

LANGUAGES = [
    ("auto", "🔎 تشخیص خودکار / auto"),
    ("fa", "🇮🇷 فارسی / Persian"),
    ("en", "🇬🇧 انگلیسی / English"),
    ("de", "🇩🇪 آلمانی / German"),
    ("ar", "🇸🇦 عربی / Arabic"),
    ("tr", "🇹🇷 ترکی / Turkish"),
    ("ru", "🇷🇺 روسی / Russian"),
]

SUBTITLE_STYLES = [
    (srt_utils.STYLE_SENTENCE, "📝 جمله‌ای (استاندارد / standard)"),
    (srt_utils.STYLE_SHORT, "✂️ خطوط کوتاه (برای ترجمه / short)"),
    (srt_utils.STYLE_WORD, "🔤 کلمه‌به‌کلمه (word-level)"),
]

PROVIDERS = [
    ("groq", "⚡ Groq (Whisper)"),
    ("gemini", "✨ Gemini (deep listen)"),
]

DL_AUDIO_QUALITIES = [
    ("audio", "🎧 MP3 (64k mono — سبک)"),
    ("m4a", "🎵 M4A (بدون تبدیل)"),
    ("opus", "🎵 Opus"),
    ("flac", "🎼 FLAC (بدون افت)"),
]

DL_VIDEO_QUALITIES = [
    ("best", "⭐ بهترین کیفیت موجود"),
    ("2160", "4K (2160p)"),
    ("1440", "2K (1440p)"),
    ("1080", "Full HD (1080p)"),
    ("720", "HD (720p)"),
    ("480", "480p"),
    ("360", "360p"),
    ("240", "240p"),
    ("144", "144p"),
]

# Short labels used when showing size estimates.
DL_VIDEO_LABELS = {
    "best": "بهترین", "2160": "4K", "1440": "2K", "1080": "1080p",
    "720": "720p", "480": "480p", "360": "360p", "240": "240p", "144": "144p",
}
DL_AUDIO_LABELS = {"mp3": "MP3", "m4a": "M4A", "opus": "Opus", "flac": "FLAC",
                   "audio": "MP3"}

TRANSLATE_LANGUAGES = [
    ("fa", "🇮🇷 فارسی / Persian", "Persian"),
    ("en", "🇬🇧 انگلیسی / English", "English"),
    ("ar", "🇸🇦 عربی / Arabic", "Arabic"),
    ("tr", "🇹🇷 ترکی / Turkish", "Turkish"),
    ("de", "🇩🇪 آلمانی / German", "German"),
    ("fr", "🇫🇷 فرانسوی / French", "French"),
    ("es", "🇪🇸 اسپانیایی / Spanish", "Spanish"),
    ("ru", "🇷🇺 روسی / Russian", "Russian"),
    ("it", "🇮🇹 ایتالیایی / Italian", "Italian"),
]

TRANSLATE_STYLES = [
    ("casual", "😎 خودمانی و محاوره‌ای / casual"),
    ("formal", "🎩 رسمی / formal"),
    ("educational", "📚 آموزشی / فنی / educational"),
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
            parts = [f"📥 {pct:.1f}%"]
            if speed:
                parts.append(speed)
            if eta:
                parts.append(f"⏳ {eta}")
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
        raise RuntimeError("هیچ کلید API تنظیم نشده؛ اول از تب «تنظیمات» کلید بگذار.")
    if not os.path.exists(input_path):
        raise RuntimeError(f"فایل ورودی پیدا نشد:\n{input_path}")
    os.makedirs(out_dir, exist_ok=True)

    work_dir = os.path.join(config.WORK_DIR, "transcribe",
                            f"{_safe_stem(input_path)}_{time.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(work_dir, exist_ok=True)

    job.log(f"🎬 فایل ورودی: {input_path}")
    job.log(f"📁 پوشه‌ی خروجی: {out_dir}")
    job.log(f"⚙️ موتور: {provider} · زبان: {language} · فرمت: {output_format}")
    job.report(0, "شروع پردازش…", progress_start + 1)

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
        job.log(f"✅ {key.upper()} ساخته شد → {path}")
    job.report(100, "تمام شد ✅", 100)
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
    job.log(f"🔗 لینک: {url}")
    job.report(0, "شروع دانلود صدا از یوتیوب…", 1)

    audio_path = downloader.download_youtube_audio(
        url, dl_dir, cookies_path=cookie_paths(cookies), use_vpn=False,
        progress=job.dl_progress(start=0, span=15), cancel_event=job.cancel_event)
    job.log(f"🎧 صدا دانلود شد: {audio_path}")
    job.report(15, "دانلود صدا تمام شد؛ شروع ساخت زیرنویس…", 16)

    return transcribe_file(
        job, api_keys, audio_path, out_dir, language=language,
        output_format=output_format, style=style, provider=provider, deep=deep,
        refine_keys=refine_keys, progress_start=16, progress_span=84)


# --- 2) YouTube downloads -------------------------------------------------------

def download_media(job: Job, url, out_dir, quality="audio", cookies=None):
    """Download audio or video. Returns the local file path."""
    job._check()
    os.makedirs(out_dir, exist_ok=True)
    job.log(f"⬇️ شروع دانلود (کیفیت: {quality})")
    job.report(0, "در حال آماده‌سازی دانلود…", 1)
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
    job.report(0, "در حال گرفتن زیرنویس یوتیوب…", 1)
    try:
        path, target, kind, title = downloader.download_youtube_subtitle(
            url, out_dir, lang=lang, cookies_path=cookie_paths(cookies),
            use_vpn=False, progress=job.dl_progress())
    except downloader.DownloadCancelled as exc:
        raise Cancelled() from exc
    job.log(f"📝 زبان: {target} · نوع: {kind}")
    job.report(100, "زیرنویس دریافت شد ✅", 100)
    return path, target, kind, title


def download_info_txt(job: Job, url, out_dir, cookies=None):
    """Export title / metadata / description as .txt. Returns (path, title)."""
    job._check()
    os.makedirs(out_dir, exist_ok=True)
    job.report(0, "در حال خواندن مشخصات ویدیو…", 1)
    try:
        path, title = downloader.download_youtube_info_txt(
            url, out_dir, cookies_path=cookie_paths(cookies), use_vpn=False,
            progress=job.dl_progress())
    except downloader.DownloadCancelled as exc:
        raise Cancelled() from exc
    job.report(100, "فایل مشخصات ساخته شد ✅", 100)
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
        raise RuntimeError("هیچ کلید Gemini تنظیم نشده؛ اول از تب «تنظیمات» کلید بگذار.")
    if not os.path.exists(srt_path):
        raise RuntimeError(f"فایل SRT پیدا نشد:\n{srt_path}")

    with open(srt_path, encoding="utf-8", errors="ignore") as f:
        srt_text = f.read()
    items = translate.parse_srt(srt_text)
    if not items:
        raise RuntimeError("این فایل SRT معتبر نیست (هیچ خط زمانی پیدا نشد).")
    job.log(f"📄 {len(items)} خط زیرنویس · {len(keys)} کلید Gemini · مقصد: {target_language}")
    job.report(0, "شروع ترجمه…", 1)

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
    job.log(f"✅ ترجمه ذخیره شد → {out_path}")
    job.report(100, "ترجمه تمام شد ✅", 100)
    return out_path


# --- 4) Key diagnostics (Settings tab "test" buttons) -------------------------

def test_api_key(provider, key):
    """Cheap live check so users can see WHY a key does not work."""
    import requests
    key = (key or "").strip()
    if not key:
        return False, "کلید خالی است."
    try:
        if provider == "groq":
            r = requests.get("https://api.groq.com/openai/v1/models",
                             headers={"Authorization": f"Bearer {key}"}, timeout=25)
            if r.status_code == 200:
                return True, "✅ کلید Groq سالم است."
            return False, f"❌ Groq: HTTP {r.status_code} — {r.text[:200]}"
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                         params={"key": key}, timeout=25)
        if r.status_code == 200:
            names = [m.get("name", "") for m in (r.json().get("models") or [])]
            has_flash = any("flash" in n for n in names)
            extra = "" if has_flash else " (هیچ مدل flash در دسترس نیست)"
            return True, f"✅ کلید Gemini سالم است{extra}."
        return False, f"❌ Gemini: HTTP {r.status_code} — {r.text[:200]}"
    except Exception as exc:
        return False, f"❌ خطای شبکه: {exc}"