"""Engine — bridges the desktop GUI to the Arion-bot core modules.

Every heavy job (transcription, download, translation) runs synchronously in a
worker thread; the GUI passes `progress` callbacks and marshals the updates to
the Tk main loop itself. Cancellation is cooperative: a threading.Event checked
by the core modules (`cancel_check`) and by us between stages.
"""

import os
import threading

from core import config, downloader, keypool, srt_utils, transcribe, translate

# --- Choice tables (mirrors of the bot's menus) ------------------------------

LANGUAGES = [
    ("auto", "🔎 تشخیص خودکار / auto"),
    ("fa", "🇮🇷 فارسی / Persian"),
    ("en", "🇬🇧 انگلیسی / English"),
    ("de", "🇩🇪 آلمانی / German"),
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
    ("audio", "🎧 MP3 (فشرده / compressed)"),
    ("m4a", "🎵 M4A"),
    ("opus", "🎵 Opus"),
    ("flac", "🎼 FLAC (بدون افت / lossless)"),
]

DL_VIDEO_QUALITIES = [
    ("best", "⭐ بهترین کیفیت / best available"),
    ("2160", "4K (2160p)"),
    ("1440", "2K (1440p)"),
    ("1080", "Full HD (1080p)"),
    ("720", "HD (720p)"),
    ("480", "480p"),
    ("360", "360p"),
    ("240", "240p"),
    ("144", "144p"),
]

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
    """One cancellable job with progress plumbing for the GUI."""

    def __init__(self, progress_cb=None):
        self.progress_cb = progress_cb
        self.cancel_event = threading.Event()
        self.running = False

    def cancel(self):
        self.cancel_event.set()

    @property
    def cancelled(self):
        return self.cancel_event.is_set()

    def _check(self):
        if self.cancel_event.is_set():
            raise Cancelled()

    def report(self, stage_pct, label, overall=None, note=""):
        if self.progress_cb:
            try:
                ov = overall if overall is not None else stage_pct
                self.progress_cb(stage_pct, label, ov, note)
            except Exception:
                pass

    def dl_progress(self):
        """Adapter for yt-dlp's progress(pct, speed, eta) callbacks."""
        def cb(pct, speed, eta):
            try:
                pct = float(pct)
            except Exception:
                pct = 0
            self.report(pct, f"📥 {speed}   ·   ⏳ ETA {eta}", pct)
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


# --- 1) Transcription (file / YouTube audio) ----------------------------------

def transcribe_file(job: Job, api_keys, input_path, out_dir, language="auto",
                    output_format="srt", style=srt_utils.STYLE_SENTENCE,
                    provider="groq", deep=False, refine_keys=None):
    """Run the full subtitle pipeline on a local media file. Returns dict of paths."""
    job._check()
    if not api_keys:
        raise RuntimeError("هیچ کلید API تنظیم نشده؛ اول از تب تنظیمات کلید بگذار.")
    os.makedirs(out_dir, exist_ok=True)
    work_dir = os.path.join(
        out_dir, ".work_" + os.path.splitext(os.path.basename(input_path))[0])
    os.makedirs(work_dir, exist_ok=True)

    job.report(0, "شروع پردازش...", 2)
    result = transcribe.transcribe_file(
        api_keys=api_keys,
        input_path=input_path,
        work_dir=work_dir,
        language=language,
        output_format=output_format,
        style=style,
        progress=job.report,
        provider=provider,
        deep=deep,
        cancel_check=job._check,
        refine_keys=refine_keys,
    )
    job.report(100, "تمام شد ✅", 100)
    return result


def transcribe_youtube(job: Job, api_keys, url, out_dir, language="auto",
                       output_format="srt", style=srt_utils.STYLE_SENTENCE,
                       provider="groq", deep=False, refine_keys=None,
                       cookies=None):
    """Download the YouTube audio track first, then transcribe it."""
    job._check()
    audio_path = downloader.download_youtube_audio(
        url, out_dir, cookies_path=cookie_paths(cookies), use_vpn=False,
        progress=job.dl_progress())
    job.report(100, "دانلود صدا تمام شد؛ حالا زیرنویس...", 18)
    return transcribe_file(job, api_keys, audio_path, out_dir, language,
                           output_format, style, provider, deep, refine_keys)


# --- 2) YouTube downloads -------------------------------------------------------

def download_media(job: Job, url, out_dir, quality="audio", cookies=None):
    """Download audio or video. Returns the local file path."""
    job._check()
    os.makedirs(out_dir, exist_ok=True)
    audio_codes = {code for code, _ in DL_AUDIO_QUALITIES}
    if quality in audio_codes:
        return downloader.download_youtube_audio(
            url, out_dir, cookies_path=cookie_paths(cookies), use_vpn=False,
            progress=job.dl_progress())
    return downloader.download_youtube_video(
        url, out_dir, quality=quality, cookies_path=cookie_paths(cookies),
        use_vpn=False, progress=job.dl_progress())


def download_subtitles(job: Job, url, out_dir, lang=None, cookies=None):
    """Grab YouTube's own (auto/manual) SRT. Returns (path, target, kind, title)."""
    job._check()
    os.makedirs(out_dir, exist_ok=True)
    return downloader.download_youtube_subtitle(
        url, out_dir, lang=lang, cookies_path=cookie_paths(cookies), use_vpn=False)


def download_info_txt(job: Job, url, out_dir, cookies=None):
    """Export title / metadata / description as .txt. Returns (path, title)."""
    job._check()
    os.makedirs(out_dir, exist_ok=True)
    return downloader.download_youtube_info_txt(
        url, out_dir, cookies_path=cookie_paths(cookies), use_vpn=False)


def probe_sizes(url, cookies=None):
    """Best-effort size estimates per quality key (background task)."""
    return downloader.probe_sizes(url, cookies_path=cookie_paths(cookies), use_vpn=False)


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
        raise RuntimeError("هیچ کلید Gemini تنظیم نشده؛ اول از تب تنظیمات کلید بگذار.")
    with open(srt_path, encoding="utf-8", errors="ignore") as f:
        srt_text = f.read()

    def progress(pct, label):
        job.report(pct, label, max(20, min(95, int(pct))))

    out_text = translate.translate_srt(
        srt_text, target_language, style=style, keys=keys, progress=progress)
    job._check()

    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(srt_path))[0]
    suffix = _URL_SUFFIX.get((lang_code or "").lower()) or (target_language or "lang")[:3].lower()
    out_path = os.path.join(out_dir, f"{base}_{suffix}.srt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out_text)
    job.report(100, "ترجمه تمام شد ✅", 100)
    return out_path
