"""Downloader + audio catalogs (yt-dlp downloads and ffmpeg helpers).

Covers the user-facing text of ``core/downloader.py`` and ``core/audio.py``:
progress labels, log lines handed to progress callbacks and every
``DownloadError`` / ``DownloadCancelled`` / ``AudioError`` message.

English is the default; the Persian values keep the original wording.
"""

CATALOG = {
    "audio.err.convert_failed": {
        "en": "ffmpeg could not convert the file to mp3.",
        "fa": "ffmpeg نتوانست فایل را به mp3 تبدیل کند.",
    },
    "audio.err.input_missing": {
        "en": "Input file not found: {path}",
        "fa": "فایل ورودی پیدا نشد: {path}",
    },
    "audio.err.mkdir_failed": {
        "en": "Creating the output folder failed: {path}\n{error}",
        "fa": "ساخت پوشه‌ی خروجی ناموفق بود: {path}\n{error}",
    },
    "audio.err.no_chunks": {
        "en": "No audio chunks were created.",
        "fa": "هیچ تکه‌ی صوتی ساخته نشد.",
    },
    "audio.err.no_duration": {
        "en": "The audio file's duration could not be read (is the file intact?).",
        "fa": "مدت فایل صوتی خوانده نشد (فایل سالم است؟).",
    },
    "audio.err.spawn_failed": {
        "en": "«{tool}» could not be started: {error}",
        "fa": "«{tool}» اجرا نشد: {error}",
    },
    "audio.err.split_failed": {
        "en": "Creating the audio chunk failed.",
        "fa": "ساخت تکه‌ی صوتی ناموفق بود.",
    },
    "audio.err.timeout": {
        "en": "Audio processing took too long (timeout).",
        "fa": "پردازش صدا بیش از حد طول کشید (timeout).",
    },
    "audio.err.tool_missing": {
        "en": "«{tool}» was not found; ffmpeg/ffprobe must be installed and on PATH. ({error})",
        "fa": "«{tool}» پیدا نشد؛ ffmpeg/ffprobe باید نصب و روی PATH باشد. ({error})",
    },
    "audio.log.compressing": {"en": "🎛️ Compressing audio", "fa": "🎛️ فشرده‌سازی صدا"},
    "audio.log.finding_silences": {"en": "🔎 Finding silences", "fa": "🔎 پیدا کردن سکوت‌ها"},
    "audio.log.preparing": {"en": "✂️ Preparing audio", "fa": "✂️ آماده‌سازی صدا"},
    "audio.log.split_done": {"en": "✂️ Splitting audio finished", "fa": "✂️ تکه‌بندی صدا تمام شد"},
    "audio.log.splitting": {
        "en": "✂️ Splitting audio ({current}/{total})",
        "fa": "✂️ تکه‌بندی صدا ({current}/{total})",
    },
    "dl.err.audio_not_found": {
        "en": "The downloaded audio file was not found.",
        "fa": "فایل صوتی دانلودشده پیدا نشد.",
    },
    "dl.err.cancelled": {"en": "Download cancelled.", "fa": "دانلود لغو شد."},
    "dl.err.file_not_found": {
        "en": "The downloaded file was not found.",
        "fa": "فایل دانلودشده پیدا نشد.",
    },
    "dl.err.hint_bot_check": {
        "en": "\n\n💡 YouTube has blocked this IP. Import a cookies.txt file from the Download tab or set a proxy.",
        "fa": "\n\n💡 یوتیوب این IP را بلاک کرده. یک فایل cookies.txt از تب دانلود معرفی کن یا پروکسی بگذار.",
    },
    "dl.err.hint_forbidden": {
        "en": "\n\n💡 Access to this video is restricted (403); cookies or a proxy are required.",
        "fa": "\n\n💡 دسترسی به این ویدیو محدود است (403)؛ کوکی یا پروکسی لازم است.",
    },
    "dl.err.hint_format_unavailable": {
        "en": "\n\n💡 This quality is not available for this video; pick another option.",
        "fa": "\n\n💡 این کیفیت برای این ویدیو موجود نیست؛ گزینه‌ی دیگری انتخاب کن.",
    },
    "dl.err.hint_js_runtime": {
        "en": "\n\n💡 yt-dlp needs a JS runtime (Node/Deno); install it or update yt-dlp.",
        "fa": "\n\n💡 yt-dlp به یک JS runtime (Node/Deno) نیاز دارد؛ نصبش کن یا نسخه‌ی yt-dlp را به‌روز کن.",
    },
    "dl.err.hint_unavailable": {
        "en": "\n\n💡 The video is private/deleted.",
        "fa": "\n\n💡 ویدیو خصوصی/حذف‌شده است.",
    },
    "dl.err.info_failed": {
        "en": "Reading video info failed.",
        "fa": "خواندن اطلاعات ویدیو ناموفق بود.",
    },
    "dl.err.info_timeout": {
        "en": "Reading video info took too long (timeout).",
        "fa": "خواندن اطلاعات ویدیو زمان‌بر شد (timeout).",
    },
    "dl.err.info_unreadable": {
        "en": "The video info response could not be read.",
        "fa": "پاسخ اطلاعات ویدیو قابل خواندن نبود.",
    },
    "dl.err.no_ready_subs": {
        "en": "This video has no ready subtitles.",
        "fa": "این ویدیو زیرنویس آماده ندارد.",
    },
    "dl.err.no_subs_in_lang": {
        "en": "This video has no subtitle in «{target}» (and no auto-translation is available).",
        "fa": "این ویدیو زیرنویس به زبان «{target}» ندارد (و ترجمهٔ خودکار هم موجود نیست).",
    },
    "dl.err.no_subtitles": {
        "en": "This video has no subtitles/captions.",
        "fa": "این ویدیو هیچ زیرنویس/کپشنی ندارد.",
    },
    "dl.err.no_ytdlp": {
        "en": "yt-dlp could not run; the yt-dlp package is not installed (pip install -r requirements.txt).",
        "fa": "yt-dlp اجرا نشد؛ بسته‌ی yt-dlp نصب نیست (pip install -r requirements.txt).",
    },
    "dl.err.rate_limited": {
        "en": "YouTube has temporarily rate-limited requests from this system (429). Try again in a few minutes.",
        "fa": "یوتیوب موقتاً درخواست‌های این سیستم را محدود کرده (429). چند دقیقه بعد دوباره امتحان کن.",
    },
    "dl.err.size_no_info": {
        "en": "This video's info could not be read (check the link or the connection).",
        "fa": "اطلاعات این ویدیو خوانده نشد (لینک یا اتصال را بررسی کن).",
    },
    "dl.log.audio_done": {"en": "✅ Audio download finished", "fa": "✅ دانلود صدا تمام شد"},
    "dl.log.info_txt_done": {"en": "✅ Info file written", "fa": "✅ فایل مشخصات نوشته شد"},
    "dl.log.probing": {"en": "🔎 Reading video info...", "fa": "🔎 خواندن اطلاعات ویدیو…"},
    "dl.log.probing_subs": {
        "en": "🔎 Reading info and subtitles...",
        "fa": "🔎 خواندن اطلاعات و زیرنویس‌ها…",
    },
    "dl.log.rate_limit_retry": {
        "en": "⏳ YouTube temporarily rate-limited us; waiting 45 seconds and trying again...",
        "fa": "⏳ یوتیوب محدودیت موقت داد؛ ۴۵ ثانیه صبر و تلاش دوباره…",
    },
    "dl.log.size_calculating": {
        "en": "⚖️ Size estimate: calculating qualities...",
        "fa": "⚖️ تخمین حجم: محاسبه‌ی کیفیت‌ها…",
    },
    "dl.log.size_done": {"en": "✅ Size estimate ready", "fa": "✅ تخمین حجم آماده شد"},
    "dl.log.size_reading": {
        "en": "⚖️ Size estimate: reading video info...",
        "fa": "⚖️ تخمین حجم: خواندن اطلاعات ویدیو…",
    },
    "dl.log.sub_done": {"en": "✅ Subtitle downloaded", "fa": "✅ زیرنویس دریافت شد"},
    "dl.log.sub_fetching": {
        "en": "⬇️ Fetching subtitle «{target}» ({kind})...",
        "fa": "⬇️ دریافت زیرنویس «{target}» ({kind})…",
    },
    "dl.log.sub_rate_limit_wait": {
        "en": "⏳ Temporary YouTube rate limit; waiting 45 seconds...",
        "fa": "⏳ محدودیت موقت یوتیوب؛ ۴۵ ثانیه صبر…",
    },
    "dl.log.video_done": {"en": "✅ Download finished", "fa": "✅ دانلود تمام شد"},
    "dl.sub.fallback_note": {
        "en": " (YouTube auto-translation was rate-limited; using the original)",
        "fa": " (ترجمهٔ خودکار یوتیوب محدود بود؛ نسخهٔ اصلی)",
    },
}
