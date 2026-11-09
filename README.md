# 🎛 Arion Studio

![Version](https://img.shields.io/badge/version-v0.1.0--alpha-blue)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)
![Python](https://img.shields.io/badge/python-3.10%2B-green)
![License: PolyForm Strict](https://img.shields.io/badge/license-PolyForm%20Strict-c0392b)

**فارسی | [English](#-arion-studio--english)** — [دانلود نسخه‌ی آلفا](https://github.com/ParsaPRF/arion-studio/releases)

نسخه‌ی دسکتاپِ موتورِ ربات [Arion](https://github.com/ParsaPRF/arion-bot) است؛ ساخته‌شده با رابط گرافیکی **[CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)**. همان موتور زیرنویس/ترجمه/دانلودِ ربات — این‌بار بدون تلگرام و روی کامپیوتر خودتان:

- 🎬 **ساخت زیرنویس (SRT / TXT)** از ویدیو، ویس یا لینک یوتیوب
  - موتورهای تشخیص: ⚡ Groq (Whisper) یا ✨ Gemini با حالت عمیق
  - زبان: تشخیص خودکار، فارسی، انگلیسی، آلمانی — سه استایل: جمله‌ای، خطوط کوتاه، کلمه‌به‌کلمه
  - نوار پیشرفت زنده، لاگ مراحل، امکان لغو کار؛ چند کلید = چرخش خودکار هنگام محدودیت
- 📺 **دانلود از یوتیوب**
  - ویدیو تا 4K · صدا (MP3 / M4A / Opus / FLAC) · زیرنویس آماده‌ی یوتیوب · خروجی TXT مشخصات
  - نمایش درصد/سرعت/ETA به‌صورت زنده + دکمه‌ی تخمین حجم هر کیفیت
  - پشتیبانی از فایل کوکی و پروکسی برای ویدیوهای محدودشده
- 🌍 **ترجمه‌ی SRT** با Gemini — ۹ زبان و سه سبک (خودمانی / رسمی / آموزشی)
- ⚙️ **تنظیمات** — کلیدهای API، پوشه‌ی خروجی، پروکسی، تم روشن/تیره

هر کار در یک ترد جدا اجرا می‌شود و پیشرفتش از طریق یک صف امن به رابط منتقل می‌شود؛ رابط هرگز هنگام کار منجمد نمی‌شود.

## ✨ رابط کاربری

- پنجره کاملاً **قابل تغییر اندازه** — کارت‌ها، نوارها و لاگ‌ها همراه پنجره کش می‌آیند
- اسلایدر **«اندازه‌ی عناصر»** — تمام فونت‌ها و دکمه‌ها از ۷۰٪ تا ۱۶۰٪ مقیاس می‌شوند
- تم: system / dark / light — آخرین اندازه و مقیاس پنجره و تنظیمات در `settings.json` ذخیره می‌شود

## 📥 نصب

### روش ۱ — نسخه‌ی آماده (پیشنهادی)

آرشیو مخصوص سیستم‌عامل خود را از [**Releases**](https://github.com/ParsaPRF/arion-studio/releases) بگیرید.

**🪟 ویندوز**

1. `arion-studio-0.1.0a1-windows.zip` را دانلود و استخراج کنید
2. **دابل‌کلیک روی `run.bat`** — خودش پایتون (اگر نبود با winget)، venv و وابستگی‌ها را نصب و برنامه را اجرا می‌کند
3. فقط یک بار `ffmpeg` را نصب کنید:
   ```bat
   winget install Gyan.FFmpeg
   ```

**🐧 لینوکس / مک**

```bash
tar xzf arion-studio-0.1.0a1-linux.tar.gz
cd arion-studio-0.1.0a1
./install.sh     # پیش‌نیازها (ffmpeg ،tkinter) + venv + وابستگی‌ها
arion-studio     # اجرا — یا فقط از این پوشه: ./run.sh
```

`install.sh` پایتونِ ۳.۱۰+ را پیدا می‌کند، در صورت نبود `ffmpeg` و `python3-tk` با مدیر بسته (apt / dnf / pacman / brew) نصبشان می‌کند و یک میان‌بر منو (`arion-studio`) هم می‌سازد.

### روش ۲ — اجرا از سورس

پیش‌نیاز: `Python 3.10+` و `ffmpeg` روی PATH.

```bash
git clone https://github.com/ParsaPRF/arion-studio.git
cd arion-studio
python -m venv venv
venv\Scripts\pip install -r requirements.txt      # ویندوز
# venv/bin/pip install -r requirements.txt        # لینوکس / مک
venv\Scripts\python main.py                       # ویندوز
# venv/bin/python main.py                         # لینوکس / مک
```

یا ساده‌تر: `run.bat` در ویندوز و `run.sh` در لینوکس.

## 🔑 کلیدهای API

از تب **⚙️ تنظیمات**:

| سرویس | کاربرد | دریافت کلید |
|---|---|---|
| Groq (Whisper) | تشخیص گفتار (رایگان) | [console.groq.com/keys](https://console.groq.com/keys) |
| Gemini (Google AI Studio) | ترجمه، حالت عمیق | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |

اگر تیک «ذخیره در استخر» را بزنید، کلیدها در `keys/*.txt` نگه داشته می‌شوند — می‌توانید چند کلید بگذارید تا هنگام محدودشدن یکی، به‌طور خودکار بعدی استفاده شود.

## 🛠 عیب‌یابی

| مشکل | راه‌حل |
|---|---|
| هشدار «ffmpeg پیدا نشد» | ویندوز: `winget install Gyan.FFmpeg` · لینوکس: `sudo apt install ffmpeg` |
| خطای حین نصب وابستگی‌ها (تماس با PyPI قطع می‌شود) | نصب‌کننده‌ها خودشان به میرور منطقه‌ای `[mirror-pypi.runflare.com](https://mirror-pypi.runflare.com/simple)` برمی‌گردند؛ در نصب دستی همین فلگ را اضافه کنید: `pip install -r requirements.txt -i https://mirror-pypi.runflare.com/simple` |
| خطای `No module named tkinter` در لینوکس | `sudo apt install python3-tk` (برای Fedora: `python3-tkinter`) |
| یوتیوب خطای ۴۰۳/محدودیت می‌دهد | فایل `cookies.txt` را از تب دانلود معرفی کنید یا پروکسی بگذارید |
| پنجره باز نمی‌شود در SSH / بدون دسکتاپ | برنامه GUI است و به نمایشگر نیاز دارد؛ روی سرور باید از VNC/X11 استفاده شود |

## 🧱 ساختار پروژه

```
arion-studio/
├── main.py              # رابط CustomTkinter (۴ تب + نوار کنار)
├── engine.py            # پل GUI → هسته: ترد، پیشرفت، لغو
├── core/                # موتور پورت‌شده از arion-bot
│   ├── transcribe.py      # خط لوله زیرنویس (Groq/Gemini + چرخش کلید)
│   ├── downloader.py      # دانلود ویدیو/صدا/زیرنویس/مشخصات
│   ├── translate.py       # ترجمه SRT با Gemini
│   ├── audio.py, srt_utils.py, keypool.py, gemini_worker.py
│   └── config.py          # برای دسکتاپ بازنویسی شده
├── install.sh / run.sh  # نصب و اجرای لینوکس/مک
├── run.bat              # نصب و اجرای ویندوز
├── requirements.txt
└── LICENSE
```

> `core/` یک‌به‌یک از [arion-bot](https://github.com/ParsaPRF/arion-bot) ارث رسیده؛ فقط `config.py` برای دسکتاپ تغییر کرده (بدون netns/VPN، مسیرهای ویندوزی). پوشه‌های `settings.json`، `keys/`، `output/`، `work/` و `cookies/` حاوی داده‌های شخصی‌اند و در `.gitignore` هستند.

## 📄 لایسنس

© ۲۰۲۶ امیر پارسا فتح‌الهی (ParsaPRF) — تمام حقوق محفوظ است.

این پروژه تحت **[PolyForm Strict License 1.0.0](LICENSE)** منتشر شده است: استفاده‌ی شخصی و غیرتجاری آزاد است، اما **کپی، توزیع، فورک، تغییر یا ساختن کار مشتق‌شده مجاز نیست**. استفاده‌ی تجاری نیازمند اجازه‌ی کتبی از نویسنده است.

---

<a id="-arion-studio--english"></a>
# 🎛 Arion Studio (English)

![Version](https://img.shields.io/badge/version-v0.1.0--alpha-blue)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)
![Python](https://img.shields.io/badge/python-3.10%2B-green)
![License: PolyForm Strict](https://img.shields.io/badge/license-PolyForm%20Strict-c0392b)

**[فارسی](#-arion-studio) | English** — [Download the alpha](https://github.com/ParsaPRF/arion-studio/releases)

The **desktop edition** of the engine behind the [Arion](https://github.com/ParsaPRF/arion-bot) Telegram bot, wrapped in a **[CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)** GUI. No Telegram — the same subtitle/download/translate engine, running locally on your PC:

- 🎬 **Subtitles (SRT / TXT)** from a local media file or a YouTube link
  - Engines: ⚡ Groq (Whisper) or ✨ Gemini with a deep-listen refinement mode
  - Languages: auto / Persian / English / German — three styles: sentence, short lines, word-by-word
  - Live progress bar + stage log + cancel; multiple keys rotate automatically on rate limits
- 📺 **YouTube downloads**
  - Video up to 4K · audio (MP3 / M4A / Opus / FLAC) · YouTube's own subtitles · metadata TXT
  - Live percent / speed / ETA + per-quality size estimates
  - cookies file and proxy support for restricted videos
- 🌍 **SRT translation** with Gemini — 9 languages, 3 styles (casual / formal / educational)
- ⚙️ **Settings** — API keys, output folder, proxy, light/dark theme

Each job runs in its own worker thread and its progress is marshalled onto the Tk main loop through a queue — the UI never freezes while working.

## ✨ The interface

- Fully **resizable window** — cards, bars and logs stretch with the window
- A **UI-scale slider** — every font and button scales from 70% to 160%
- Theme: system / dark / light — window geometry, scale and settings persist in `settings.json`

## 📥 Install

### Option 1 — prebuilt release (recommended)

Grab the archive for your OS from [**Releases**](https://github.com/ParsaPRF/arion-studio/releases).

**🪟 Windows**

1. Download and extract `arion-studio-0.1.0a1-windows.zip`
2. **Double-click `run.bat`** — it installs Python (via winget if missing), the venv and the dependencies, then launches the app
3. Install ffmpeg once:
   ```bat
   winget install Gyan.FFmpeg
   ```

**🐧 Linux / macOS**

```bash
tar xzf arion-studio-0.1.0a1-linux.tar.gz
cd arion-studio-0.1.0a1
./install.sh     # prerequisites (ffmpeg, tkinter) + venv + deps
arion-studio     # launch — or just: ./run.sh
```

`install.sh` finds a Python 3.10+ binary, installs `ffmpeg` and `python3-tk` via your package manager (apt / dnf / pacman / brew) when missing, and adds an `arion-studio` menu entry.

### Option 2 — run from source

Prerequisites: `Python 3.10+` and `ffmpeg` on PATH.

```bash
git clone https://github.com/ParsaPRF/arion-studio.git
cd arion-studio
python -m venv venv
venv/bin/pip install -r requirements.txt     # Linux / macOS
venv/bin/python main.py
```

Or simply run `run.bat` (Windows) / `run.sh` (Linux, macOS).

## 🔑 API keys

In the **⚙️ Settings** tab:

| Service | Used for | Get a key |
|---|---|---|
| Groq (Whisper) | speech recognition (free tier) | [console.groq.com/keys](https://console.groq.com/keys) |
| Gemini (Google AI Studio) | translation, deep-listen mode | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |

Tick "save to pool" to append keys to `keys/*.txt` — stack several keys and they rotate automatically when one hits a rate limit.

## 🛠 Troubleshooting

| Problem | Fix |
|---|---|
| "ffmpeg not found" warning | Windows: `winget install Gyan.FFmpeg` · Linux: `sudo apt install ffmpeg` |
| Dependency install fails (PyPI unreachable) | The installers fall back to a regional mirror (`mirror-pypi.runflare.com`) automatically; with manual pip add: `-i https://mirror-pypi.runflare.com/simple` |
| `No module named tkinter` on Linux | `sudo apt install python3-tk` (Fedora: `python3-tkinter`) |
| YouTube 403 / restricted video | Point the download tab to a `cookies.txt` file or set a proxy |
| Window won't open over SSH | The app is a GUI and needs a display — use VNC/X11 on servers |

## 🧱 Project layout

```
arion-studio/
├── main.py              # the CustomTkinter GUI (4 tabs + sidebar)
├── engine.py            # GUI → engine bridge: threads, progress, cancel
├── core/                # engine ported from arion-bot
│   ├── transcribe.py      # subtitle pipeline (Groq/Gemini + key rotation)
│   ├── downloader.py      # video/audio/subtitle/metadata downloads
│   ├── translate.py       # SRT translation with Gemini
│   ├── audio.py, srt_utils.py, keypool.py, gemini_worker.py
│   └── config.py          # rewritten for the desktop
├── install.sh / run.sh  # Linux/macOS installer + launcher
├── run.bat              # Windows installer + launcher
├── requirements.txt
└── LICENSE
```

> `core/` is taken one-to-one from [arion-bot](https://github.com/ParsaPRF/arion-bot); only `config.py` was re-tuned for the desktop (no netns/VPN, Windows-friendly paths). `settings.json`, `keys/`, `output/`, `work/` and `cookies/` hold personal data and are git-ignored.

## 📄 License

© 2026 Amir Parsa Fatholahi (ParsaPRF) — all rights reserved.

Released under the **[PolyForm Strict License 1.0.0](LICENSE)**: personal and non-commercial use is allowed, but **copying, redistribution, forking, modifying, or building derivative works is NOT permitted**. Commercial use requires the author's written permission.
