"""Engine catalog: choice-table labels, progress labels and engine messages.

Keys are grouped by the engine.py constant or message family they belong to:
``engine.lang.*`` (LANGUAGES / TRANSLATE_LANGUAGES), ``engine.style.*``
(SUBTITLE_STYLES), ``engine.provider.*`` (PROVIDERS), ``engine.quality.*``
(DL_*_QUALITIES and the short DL_*_LABELS), ``engine.translate_style.*``
(TRANSLATE_STYLES), plus ``engine.log.*``, ``engine.progress.*``,
``engine.err.*`` and ``engine.key.*`` for the runtime messages.
"""

CATALOG = {
    # --- LANGUAGES / TRANSLATE_LANGUAGES -------------------------------------
    "engine.deep.gemini": {"en": "Gemini (hears the audio)", "fa": "Gemini (صدا را می‌شنود)"},
    "engine.deep.openrouter": {"en": "OpenRouter free models (text only)", "fa": "مدل‌های رایگان OpenRouter (فقط متن)"},
    "engine.key.openrouter_http": {"en": "OpenRouter rejected the key: {body}", "fa": "OpenRouter کلید را نپذیرفت: {body}"},
    "engine.key.openrouter_ok": {"en": "✅ OpenRouter key works{extra}", "fa": "✅ کلید OpenRouter کار می‌کند{extra}"},
    "engine.lang.auto": {
        "en": "🔎 Auto-detect",
        "fa": "🔎 تشخیص خودکار / auto",
    },
    "engine.lang.fa": {
        "en": "🇮🇷 Persian",
        "fa": "🇮🇷 فارسی / Persian",
    },
    "engine.lang.en": {
        "en": "🇬🇧 English",
        "fa": "🇬🇧 انگلیسی / English",
    },
    "engine.lang.de": {
        "en": "🇩🇪 German",
        "fa": "🇩🇪 آلمانی / German",
    },
    "engine.lang.ar": {
        "en": "🇸🇦 Arabic",
        "fa": "🇸🇦 عربی / Arabic",
    },
    "engine.lang.tr": {
        "en": "🇹🇷 Turkish",
        "fa": "🇹🇷 ترکی / Turkish",
    },
    "engine.lang.ru": {
        "en": "🇷🇺 Russian",
        "fa": "🇷🇺 روسی / Russian",
    },
    "engine.lang.fr": {
        "en": "🇫🇷 French",
        "fa": "🇫🇷 فرانسوی / French",
    },
    "engine.lang.es": {
        "en": "🇪🇸 Spanish",
        "fa": "🇪🇸 اسپانیایی / Spanish",
    },
    "engine.lang.it": {
        "en": "🇮🇹 Italian",
        "fa": "🇮🇹 ایتالیایی / Italian",
    },

    # --- SUBTITLE_STYLES ------------------------------------------------------
    "engine.style.sentence": {
        "en": "📝 Sentence (standard)",
        "fa": "📝 جمله‌ای (استاندارد / standard)",
    },
    "engine.style.short": {
        "en": "✂️ Short lines (for translation)",
        "fa": "✂️ خطوط کوتاه (برای ترجمه / short)",
    },
    "engine.style.word": {
        "en": "🔤 Word-by-word (word-level)",
        "fa": "🔤 کلمه‌به‌کلمه (word-level)",
    },

    # --- PROVIDERS ------------------------------------------------------------
    "engine.provider.groq": {
        "en": "⚡ Groq (Whisper)",
        "fa": "⚡ Groq (Whisper)",
    },
    "engine.provider.gemini": {
        "en": "✨ Gemini (deep listen)",
        "fa": "✨ Gemini (deep listen)",
    },

    # --- DL_AUDIO_QUALITIES ---------------------------------------------------
    "engine.quality.audio.audio": {
        "en": "🎧 MP3 (64k mono — light)",
        "fa": "🎧 MP3 (64k mono — سبک)",
    },
    "engine.quality.audio.m4a": {
        "en": "🎵 M4A (no conversion)",
        "fa": "🎵 M4A (بدون تبدیل)",
    },
    "engine.quality.audio.opus": {
        "en": "🎵 Opus",
        "fa": "🎵 Opus",
    },
    "engine.quality.audio.flac": {
        "en": "🎼 FLAC (lossless)",
        "fa": "🎼 FLAC (بدون افت)",
    },

    # --- DL_VIDEO_QUALITIES ---------------------------------------------------
    "engine.quality.video.best": {
        "en": "⭐ Best available quality",
        "fa": "⭐ بهترین کیفیت موجود",
    },
    "engine.quality.video.2160": {"en": "4K (2160p)", "fa": "4K (2160p)"},
    "engine.quality.video.1440": {"en": "2K (1440p)", "fa": "2K (1440p)"},
    "engine.quality.video.1080": {"en": "Full HD (1080p)", "fa": "Full HD (1080p)"},
    "engine.quality.video.720": {"en": "HD (720p)", "fa": "HD (720p)"},
    "engine.quality.video.480": {"en": "480p", "fa": "480p"},
    "engine.quality.video.360": {"en": "360p", "fa": "360p"},
    "engine.quality.video.240": {"en": "240p", "fa": "240p"},
    "engine.quality.video.144": {"en": "144p", "fa": "144p"},

    # --- DL_VIDEO_LABELS (short, size estimates) ------------------------------
    "engine.quality.video_short.best": {"en": "Best", "fa": "بهترین"},
    "engine.quality.video_short.2160": {"en": "4K", "fa": "4K"},
    "engine.quality.video_short.1440": {"en": "2K", "fa": "2K"},
    "engine.quality.video_short.1080": {"en": "1080p", "fa": "1080p"},
    "engine.quality.video_short.720": {"en": "720p", "fa": "720p"},
    "engine.quality.video_short.480": {"en": "480p", "fa": "480p"},
    "engine.quality.video_short.360": {"en": "360p", "fa": "360p"},
    "engine.quality.video_short.240": {"en": "240p", "fa": "240p"},
    "engine.quality.video_short.144": {"en": "144p", "fa": "144p"},

    # --- DL_AUDIO_LABELS (short, size estimates) ------------------------------
    "engine.quality.audio_short.mp3": {"en": "MP3", "fa": "MP3"},
    "engine.quality.audio_short.m4a": {"en": "M4A", "fa": "M4A"},
    "engine.quality.audio_short.opus": {"en": "Opus", "fa": "Opus"},
    "engine.quality.audio_short.flac": {"en": "FLAC", "fa": "FLAC"},
    "engine.quality.audio_short.audio": {"en": "MP3", "fa": "MP3"},

    # --- TRANSLATE_STYLES -----------------------------------------------------
    "engine.translate_style.casual": {
        "en": "😎 Casual and colloquial",
        "fa": "😎 خودمانی و محاوره‌ای / casual",
    },
    "engine.translate_style.formal": {
        "en": "🎩 Formal",
        "fa": "🎩 رسمی / formal",
    },
    "engine.translate_style.educational": {
        "en": "📚 Educational / technical",
        "fa": "📚 آموزشی / فنی / educational",
    },

    # --- Log lines ------------------------------------------------------------
    "engine.log.input_file": {
        "en": "🎬 Input file: {path}",
        "fa": "🎬 فایل ورودی: {path}",
    },
    "engine.log.out_dir": {
        "en": "📁 Output folder: {path}",
        "fa": "📁 پوشه‌ی خروجی: {path}",
    },
    "engine.log.engine_info": {
        "en": "⚙️ Engine: {provider} · Language: {language} · Format: {fmt}",
        "fa": "⚙️ موتور: {provider} · زبان: {language} · فرمت: {fmt}",
    },
    "engine.log.artifact_saved": {
        "en": "✅ {kind} created → {path}",
        "fa": "✅ {kind} ساخته شد → {path}",
    },
    "engine.log.link": {
        "en": "🔗 Link: {url}",
        "fa": "🔗 لینک: {url}",
    },
    "engine.log.audio_downloaded": {
        "en": "🎧 Audio downloaded: {path}",
        "fa": "🎧 صدا دانلود شد: {path}",
    },
    "engine.log.download_started": {
        "en": "⬇️ Download started (quality: {quality})",
        "fa": "⬇️ شروع دانلود (کیفیت: {quality})",
    },
    "engine.log.subtitle_info": {
        "en": "📝 Language: {target} · Type: {kind}",
        "fa": "📝 زبان: {target} · نوع: {kind}",
    },
    "engine.log.translate_start": {
        "en": "📄 {lines} subtitle lines · {keys} Gemini keys · Target: {target}",
        "fa": "📄 {lines} خط زیرنویس · {keys} کلید Gemini · مقصد: {target}",
    },
    "engine.log.translation_saved": {
        "en": "✅ Translation saved → {path}",
        "fa": "✅ ترجمه ذخیره شد → {path}",
    },

    # --- Progress labels ------------------------------------------------------
    "engine.progress.start_processing": {
        "en": "Starting processing...",
        "fa": "شروع پردازش…",
    },
    "engine.progress.done": {
        "en": "Done ✅",
        "fa": "تمام شد ✅",
    },
    "engine.progress.youtube_audio_start": {
        "en": "Starting YouTube audio download...",
        "fa": "شروع دانلود صدا از یوتیوب…",
    },
    "engine.progress.audio_ready": {
        "en": "Audio download finished; starting subtitle generation...",
        "fa": "دانلود صدا تمام شد؛ شروع ساخت زیرنویس…",
    },
    "engine.progress.download_preparing": {
        "en": "Preparing download...",
        "fa": "در حال آماده‌سازی دانلود…",
    },
    "engine.progress.download_percent": {
        "en": "📥 {pct:.1f}%",
        "fa": "📥 {pct:.1f}%",
    },
    "engine.progress.eta": {
        "en": "⏳ {eta}",
        "fa": "⏳ {eta}",
    },
    "engine.progress.subtitle_fetch": {
        "en": "Fetching YouTube subtitles...",
        "fa": "در حال گرفتن زیرنویس یوتیوب…",
    },
    "engine.progress.subtitle_ready": {
        "en": "Subtitles received ✅",
        "fa": "زیرنویس دریافت شد ✅",
    },
    "engine.progress.info_reading": {
        "en": "Reading video metadata...",
        "fa": "در حال خواندن مشخصات ویدیو…",
    },
    "engine.progress.info_saved": {
        "en": "Metadata file created ✅",
        "fa": "فایل مشخصات ساخته شد ✅",
    },
    "engine.progress.translate_start": {
        "en": "Starting translation...",
        "fa": "شروع ترجمه…",
    },
    "engine.progress.translate_done": {
        "en": "Translation finished ✅",
        "fa": "ترجمه تمام شد ✅",
    },

    # --- Errors raised to the GUI ---------------------------------------------
    "engine.err.no_api_keys": {
        "en": "No API key is configured; add one in the Settings tab first.",
        "fa": "هیچ کلید API تنظیم نشده؛ اول از تب «تنظیمات» کلید بگذار.",
    },
    "engine.err.input_missing": {
        "en": "Input file not found:\n{path}",
        "fa": "فایل ورودی پیدا نشد:\n{path}",
    },
    "engine.err.no_gemini_keys": {
        "en": "No Gemini key is configured; add one in the Settings tab first.",
        "fa": "هیچ کلید Gemini تنظیم نشده؛ اول از تب «تنظیمات» کلید بگذار.",
    },
    "engine.err.srt_missing": {
        "en": "SRT file not found:\n{path}",
        "fa": "فایل SRT پیدا نشد:\n{path}",
    },
    "engine.err.srt_invalid": {
        "en": "This SRT file is not valid (no timestamp lines found).",
        "fa": "این فایل SRT معتبر نیست (هیچ خط زمانی پیدا نشد).",
    },
    "engine.err.empty_key": {
        "en": "The key is empty.",
        "fa": "کلید خالی است.",
    },

    # --- API key diagnostics --------------------------------------------------
    "engine.key.groq_ok": {
        "en": "✅ Groq key is valid.",
        "fa": "✅ کلید Groq سالم است.",
    },
    "engine.key.groq_http": {
        "en": "❌ Groq: HTTP {code} — {body}",
        "fa": "❌ Groq: HTTP {code} — {body}",
    },
    "engine.key.no_flash": {
        "en": " (no flash model available)",
        "fa": " (هیچ مدل flash در دسترس نیست)",
    },
    "engine.key.gemini_ok": {
        "en": "✅ Gemini key is valid{extra}.",
        "fa": "✅ کلید Gemini سالم است{extra}.",
    },
    "engine.key.gemini_http": {
        "en": "❌ Gemini: HTTP {code} — {body}",
        "fa": "❌ Gemini: HTTP {code} — {body}",
    },
    "engine.key.network_error": {
        "en": "❌ Network error: {error}",
        "fa": "❌ خطای شبکه: {error}",
    },
}
