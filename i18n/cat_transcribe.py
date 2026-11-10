"""Transcription, translation and SRT utility strings (core.transcribe,
core.translate, core.srt_utils)."""

CATALOG = {
    # ----- core/transcribe.py: API keys and provider errors -------------------
    "tr.progress.deep_refine_model": {"en": "🔎 Deep review with {model}", "fa": "🔎 بازبینی عمیق با {model}"},
    "tr.progress.key": {
        "en": "Key {index}/{total}",
        "fa": "کلید {index}/{total}",
    },
    "tr.err.network": {
        "en": "Network error: {error}",
        "fa": "خطای شبکه: {error}",
    },
    "tr.err.chunk_too_large": {
        "en": "The audio chunk is too large for the server.",
        "fa": "حجم تکه برای سرور بیش از حد بزرگ است.",
    },
    "tr.retry.seconds": {
        "en": "{seconds} seconds",
        "fa": "{seconds} ثانیه",
    },
    "tr.err.rate_limited": {
        "en": "API rate limit: {detail}",
        "fa": "محدودیت API: {detail}",
    },
    "tr.err.all_failed": {
        "en": "All keys/attempts failed: {detail}",
        "fa": "همه‌ی کلیدها/تلاش‌ها ناموفق بودند: {detail}",
    },
    "tr.err.empty_response": {
        "en": "The transcription response was empty (no segments and no text).",
        "fa": "پاسخ ترنسکرایب خالی بود (نه سگمنت و نه متن).",
    },
    "tr.err.run": {
        "en": "Run error: {error}",
        "fa": "خطای اجرا: {error}",
    },
    "tr.err.empty_gemini": {
        "en": "Empty response from Gemini",
        "fa": "پاسخ خالی از Gemini",
    },
    "tr.err.ip_blocked": {
        "en": "IP blocked by Google (VPN required)",
        "fa": "IP توسط گوگل بلاک شده است (VPN لازم است)",
    },
    "tr.err.gemini_rate_limited": {
        "en": "Gemini API rate limit: {detail}",
        "fa": "محدودیت API Gemini: {detail}",
    },
    "tr.err.gemini_failed": {
        "en": "Gemini failed: {detail}",
        "fa": "Gemini ناموفق بود: {detail}",
    },

    # ----- core/transcribe.py: progress labels -------------------------------
    "tr.progress.audio_processing": {
        "en": "🎛️ Processing audio...",
        "fa": "🎛️ پردازش صدا...",
    },
    "tr.progress.compressing": {
        "en": "🎛️ Compressing audio...",
        "fa": "🎛️ فشرده‌سازی صدا...",
    },
    "tr.progress.compressing_done": {
        "en": "🎛️ Compressing audio ✦",
        "fa": "🎛️ فشرده‌سازی صدا ✦",
    },
    "tr.progress.splitting": {
        "en": "✂️ Splitting audio...",
        "fa": "✂️ تکه‌بندی صدا...",
    },
    "tr.progress.splitting_done": {
        "en": "✂️ Splitting audio ✦ ({count} chunks of {minutes} min each)",
        "fa": "✂️ تکه‌بندی صدا ✦ ({count} بخش {minutes} دقیقه‌ای)",
    },
    "tr.progress.transcribe_chunk": {
        "en": "🎙️ Transcribing chunk {index}/{total} ({engine})\n📄 {icons}",
        "fa": "🎙️ ترنسکرایب بخش {index}/{total} ({engine})\n📄 {icons}",
    },
    "tr.progress.chunk": {
        "en": "✅ Chunk {index}/{total} transcribed",
        "fa": "✅ بخش {index}/{total} ترنسکرایب شد",
    },
    "tr.progress.audio_review": {
        "en": "🔬 Reviewing audio for chunk {index}/{total}...",
        "fa": "🔬 بازبینی شنیداری تکه {index}/{total}...",
    },
    "tr.progress.audio_review_done": {
        "en": "🔬 Audio review ✦ ({done}/{total} chunks)",
        "fa": "🔬 بازبینی شنیداری ✦ ({done}/{total} تکه)",
    },
    "tr.progress.merging": {
        "en": "🔗 Merging chunks...",
        "fa": "🔗 ادغام تکه‌ها...",
    },
    "tr.progress.merging_done": {
        "en": "🔗 Merging chunks ✦",
        "fa": "🔗 ادغام تکه‌ها ✦",
    },
    "tr.progress.deep_refine": {
        "en": "🔬 Deep refine pass (Gemini)...",
        "fa": "🔬 پاس اصلاح عمیق (Gemini)...",
    },
    "tr.progress.deep_refine_done": {
        "en": "🔬 Deep refine pass ✦",
        "fa": "🔬 پاس اصلاح عمیق ✦",
    },
    "tr.progress.output_written": {
        "en": "✅ Output file written",
        "fa": "✅ فایل خروجی نوشته شد",
    },

    # ----- core/transcribe.py: pipeline stage names (shown in errors) --------
    "tr.stage.compress": {
        "en": "Audio compression (ffmpeg)",
        "fa": "فشرده‌سازی صدا (ffmpeg)",
    },
    "tr.stage.split": {
        "en": "Audio splitting (ffmpeg)",
        "fa": "تکه‌بندی صدا (ffmpeg)",
    },
    "tr.err.no_chunks": {
        "en": "No chunks were created.",
        "fa": "هیچ تکه‌ای ساخته نشد.",
    },
    "tr.stage.transcribe_chunk": {
        "en": "Transcribing chunk {index}/{total}",
        "fa": "ترنسکرایب تکه {index}/{total}",
    },
    "tr.stage.merge": {
        "en": "Merging chunks",
        "fa": "ادغام تکه‌ها",
    },
    "tr.stage.write_output": {
        "en": "Writing output file",
        "fa": "نوشتن فایل خروجی",
    },

    # ----- core/translate.py -------------------------------------------------
    "translate.err.worker_start": {
        "en": "Failed to start gemini_worker: {error}",
        "fa": "اجرای gemini_worker ناموفق: {error}",
    },
    "translate.err.empty_model": {
        "en": "Empty response from the model",
        "fa": "پاسخ خالی از مدل",
    },
    "translate.err.ip_blocked": {
        "en": "IP blocked by Google (VPN required)",
        "fa": "IP توسط گوگل بلاک شده (VPN لازم است)",
    },
    "translate.err.bad_srt": {
        "en": "Invalid SRT / no lines found.",
        "fa": "SRT معتبر نبود / خطی پیدا نشد.",
    },
    "translate.err.no_keys": {
        "en": "No Gemini key is configured for translation.",
        "fa": "هیچ کلید Gemini برای ترجمه تنظیم نشده است.",
    },
    "translate.progress.pass": {
        "en": "🌍 Translating to {language} — pass {attempt} · {done}/{lines} lines",
        "fa": "🌍 ترجمه به {language} — پاس {attempt} · {done}/{lines} خط",
    },
    "translate.progress.chunk": {
        "en": "🌍 Translating chunk {index}/{chunks} (pass {attempt}) — {done}/{lines} lines",
        "fa": "🌍 ترجمه بخش {index}/{chunks} (پاس {attempt}) — {done}/{lines} خط",
    },
    "translate.progress.retry": {
        "en": "🔁 {pending} lines were not translated; retrying ({attempt}/3)...",
        "fa": "🔁 {pending} خط ترجمه نشد؛ تلاش دوباره ({attempt}/3)...",
    },
    "translate.progress.done": {
        "en": "✅ Translation complete ({done}/{total} lines)",
        "fa": "✅ ترجمه کامل شد ({done}/{total} خط)",
    },
    "translate.progress.missing": {
        "en": "⚠️ {missing} lines were not translated and stayed in the source "
              "language ({done}/{total} lines translated)",
        "fa": "⚠️ {missing} خط ترجمه نشد و به زبان اصلی ماند "
              "({done}/{total} خط ترجمه شد)",
    },

    # ----- core/srt_utils.py -------------------------------------------------
    "srt.err.bad_time": {
        "en": "bad timestamp: {value}",
        "fa": "برچسب زمانی نامعتبر: {value}",
    },
}
