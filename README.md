<a id="english"></a>
# 🎛 Arion Studio

![Version](https://img.shields.io/badge/version-v0.2.0--alpha-blue)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)
![Python](https://img.shields.io/badge/python-3.10%2B-green)
![License: PolyForm Strict](https://img.shields.io/badge/license-PolyForm%20Strict-c0392b)

**[فارسی](#persian)** | English — [Download the alpha](https://github.com/ParsaPRF/arion-studio/releases)

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
- A **UI-scale slider** — every font and button scales from 75% to 150%
- Theme: system / dark / light — window geometry, scale and settings persist in `settings.json`
- 💬 Per-tab progress panel: **overall percent**, current stage, ⏱ elapsed, ⏳ ETA, 🚀 speed and the 🔑 key in use
- 📜 Timestamped log per tab with "copy log", "clear" and "save log" (into `logs/`)
- 🌍 **Interface language** — the app starts in **English** on a fresh install; switch to Persian from the sidebar. Your choice is remembered in `settings.json`

## ⌨️ Keyboard shortcuts

Shortcuts are resolved from the **physical key code**, not the character, so they keep working while the OS keyboard layout is Persian / Arabic / Cyrillic.

| Key | Action |
|---|---|
| `Ctrl+O` | pick a file (current tab) |
| `Ctrl+Enter` or `F5` | start the current job |
| `Esc` | cancel the running job |
| `Ctrl+1…4` | jump to tab 1–4 |
| `Ctrl+Tab` | next tab |
| `Ctrl+C` / `Ctrl+V` / `Ctrl+X` | copy / paste / cut in any text field |
| `Ctrl+A` · `Ctrl+Z` / `Ctrl+Y` | select all · undo / redo in text boxes |
| `Shift+Insert` / `Ctrl+Insert` | paste / copy (Windows) |
| `F1` | shortcut help |

**Right-click** any text field for a cut / copy / paste / select-all menu. The UI font is chosen from families with real Persian glyphs (Vazirmatn → Vazir → IRANSans → Segoe UI → Tahoma → …), so Persian text never turns into boxes. In English mode a Latin-first family is preferred (Segoe UI → Inter → Noto Sans → …); in Persian mode the Persian-capable chain above is used.

## 📂 Where do output files go?

| Output | Location |
|---|---|
| Finished subtitle / translation | exactly the **output folder** chosen in that tab (default `output/`) |
| Intermediates (compressed audio, chunks, per-chunk SRT) | `work/` — safe to delete afterwards |
| Downloads (video/audio/subtitle/TXT) | the "save" folder of the download tab |
| Job log | "save log" writes into `logs/` |

## 📥 Install

### Option 1 — prebuilt release (recommended)

Grab the archive for your OS from [**Releases**](https://github.com/ParsaPRF/arion-studio/releases).

**🪟 Windows**

1. Download and extract `arion-studio-0.2.0a1-windows.zip`
2. **Double-click `run.bat`** — it installs Python (via winget if missing), the venv and the dependencies, then launches the app
3. Install ffmpeg once:
   ```bat
   winget install Gyan.FFmpeg
   ```

**🐧 Linux / macOS**

```bash
tar xzf arion-studio-0.2.0a1-linux.tar.gz
cd arion-studio-0.2.0a1
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
| Progress bar frozen, or wrong percent/speed | Fixed here (yt-dlp's progress template is no longer suppressed by `--print`, and ANSI colour codes no longer break parsing). If it returns, update yt-dlp: `pip install -U yt-dlp` |
| Typing or `Ctrl+V` dies after switching keyboard language | Fixed: shortcuts use physical key codes and every field has a right-click menu. If Persian text shows as boxes, install `Vazirmatn` or use `Segoe UI` |
| Can't find the produced subtitle | It is in the output folder of that tab (the 📂 button opens it); intermediates stay in `work/` |
| Translation / deep mode does nothing | Both need a **Gemini** key (not Groq) — add it in Settings and press "test" |
| No YouTube subtitle found | Some videos have none; use the Transcribe tab with the Whisper engine instead |

## 🧱 Project layout

```
arion-studio/
├── main.py              # the CustomTkinter GUI (4 tabs + sidebar)
├── engine.py            # GUI → engine bridge: threads, progress, cancel
├── i18n/                # en/fa catalogs + t() lookup
├── core/                # engine ported from arion-bot
│   ├── transcribe.py      # subtitle pipeline (Groq/Gemini + key rotation)
│   ├── downloader.py      # video/audio/subtitle/metadata downloads
│   ├── translate.py       # SRT translation with Gemini
│   ├── audio.py, srt_utils.py, keypool.py, gemini_worker.py
│   └── config.py          # rewritten for the desktop
├── tests/               # regression tests (unittest — no network needed)
├── install.sh / run.sh  # Linux/macOS installer + launcher
├── run.bat              # Windows installer + launcher
├── requirements.txt
└── LICENSE
```

### 🧪 Tests

```bash
python -m unittest discover -s tests -v      # 81 tests: progress parsing, SRT, pipeline, shortcuts, GUI wiring
```

They run offline (no API keys, no network). The audio part needs `ffmpeg`, and the GUI-wiring tests run only when `customtkinter` is installed (otherwise they are skipped). Manual, network-touching checks live in `tests/_smoke_*.py`.

> `core/` is taken one-to-one from [arion-bot](https://github.com/ParsaPRF/arion-bot); only `config.py` was re-tuned for the desktop (no netns/VPN, Windows-friendly paths). `settings.json`, `keys/`, `output/`, `work/` and `cookies/` hold personal data and are git-ignored.

## 📄 License

© 2026 Amir Parsa Fatholahi (ParsaPRF) — all rights reserved.

Released under the **[PolyForm Strict License 1.0.0](LICENSE)**: personal and non-commercial use is allowed, but **copying, redistribution, forking, modifying, or building derivative works is NOT permitted**. Commercial use requires the author's written permission.

---

<a id="persian"></a>
# 🎛 Arion Studio (فارسی)

![Version](https://img.shields.io/badge/version-v0.2.0--alpha-blue)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)
![Python](https://img.shields.io/badge/python-3.10%2B-green)
![License: PolyForm Strict](https://img.shields.io/badge/license-PolyForm%20Strict-c0392b)

**English | [فارسی](#persian)** — [Download the alpha](https://github.com/ParsaPRF/arion-studio/releases)

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

- پنجره کاملاً **قابل تغییر اندازه** — کارتها، نوارها و لاگها همراه پنجره کش می‌آیند
- اسلایدر **«اندازه‌ی عناصر»** — تمام فونت‌ها و دکمه‌ها از ۷۵٪ تا ۱۵۰٪ مقیاس می‌شوند
- تم: system / dark / light — آخرین اندازه و مقیاس پنجره و تنظیمات در `settings.json` ذخیره می‌شود
- 💬 نوار پیشرفت هر تب: **درصد کل**، مرحله‌ی جاری، ⏱ زمان سپری‌شده، ⏳ تخمین باقی‌مانده، 🚀 سرعت و 🔑 کلید در حال استفاده
- 📜 لاگ زمان‌دار داخل هر تب با دکمه‌های «کپی لاگ»، «پاک کردن» و «ذخیره‌ی لاگ» (در `logs/`)
- 🌍 **زبان رابط** — در نصب تازه برنامه با **انگلیسی** باز می‌شود؛ از نوار کنار می‌توانید به فارسی برگردانید. انتخابتان در `settings.json` می‌ماند

## ⌨️ میان‌برهای کیبورد

میان‌برها از **کد فیزیکی کلید** خوانده می‌شوند، نه از حرف؛ پس وقتی صفحه‌کلید روی فارسی/عربی/سیریلیک است هم کار می‌کنند.

| کلید | کار |
|---|---|
| `Ctrl+O` | انتخاب فایل (در تب جاری) |
| `Ctrl+Enter` یا `F5` | شروع کار جاری |
| `Esc` | لغو کار در حال اجرا |
| `Ctrl+1…4` | رفتن به تب ۱ تا ۴ |
| `Ctrl+Tab` | تب بعدی |
| `Ctrl+C` / `Ctrl+V` / `Ctrl+X` | کپی / چسباندن / برش در هر فیلد متنی |
| `Ctrl+A` · `Ctrl+Z` / `Ctrl+Y` | انتخاب همه · برگشت / تکرار در جعبه‌های متن |
| `Shift+Insert` / `Ctrl+Insert` | چسباندن / کپی (ویندوز) |
| `F1` | راهنمای میان‌برها |

روی هر فیلد متنی **راست‌کلیک** کنید تا منوی «برش / کپی / چسباندن / انتخاب همه» باز شود. فونت رابط از خانواده‌هایی انتخاب می‌شود که حروف فارسی دارند (Vazirmatn → Vazir → IRANSans → Segoe UI → Tahoma → …) تا متن فارسی هرگز مربع‌نشود. در حالت انگلیسی فونت‌های لاتین (Segoe UI → Inter → Noto Sans → …) ترجیح داده می‌شوند و در حالت فارسی همان زنجیرهٔ فارسی‌محور بالا.

## 📂 فایل‌های خروجی کجا می‌روند؟

| خروجی | مسیر |
|---|---|
| زیرنویس / ترجمه‌ی نهایی | دقیقاً در **پوشه‌ی خروجی** که در همان تب انتخاب می‌کنید (پیش‌فرض `output/`) |
| فایل‌های میانی (صدای فشرده، تکه‌ها، SRT هر بخش) | `work/` — بعد از پایان کار قابل پاک کردن |
| دانلودها (ویدیو/صدا/زیرنویس/TXT) | همان پوشه‌ی «ذخیره» تب دانلود |
| لاگ کار | با دکمه‌ی «ذخیره‌ی لاگ» در `logs/` |

## 📥 نصب

### روش ۱ — نسخه‌ی آماده (پیشنهادی)

آرشیو مخصوص سیستم‌عامل خود را از [**Releases**](https://github.com/ParsaPRF/arion-studio/releases) بگیرید.

**🪟 ویندوز**

1. `arion-studio-0.2.0a1-windows.zip` را دانلود و استخراج کنید
2. **دابل‌کلیک روی `run.bat`** — خودش پایتون (اگر نبود با winget)، venv و وابستگی‌ها را نصب و برنامه را اجرا می‌کند
3. فقط یک بار `ffmpeg` را نصب کنید:
   ```bat
   winget install Gyan.FFmpeg
   ```

**🐧 لینوکس / مک**

```bash
tar xzf arion-studio-0.2.0a1-linux.tar.gz
cd arion-studio-0.2.0a1
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
| نوار پیشرفت تکان نمی‌خورد یا درصد/سرعت اشتباه است | در این نسخه رفع شده (قالب پیشرفت yt-dlp دیگر با `--print` خفه نمی‌شود و کدهای رنگی ANSI هم پارس می‌شوند). اگر باز هم دیدید، yt-dlp را به‌روز کنید: `pip install -U yt-dlp` |
| بعد از عوض کردن زبانِ ویندوز، تایپ یا `Ctrl+V` در فیلدها کار نمی‌کند | رفع شده: میان‌برها با کد فیزیکی کلید کار می‌کنند و هر فیلد منوی راست‌کلیک دارد. اگر متن فارسی مربع نشان داده می‌شود، فونت `Vazirmatn` یا `Segoe UI` را نصب کنید |
| فایل خروجی زیرنویس را پیدا نمی‌کنم | نتیجه در پوشه‌ی خروجیِ همان تب است (دکمه‌ی 📂 کنارِ مسیر آن را باز می‌کند)؛ فایل‌های میانی در `work/` می‌مانند |
| ترجمه/حالت عمیق کار نمی‌کند | این دو به کلید **Gemini** نیاز دارند (نه Groq) — از تب تنظیمات کلید بگذارید و دکمه‌ی «تست» را بزنید |
| زیرنویس خودکار یوتیوب پیدا نمی‌شود | بعضی ویدیوها هیچ زیرنویسی ندارند؛ در این حالت از تب «ساخت زیرنویس» با موتور Whisper استفاده کنید |

## 🧱 ساختار پروژه

```
arion-studio/
├── main.py              # رابط CustomTkinter (۴ تب + نوار کنار)
├── engine.py            # پل GUI → هسته: ترد، پیشرفت، لغو
├── i18n/                # کاتالوگ انگلیسی/فارسی + تابع t()
├── core/                # موتور پورت‌شده از arion-bot
│   ├── transcribe.py      # خط لوله زیرنویس (Groq/Gemini + چرخش کلید)
│   ├── downloader.py      # دانلود ویدیو/صدا/زیرنویس/مشخصات
│   ├── translate.py       # ترجمه SRT با Gemini
│   ├── audio.py, srt_utils.py, keypool.py, gemini_worker.py
│   └── config.py          # برای دسکتاپ بازنویسی شده
├── tests/               # تست‌های رگرسیون (unittest — بدون نیاز به شبکه)
├── install.sh / run.sh  # نصب و اجرای لینوکس/مک
├── run.bat              # نصب و اجرای ویندوز
├── requirements.txt
└── LICENSE
```

### 🧪 تست‌ها

```bash
python -m unittest discover -s tests -v      # ۸۱ تست: پارس پیشرفت، SRT، خط لوله، میان‌برها، سیم‌کشی GUI
```

تست‌ها آفلاین اجرا می‌شوند (به کلید API و شبکه نیاز ندارند). بخش صوتی به `ffmpeg` نیاز دارد و تست‌های «سیم‌کشی GUI» فقط وقتی `customtkinter` نصب باشد اجرا می‌شوند (وگرنه skip). اسکریپت‌های بررسی دستی با شبکه در `tests/_smoke_*.py` هستند.

> `core/` یک‌به‌یک از [arion-bot](https://github.com/ParsaPRF/arion-bot) ارث رسیده؛ فقط `config.py` برای دسکتاپ تغییر کرده (بدون netns/VPN، مسیرهای ویندوزی). پوشه‌های `settings.json`، `keys/`، `output/`، `work/` و `cookies/` حاوی داده‌های شخصی‌اند و در `.gitignore` هستند.

## 📄 لایسنس

© ۲۰۲۶ امیر پارسا فتح‌الهی (ParsaPRF) — تمام حقوق محفوظ است.

این پروژه تحت **[PolyForm Strict License 1.0.0](LICENSE)** منتشر شده است: استفاده‌ی شخصی و غیرتجاری آزاد است، اما **کپی، توزیع، فورک، تغییر یا ساختن کار مشتق‌شده مجاز نیست**. استفاده‌ی تجاری نیازمند اجازه‌ی کتبی از نویسنده است.

