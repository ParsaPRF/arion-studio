# 🎛 Arion Studio — desktop GUI of the Arion engine

**فارسی | [English](#-arion-studio--english)**

نسخه‌ی دسکتاپِ (بدون تلگرام) موتور ربات [Arion](https://github.com/ParsaPRF/arion-bot) است؛ با رابط گرافیکی **CustomTkinter**. همون موتور زیرنویس/ترجمه/دانلود ربات، این‌بار روی پی‌سی خودتان:

- 🎬 **ساخت زیرنویس (SRT/TXT)** از فایل ویدیو/صدا یا لینک یوتیوب — زبان (فارسی/انگلیسی/آلمانی/خودکار)، سه استایل (جمله‌ای / خطوط کوتاه / کلمه‌به‌کلمه)، گزارش پیشرفت زنده، retry چرخشی کلیدها، حالت عمیق با Gemini
- 📺 **دانلود یوتیوب** — ویدیو (تا 4K)، صدا (MP3/M4A/Opus/FLAC)، زیرنویس آماده (SRT)، خروجی TXT از مشخصات و توضیحات ویدیو؛ نمایش درصد/سرعت/ETA؛ تخمین حجم هر کیفیت
- 🌍 **ترجمه‌ی SRT** با Gemini (۹ زبان، سه سبک)
- ⚙️ **تنظیمات** — کلیدها (yyyy متذکر: ذخیره‌ی اختیاری)، پوشه خروجی، پروکسی

جریان هر کار در ترد جداگانه اجرا می‌شود و HUD پیشرفت (نوار + لاگ) از طریق صف به رابط منتقل می‌شود؛ لغو کار هم پشتیبانی می‌شود.

## ویژگی رابط

- پنجره کاملاً **قابل تغییر اندازه** (کارت‌ها و لاگ‌ها کش می‌آیند، حداقل سایز معقول)
- اسلایدر **«اندازه‌ی عناصر»** — کل رابط از ۷۰٪ تا ۱۶۰٪ مقیاس می‌شود (CTk widget/window scaling)
- سوییچ تم (system / dark / light) و ذخیره‌ی آخرین اندازه/مقیاس در `settings.json`

## راه‌اندازی سریع (ویندوز)

1. پیش‌نیاز: Python 3.10+ و `ffmpeg` روی PATH (`winget install Gyan.FFmpeg`)
2. دابل‌کلیک روی `run.bat`  — دستی:

```bat
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python main.py
```

## کلید API

از تب **⚙️ تنظیمات**:
- Groq (رایگان): [`console.groq.com/keys`](https://console.groq.com/keys)
- Gemini: [`aistudio.google.com/apikey`](https://aistudio.google.com/apikey)

اگر گزینه‌ی «ذخیره در استخر» را بزنید، کلیدها در `keys/*.txt` نگه داشته می‌شوند (همین فرمتِ ربات) و می‌توانید چند کلید بگذارید تا کلیک‌شدن یکی به بعدی جابجا شود.

## ساختار پروژه

```
ArionStudio/
├── main.py            # رابط CustomTkinter
├── engine.py          # پل GUI → هسته (ترد، پیشرفت، لغو)
├── core/              # موتور مستعار از arion-bot
│   ├── transcribe.py, audio.py, srt_utils.py
│   ├── downloader.py, translate.py, gemini_worker.py
│   ├── keypool.py, config.py   (# config برای ویندوز محلی بازنویسی شده)
├── requirements.txt
└── run.bat
```

نکته: هسته یک‌به‌یک از ربات ارث رسیده؛ فقط `config.py` برای دسکتاپ (بدون netns/VPN و با مسیرهای ویندوزی) بازنویسی شده است. فایل‌های `settings.json`، `keys/`، `output/` و `work/` به گیت ignore شده‌اند چون ممکن است حاوی کلید یا رسانه‌ی شخصی باشند.

---

<a id="-arion-studio--english"></a>
# 🎛 Arion Studio — English

The **desktop (Telegram-less) edition** of the engine behind the [Arion](https://github.com/ParsaPRF/arion-bot) bot, wrapped into a **CustomTkinter** GUI:

- 🎬 **Subtitles (SRT/TXT)** from a local media file or a YouTube link — language (fa/en/de/auto), three styles (sentence / short lines / word-by-word), live progress, key rotation with retries, Gemini "deep-listen" refinement mode
- 📺 **YouTube downloads** — video (up to 4K), audio (MP3/M4A/Opus/FLAC), the site's own subtitles, and a TXT with metadata + description; live percent/speed/ETA; per-quality size estimates
- 🌍 **SRT translation** with Gemini (9 languages, 3 styles)
- ⚙️ **Settings** — API keys (masked), output folder, optional proxy

Every job runs in a worker thread; progress + log are marshalled onto the Tk main loop through a queue. Cancellations are cooperative.

## UI niceties

- Fully **resizable window** (cards and logs stretch, sane minimum size)
- A **UI-scale slider** — the whole interface scales from 70% to 160% (CTk widget/window scaling)
- Theme switch (system/dark/light); last window size and scale persist in `settings.json`

## Quick start (Windows)

Prerequisites: Python 3.10+ and `ffmpeg` on PATH (`winget install Gyan.FFmpeg`). Double-click `run.bat`, or:

```bat
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python main.py
```

## API keys

In the **⚙️ Settings** tab: a free Groq key (`console.groq.com/keys`) and a Gemini key (Google AI Studio). "Save to pool" appends the key to `keys/*.txt` — the same file format the bot uses, so you can stack several keys and rotate on rate limits.

## Where things came from

The `core/` modules are taken one-to-one from the arion-bot repository; only `config.py` was re-tuned for a desktop (no netns/VPN, Windows-friendly paths). `settings.json`, `keys/`, `output/` and `work/` are git-ignored since they may hold keys or personal media.
