"""Arion Studio — desktop GUI for the Arion subtitle/transcription engine.

Built on top of the arion-bot core modules with CustomTkinter
(https://github.com/TomSchimansky/CustomTkinter).

Layout is fully responsive: the window can be resized freely, cards stretch
with it (grid weights), log boxes grow/shrink, and a UI-scale slider in the
sidebar resizes every widget live (CTk widget scaling). The last window size
and scale are remembered in settings.json.

All work runs in worker threads; every widget update is marshalled onto the Tk
main loop through a queue, so the GUI never touches widgets from a side thread.

Run:  python main.py
"""

import json
import os
import queue
import threading
import tkinter as tk
import tkinter.filedialog as fd
import tkinter.messagebox as mb
import webbrowser

import customtkinter as ctk

import engine

APP_NAME = "Arion Studio"
VERSION = "0.1.0a1"
HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(HERE, "settings.json")

ACCENT = "#7C5CFF"
ACCENT_HOVER = "#6547e0"

DEFAULTS = {
    "groq_key": "",
    "gemini_key": "",
    "save_keys": False,
    "out_dir": os.path.join(HERE, "output"),
    "cookies": "",
    "proxy": "",
    "theme": "system",
    "scale": 1.0,
    "geometry": "1180x760",
    "transcribe_source": "file",
}


def load_settings():
    data = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data.update(json.load(f))
    except Exception:
        pass
    return data


def save_settings(data):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


ctk.set_appearance_mode(load_settings().get("theme", "system"))
ctk.set_default_color_theme("dark-blue")


class ProgressPump:
    """Worker threads push (kind, ...) tuples; the Tk loop repaints."""

    def __init__(self, tab):
        self.tab = tab
        self.q = queue.Queue()
        self.tab.after(120, self._pump)

    def push(self, *item):
        try:
            self.q.put_nowait(item)
        except Exception:
            pass

    def _pump(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "status":
                    self.tab.status_lbl.configure(text=item[1])
                elif kind == "overall":
                    self.tab.overall_bar.set(max(0.0, min(1.0, float(item[1]) / 100.0)))
                elif kind == "note":
                    self.tab.stage_lbl.configure(text=item[1])
                elif kind == "log":
                    box = self.tab.log_box
                    box.configure(state="normal")
                    box.insert("end", str(item[1]) + "\n")
                    box.see("end")
                    box.configure(state="disabled")
        except queue.Empty:
            pass
        self.tab.after(120, self._pump)


class Tab(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.pump = ProgressPump(self)
        self._job = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

    # ---- shared progress block (bars + status + log) -------------------------
    def _progress_block(self):
        card = ctk.CTkFrame(self, corner_radius=12)
        card.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        card.columnconfigure(0, weight=1)

        self.status_lbl = ctk.CTkLabel(card, text="آماده‌ام؛ کار بده 🙃", anchor="w")
        self.status_lbl.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))

        self.overall_bar = ctk.CTkProgressBar(card, progress_color=ACCENT, height=16)
        self.overall_bar.grid(row=1, column=0, sticky="ew", padx=14, pady=2)
        self.overall_bar.set(0)

        self.len_dur_row = ctk.CTkFrame(card, fg_color="transparent")
        self.len_dur_row.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 6))
        self.stage_lbl = ctk.CTkLabel(self.len_dur_row, text="", anchor="w",
                                      text_color="gray60")
        self.stage_lbl.pack(side="left")

        self.log_box = ctk.CTkTextbox(card, activate_scrollbars=True)
        self.log_box.grid(row=3, column=0, sticky="nsew", padx=14, pady=(2, 12))
        self.log_box.configure(state="disabled")
        card.rowconfigure(3, weight=1)

    # ---- thread-safe logging -------------------------------------------------
    def log(self, line):
        """UI-thread logging."""
        box = self.log_box
        box.configure(state="normal")
        box.insert("end", str(line) + "\n")
        box.see("end")
        box.configure(state="disabled")

    def logf(self, line):
        """Worker-thread logging (marshalled through the pump)."""
        self.pump.push("log", line)

    # ---- job plumbing ----------------------------------------------------------
    def make_job(self):
        self._job = engine.Job(progress_cb=self._progress_cb())
        self._job.running = True
        return self._job

    def _progress_cb(self):
        push = self.pump.push

        def cb(stage_pct, label, overall=None, note=""):
            ov = overall if overall is not None else stage_pct
            push("status", label or "")
            if note:
                push("note", f"🔑 {note}")
            push("overall", ov)

        return cb

    def start_worker(self, fn, on_done):
        def run():
            try:
                result = fn()
                self.app.after(0, lambda: on_done(result, None))
            except engine.Cancelled:
                self.app.after(0, self._on_cancelled)
            except Exception as e:
                self.app.after(0, lambda: on_done(None, e))

        threading.Thread(target=run, daemon=True).start()

    def _on_cancelled(self):
        self.set_running(False)
        self.log("⛔ لغو شد.")
        self.pump.push("status", "لغو شد.")

    def set_running(self, running):
        self.start_btn.configure(state="disabled" if running else "normal")
        self.cancel_btn.configure(state="normal" if running else "disabled")
        if not running and self._job:
            self._job.running = False
        if running:
            self.start_btn.configure(text="⏳ در حال اجرا…")
        else:
            self.start_btn.configure(text=self._start_text)

    def stage_note(self, note):
        self.stage_lbl.configure(text=note)


# =============================== Transcribe =================================

class TranscribeTab(Tab):
    _START = "🚀 شروع ساخت زیرنویس"

    def __init__(self, master, app):
        super().__init__(master, app)
        self._build_control_card()
        self._progress_block()
        self._start_text = self._START

    def _build_control_card(self):
        card = ctk.CTkFrame(self, corner_radius=12)
        card.grid(row=0, column=0, sticky="new", padx=2, pady=(0, 8))
        card.columnconfigure(0, weight=1)

        ctk.CTkLabel(card, text="🎬 ساخت زیرنویس (SRT/TXT) از ویدیو، ویس یا لینک یوتیوب",
                     font=("", 15, "bold"), anchor="w").grid(
            row=0, column=0, columnspan=3, sticky="ew", padx=12, pady=(10, 6))

        # source type switch
        seg = ctk.CTkSegmentedButton(card, values=["📁 فایل محلی", "📺 لینک یوتیوب"],
                                     command=self._switch_source)
        seg.set("📁 فایل محلی" if self.app.settings["transcribe_source"] == "file"
                else "📺 لینک یوتیوب")
        seg.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 8))

        # file row
        self.file_row = ctk.CTkFrame(card, fg_color="transparent")
        self.file_row.columnconfigure(0, weight=1)
        self.path_var = ctk.StringVar()
        ctk.CTkEntry(self.file_row, textvariable=self.path_var,
                     placeholder_text="مسیر فایل ویدیو/صدا (mp4, mkv, mp3, wav, m4a, …)"
                     ).grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(self.file_row, text="انتخاب فایل…", width=110,
                      command=self._pick_file).grid(row=0, column=1, padx=(8, 0))

        # url row
        self.url_row = ctk.CTkFrame(card, fg_color="transparent")
        self.url_row.columnconfigure(0, weight=1)
        self.url_var = ctk.StringVar()
        ctk.CTkEntry(self.url_row, textvariable=self.url_var,
                     placeholder_text="https://www.youtube.com/watch?v=…").grid(
            row=0, column=0, sticky="ew")
        ctk.CTkButton(self.url_row, text="⚖️ تخمین حجم", width=110,
                      command=self._check_url).grid(row=0, column=1, padx=(8, 0))

        # options row
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.grid(row=3, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 0))
        for i in range(4):
            row.columnconfigure(i, weight=1, uniform="ropt")
        ctk.CTkLabel(row, text="زبان", anchor="w").grid(row=0, column=0, sticky="ew")
        self.lang_menu = ctk.CTkOptionMenu(row, values=[lbl for _, lbl in engine.LANGUAGES])
        self.lang_menu.set(engine.LANGUAGES[0][1])
        self.lang_menu.grid(row=1, column=0, sticky="ew", padx=(0, 6))

        ctk.CTkLabel(row, text="استایل زیرنویس", anchor="w").grid(row=0, column=1, sticky="ew")
        self.style_menu = ctk.CTkOptionMenu(row, values=[lbl for _, lbl in engine.SUBTITLE_STYLES])
        self.style_menu.set(engine.SUBTITLE_STYLES[0][1])
        self.style_menu.grid(row=1, column=1, sticky="ew", padx=6)

        ctk.CTkLabel(row, text="فرمت خروجی", anchor="w").grid(row=0, column=2, sticky="ew")
        self.fmt_menu = ctk.CTkOptionMenu(row, values=["SRT", "TXT", "SRT + TXT"])
        self.fmt_menu.set("SRT")
        self.fmt_menu.grid(row=1, column=2, sticky="ew", padx=6)

        ctk.CTkLabel(row, text="موتور تشخیص", anchor="w").grid(row=0, column=3, sticky="ew")
        self.prov_menu = ctk.CTkOptionMenu(row, values=[lbl for _, lbl in engine.PROVIDERS])
        self.prov_menu.set(engine.PROVIDERS[0][1])
        self.prov_menu.grid(row=1, column=3, sticky="ew", padx=(6, 0))

        # output + deep
        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.grid(row=4, column=0, columnspan=3, sticky="ew", padx=12, pady=(8, 0))
        row2.columnconfigure(1, weight=1)
        ctk.CTkLabel(row2, text="پوشه‌ی خروجی").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.out_var = ctk.StringVar(value=self.app.settings["out_dir"])
        ctk.CTkEntry(row2, textvariable=self.out_var).grid(row=0, column=1, sticky="ew")
        ctk.CTkButton(row2, text="…", width=34, command=self._pick_out).grid(
            row=0, column=2, padx=(6, 0))

        self.deep_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(row2, text="✨ حالت عمیق (فقط با Gemini؛ صدا گوش داده و بازنویسی می‌کند)",
                        variable=self.deep_var).grid(row=1, column=0, columnspan=3,
                                                     sticky="w", pady=(8, 0))

        # actions
        act = ctk.CTkFrame(card, fg_color="transparent")
        act.grid(row=5, column=0, columnspan=3, sticky="ew", padx=12, pady=(10, 12))
        self.start_btn = ctk.CTkButton(act, text=self._START, height=38, width=180,
                                       fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                       command=self._start)
        self.start_btn.pack(side="right")
        self.cancel_btn = ctk.CTkButton(act, text="⛔ لغو", height=38, width=90,
                                        fg_color="#B44", hover_color="#d55",
                                        command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="right", padx=(0, 8))

        self._switch_source(
            "📁 فایل محلی" if self.app.settings["transcribe_source"] == "file" else "📺 لینک یوتیوب")

    def _switch_source(self, choice):
        val = "file" if choice.startswith("📁") else "url"
        self.app.settings["transcribe_source"] = val
        if val == "file":
            self.url_row.grid_forget()
            self.file_row.grid(row=2, column=0, columnspan=3, sticky="ew", padx=12, pady=2)
        else:
            self.file_row.grid_forget()
            self.url_row.grid(row=2, column=0, columnspan=3, sticky="ew", padx=12, pady=2)

    def _pick_file(self):
        path = fd.askopenfilename(
            parent=self, title="فایل ویدیو/صدا",
            filetypes=[("Media", "*.mp4 *.mkv *.mov *.avi *.webm *.mp3 *.wav *.m4a *.opus *.ogg *.aac *.flac"),
                       ("همه فایل‌ها", "*.*")])
        if path:
            self.path_var.set(path)

    def _pick_out(self):
        path = fd.askdirectory(parent=self, initialdir=self.out_var.get() or HERE,
                               title="پوشه‌ی خروجی")
        if path:
            self.out_var.set(path)

    def _check_url(self):
        url = self.url_var.get().strip()
        if not url:
            mb.showwarning(APP_NAME, "لینک یوتیوب را وارد کن.")
            return
        self.status_lbl.configure(text="⏳ در حال تخمین حجم و مدت…")

        def work():
            return engine.probe_sizes(url)

        def done(result, err):
            if err:
                self.status_lbl.configure(text=f"⚠️ {err}")
                self.logf(f"⛔ تخمین ناموفق: {err}")
                return
            parts = [f"{k}: {v}MB" for k, v in (result or {}).items()
                     if v and k not in ("audio", "m4a")]
            label = "  |  ".join(parts[:3]) if parts else "— چیزی پیدا نشد"
            self.status_lbl.configure(text=label)
            self.logf(f"📊 حجم‌ها: {label}")

        self.start_worker(work, done)

    def _start(self):
        if self._job is not None and self._job.running:
            mb.showwarning(APP_NAME, "یک کار در حال اجراست؛ صبر کن یا لغو کن.")
            return
        out_dir = self.out_var.get().strip() or self.app.settings["out_dir"]
        os.makedirs(out_dir, exist_ok=True)
        self.app.settings["out_dir"] = out_dir

        lang_code = {lbl: code for code, lbl in engine.LANGUAGES}[self.lang_menu.get()]
        style_code = {lbl: code for code, lbl in engine.SUBTITLE_STYLES}[self.style_menu.get()]
        fmt = {"SRT": "srt", "TXT": "txt", "SRT + TXT": "both"}[self.fmt_menu.get()]
        prov = {lbl: code for code, lbl in engine.PROVIDERS}[self.prov_menu.get()]
        deep = self.deep_var.get()

        if self.app.settings["transcribe_source"] == "file":
            path = self.path_var.get().strip()
            if not path or not os.path.exists(path):
                mb.showerror(APP_NAME, "فایل ورودی پیدا نشد.")
                return
            payload = ("file", path)
        else:
            url = self.url_var.get().strip()
            if not ("youtube.com" in url or "youtu.be" in url):
                mb.showerror(APP_NAME, "لینک یوتیوب معتبر نیست.")
                return
            payload = ("url", url)

        groq = engine.groq_keys(self.app.settings.get("groq_key"))
        gem = engine.gemini_keys(self.app.settings.get("gemini_key"))
        if prov == "groq" and not groq:
            mb.showerror(APP_NAME, "برای Groq اول کلید API را در تب «تنظیمات» بگذار.")
            return
        if prov == "gemini" and not gem:
            mb.showerror(APP_NAME, "برای Gemini اول کلید API را در تب «تنظیمات» بگذار.")
            return

        job = self.make_job()
        self.set_running(True)
        self.log(f"▶️ شروع؛ موتور={prov}  زبان={lang_code}  استایل={style_code}")

        def work():
            if payload[0] == "file":
                return engine.transcribe_file(
                    job, groq, payload[1], out_dir, language=lang_code,
                    output_format=fmt, style=style_code, provider=prov,
                    deep=deep, refine_keys=gem)
            return engine.transcribe_youtube(
                job, groq, payload[1], out_dir, language=lang_code,
                output_format=fmt, style=style_code, provider=prov,
                deep=deep, refine_keys=gem)

        def done(result, err):
            self.set_running(False)
            if err:
                self.status_lbl.configure(text=f"❌ {err}")
                mb.showerror(APP_NAME, str(err))
                return
            paths = ", ".join(os.path.basename(p) for p in (result or {}).values() if p)
            self.status_lbl.configure(text=f"✅ تمام شد:  {paths}")
            self.log(f"✅ ساخته شد → {out_dir}")
            mb.showinfo(APP_NAME, f"زیرنویس ساخته شد:\n{paths}\n\nپوشه:\n{out_dir}")

        self.start_worker(work, done)

    def _cancel(self):
        if self._job:
            self._job.cancel()
            self.log("⏳ در حال لغو…")


# =============================== Download ===================================

class DownloadTab(Tab):
    _START = "🚀 شروع دانلود"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.kind = "video"
        self._build_control_card()
        self._progress_block()
        self._start_text = self._START

    def _build_control_card(self):
        card = ctk.CTkFrame(self, corner_radius=12)
        card.grid(row=0, column=0, sticky="new", padx=2, pady=(0, 8))
        card.columnconfigure(0, weight=1)

        ctk.CTkLabel(card, text="📺 دانلود از یوتیوب  (ویدیو · صدا · زیرنویس · مشخصات TXT)",
                     font=("", 15, "bold"), anchor="w").grid(
            row=0, column=0, columnspan=3, sticky="ew", padx=12, pady=(10, 6))

        self.url_var = ctk.StringVar()
        ctk.CTkEntry(card, textvariable=self.url_var,
                     placeholder_text="لینک یوتیوب…").grid(
            row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 8))

        # kind chips
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.grid(row=2, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 8))
        for i in range(4):
            row.columnconfigure(i, weight=1, uniform="kct")
        self.kind_btns = {}
        self._kind_default = None
        for i, (code, lbl) in enumerate(
                [("video", "🎬 ویدیو"), ("audio", "🎧 صدا"),
                 ("subs", "💬 زیرنویس"), ("txt", "📄 TXT")]):
            b = ctk.CTkButton(row, text=lbl, height=30, corner_radius=8,
                              command=lambda c=code: self._set_kind(c))
            b.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0))
            if self._kind_default is None:
                self._kind_default = b.cget("fg_color")
            self.kind_btns[code] = b

        # quality row
        qual_row = ctk.CTkFrame(card, fg_color="transparent")
        qual_row.grid(row=3, column=0, columnspan=3, sticky="ew", padx=12)
        qual_row.columnconfigure(0, weight=1)
        qual_row.columnconfigure(1, weight=1)
        ctk.CTkLabel(qual_row, text="کیفیت / فرمت", anchor="w").grid(
            row=0, column=0, sticky="ew")
        self.quality_menu = ctk.CTkOptionMenu(
            qual_row, values=[lbl for _, lbl in engine.DL_VIDEO_QUALITIES],
            command=self._quality_to_probe)
        self.quality_menu.set(engine.DL_VIDEO_QUALITIES[0][1])
        self.quality_menu.grid(row=1, column=0, columnspan=2, sticky="ew")

        # size estimate row
        size_row = ctk.CTkFrame(card, fg_color="transparent")
        size_row.grid(row=4, column=0, columnspan=3, sticky="ew", padx=12, pady=(6, 0))
        size_row.columnconfigure(0, weight=1)
        self.size_label = ctk.CTkLabel(size_row, text="", anchor="w", text_color="gray60")
        self.size_label.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(size_row, text="⚖️ تخمین حجم", width=110,
                      command=self._probe).grid(row=0, column=1, padx=(6, 0))

        # cookies row
        ck = ctk.CTkFrame(card, fg_color="transparent")
        ck.grid(row=5, column=0, columnspan=3, sticky="ew", padx=12, pady=(6, 0))
        ck.columnconfigure(0, weight=1)
        ctk.CTkLabel(ck, text="🍪 فایل کوکی (اختیاری؛ برای ویدیوهای سن/محتوایی محدود)",
                     anchor="w").grid(row=0, column=0, sticky="ew")
        self.cookie_var = ctk.StringVar(value=self.app.settings.get("cookies", ""))
        ctk.CTkEntry(ck, textvariable=self.cookie_var,
                     placeholder_text="…\\cookies.txt  — خالی بگذار اگر لازم نیست").grid(
            row=1, column=0, sticky="ew")
        ctk.CTkButton(ck, text="…", width=34, command=self._pick_cookie).grid(
            row=1, column=1, padx=(6, 0))

        # output row
        out = ctk.CTkFrame(card, fg_color="transparent")
        out.grid(row=6, column=0, columnspan=3, sticky="ew", padx=12, pady=(6, 0))
        out.columnconfigure(1, weight=1)
        ctk.CTkLabel(out, text="پوشه‌ی ذخیره").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.out_var = ctk.StringVar(value=self.app.settings["out_dir"])
        ctk.CTkEntry(out, textvariable=self.out_var).grid(row=0, column=1, sticky="ew")
        ctk.CTkButton(out, text="…", width=34, command=self._pick_out).grid(
            row=0, column=2, padx=(6, 0))

        # optional proxy quick-edit
        ctk.CTkButton(card, text="🛠 تنظیم پروکسی (residential)",
                      width=230, height=26, fg_color="#555", hover_color="#666",
                      command=self.app.show_proxy_dialog).grid(
            row=7, column=0, columnspan=3, sticky="w", padx=12, pady=(10, 0))

        # actions
        act = ctk.CTkFrame(card, fg_color="transparent")
        act.grid(row=8, column=0, columnspan=3, sticky="ew", padx=12, pady=(10, 12))
        self.start_btn = ctk.CTkButton(act, text=self._START, height=38, width=150,
                                       fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                       command=self._start)
        self.start_btn.pack(side="right")
        self.cancel_btn = ctk.CTkButton(act, text="⛔ لغو", height=38, width=90,
                                        fg_color="#B44", hover_color="#d55",
                                        command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="right", padx=(0, 8))

        self._set_kind("video")

    def _set_kind(self, code):
        self.kind = code
        for c, b in self.kind_btns.items():
            b.configure(fg_color=ACCENT if c == code else self._kind_default)
        menu = self.quality_menu
        if code == "video":
            menu.configure(values=[lbl for _, lbl in engine.DL_VIDEO_QUALITIES])
            menu.set(engine.DL_VIDEO_QUALITIES[0][1])
            self.size_label.configure(text="کیفیت ویدیو را انتخاب کن؛ «تخمین حجم» سایز هر گزینه را می‌دهد.")
        elif code == "audio":
            menu.configure(values=[lbl for _, lbl in engine.DL_AUDIO_QUALITIES])
            menu.set(engine.DL_AUDIO_QUALITIES[0][1])
            self.size_label.configure(text="فرمت صدا را انتخاب کن.")
        else:
            menu.configure(values=["🌐 اصلی (original)", "🇮🇷 فارسی", "🇬🇧 انگلیسی", "🇩🇪 آلمانی"])
            menu.set("🌐 اصلی (original)")
            self.size_label.configure(
                text="زیرنویس آماده‌ی خود یوتیوب (در صورت وجود) دریافت می‌شود.")

    def _quality_to_probe(self, _):
        # auto-probe sizes when the user lands on a video quality
        if self.kind == "video":
            self._probe()

    def _pick_cookie(self):
        path = fd.askopenfilename(parent=self, initialdir=HERE,
                                  filetypes=[("cookies.txt", "*.txt"), ("همه", "*.*")])
        if path:
            self.cookie_var.set(path)
            self.app.settings["cookies"] = path
            save_settings(self.app.settings)

    def _pick_out(self):
        path = fd.askdirectory(parent=self, initialdir=self.out_var.get() or HERE,
                               title="پوشه‌ی ذخیره")
        if path:
            self.out_var.set(path)

    def _probe(self):
        url = self.url_var.get().strip()
        if not url:
            mb.showwarning(APP_NAME, "لینک یوتیوب را وارد کن.")
            return
        self.size_label.configure(text="⏳ در حال تخمین…")
        self.status_lbl.configure(text="⏳ پرس‌وجوی اطلاعات ویدیو…")

        def work():
            return engine.probe_sizes(url)

        def done(result, err):
            if err:
                self.size_label.configure(text=f"⚠️ تخمین ناموفق: {err}")
                self.status_lbl.configure(text="⚠️ تخمین ناموفق")
                return
            mapping = {lbl: code for code, lbl in engine.DL_VIDEO_QUALITIES}
            current = mapping.get(self.quality_menu.get())
            parts = []
            for k, v in (result or {}).items():
                if v:
                    parts.append(f"{engine.DL_VIDEO.get(k, k)}: {v}MB")
            text = "  |  ".join(parts[:4]) if parts else "— چیزی پیدا نشد"
            self.size_label.configure(text=text)
            self.log(f"📊 حجم‌ها: {text}")

        self.start_worker(work, done)

    def _start(self):
        if self._job is not None and self._job.running:
            mb.showwarning(APP_NAME, "یک کار در حال اجراست.")
            return
        url = self.url_var.get().strip()
        if not ("youtube.com" in url or "youtu.be" in url):
            mb.showerror(APP_NAME, "لینک یوتیوب معتبر نیست.")
            return
        out_dir = self.out_var.get().strip() or self.app.settings["out_dir"]
        os.makedirs(out_dir, exist_ok=True)
        self.app.settings["out_dir"] = out_dir

        menu2code = {lbl: code for code, lbl in engine.DL_VIDEO_QUALITIES}
        menu2code.update({lbl: code for code, lbl in engine.DL_AUDIO_QUALITIES})
        q_label = self.quality_menu.get()
        quality = menu2code.get(q_label, "best")
        cookies = self.cookie_var.get().strip()
        kind = self.kind

        lang = None
        if kind == "subs":
            lang = None if "اصلی" in q_label else (
                "fa" if "فارسی" in q_label else "en" if "انگلیسی" in q_label else "de")

        job = self.make_job()
        self.set_running(True)
        self.log(f"▶️ شروع دانلود ({kind}; {quality or lang or ''})")

        def work():
            if kind == "subs":
                return engine.download_subtitles(job, url, out_dir, lang=lang, cookies=cookies)
            if kind == "txt":
                return engine.download_info_txt(job, url, out_dir, cookies=cookies)
            return engine.download_media(job, url, out_dir, quality=quality, cookies=cookies)

        def done(result, err):
            self.set_running(False)
            if err:
                self.status_lbl.configure(text=f"❌ {err}")
                mb.showerror(APP_NAME, str(err))
                return
            if kind == "subs" and isinstance(result, tuple):
                path, tgt, kd, title = result
                self.status_lbl.configure(text=f"✅ زیرنویس ({tgt}): {os.path.basename(path)}")
                self.log(f"✅ زیرنویس «{title}» ({tgt} — {kd}) → {path}")
                mb.showinfo(APP_NAME, f"زیرنویس «{title}»:\n{path}")
                return
            if kind == "txt" and isinstance(result, tuple):
                path, title = result
                self.status_lbl.configure(text=f"✅ TXT: {os.path.basename(path)}")
                self.log(f"✅ مشخصات «{title}» → {path}")
                mb.showinfo(APP_NAME, f"معلومات «{title}»:\n{path}")
                return
            self.status_lbl.configure(text=f"✅ {os.path.basename(result)}")
            self.log(f"✅ دانلود شد → {result}")
            mb.showinfo(APP_NAME, f"فایل:\n{result}")

        self.start_worker(work, done)

    def _cancel(self):
        if self._job:
            self._job.cancel()
            self.log("⏳ در حال لغو…")


# =============================== Translate ==================================

class TranslateTab(Tab):
    _START = "🚀 ترجمه کن"

    def __init__(self, master, app):
        super().__init__(master, app)
        self._build_control_card()
        self._progress_block()
        self._start_text = self._START

    def _build_control_card(self):
        card = ctk.CTkFrame(self, corner_radius=12)
        card.grid(row=0, column=0, sticky="new", padx=2, pady=(0, 8))
        card.columnconfigure(0, weight=1)

        ctk.CTkLabel(card, text="🌍 ترجمه‌ی فایل SRT با Gemini", font=("", 15, "bold"),
                     anchor="w").grid(row=0, column=0, columnspan=3, sticky="ew",
                                      padx=12, pady=(10, 6))

        self.srt_var = ctk.StringVar()
        fr = ctk.CTkFrame(card, fg_color="transparent")
        fr.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 8))
        fr.columnconfigure(0, weight=1)
        ctk.CTkEntry(fr, textvariable=self.srt_var,
                     placeholder_text="مسیر فایل .srt ورودی…").grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(fr, text="انتخاب فایل…", width=110,
                      command=self._pick).grid(row=0, column=1, padx=(8, 0))

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.grid(row=2, column=0, columnspan=3, sticky="ew", padx=12)
        for i in range(2):
            row.columnconfigure(i, weight=1, uniform="topt")
        ctk.CTkLabel(row, text="به زبان", anchor="w").grid(row=0, column=0, sticky="ew")
        self.lang_menu = ctk.CTkOptionMenu(row, values=[lbl for _, lbl, _ in engine.TRANSLATE_LANGUAGES])
        self.lang_menu.set(engine.TRANSLATE_LANGUAGES[0][1])
        self.lang_menu.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkLabel(row, text="سبک ترجمه", anchor="w").grid(row=0, column=1, sticky="ew")
        self.style_menu = ctk.CTkOptionMenu(row, values=[lbl for _, lbl in engine.TRANSLATE_STYLES])
        self.style_menu.set(engine.TRANSLATE_STYLES[0][1])
        self.style_menu.grid(row=1, column=1, sticky="ew", padx=(6, 0))

        out = ctk.CTkFrame(card, fg_color="transparent")
        out.grid(row=3, column=0, columnspan=3, sticky="ew", padx=12, pady=(8, 0))
        out.columnconfigure(1, weight=1)
        ctk.CTkLabel(out, text="پوشه‌ی خروجی").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.out_var = ctk.StringVar(value=self.app.settings["out_dir"])
        ctk.CTkEntry(out, textvariable=self.out_var).grid(row=0, column=1, sticky="ew")
        ctk.CTkButton(out, text="…", width=34,
                      command=lambda: self.out_var.set(
                          fd.askdirectory(parent=self, initialdir=self.out_var.get() or HERE,
                                          title="پوشه‌ی خروجی") or self.out_var.get())
                      ).grid(row=0, column=2, padx=(6, 0))

        act = ctk.CTkFrame(card, fg_color="transparent")
        act.grid(row=4, column=0, columnspan=3, sticky="ew", padx=12, pady=(10, 12))
        self.start_btn = ctk.CTkButton(act, text=self._START, height=38, width=130,
                                       fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                       command=self._start)
        self.start_btn.pack(side="right")
        self.cancel_btn = ctk.CTkButton(act, text="⛔ لغو", height=38, width=90,
                                        fg_color="#B44", hover_color="#d55",
                                        command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="right", padx=(0, 8))
        self._job = None

    def _pick(self):
        path = fd.askopenfilename(parent=self, filetypes=[("SRT", "*.srt"), ("همه", "*.*")])
        if path:
            self.srt_var.set(path)

    def _start(self):
        if self._job is not None and self._job.running:
            mb.showwarning(APP_NAME, "یک کار در حال اجراست.")
            return
        srt_path = self.srt_var.get().strip()
        if not srt_path or not os.path.exists(srt_path):
            mb.showerror(APP_NAME, "فایل SRT پیدا نشد.")
            return
        out_dir = self.out_var.get().strip() or self.app.settings["out_dir"]
        os.makedirs(out_dir, exist_ok=True)
        lang_label = self.lang_menu.get()
        lang_code = next(c for c, l, _ in engine.TRANSLATE_LANGUAGES if l == lang_label)
        human = next(h for _, l, h in engine.TRANSLATE_LANGUAGES if l == lang_label)
        style = {lbl: code for code, lbl in engine.TRANSLATE_STYLES}[self.style_menu.get()]
        keys = engine.gemini_keys(self.app.settings.get("gemini_key"))
        if not keys:
            mb.showerror(APP_NAME, "اول کلید Gemini را در تب «تنظیمات» بگذار.")
            return

        job = self.make_job()
        self.set_running(True)
        self.log(f"▶️ ترجمه به {human} ({style}) — {len(keys)} کلید")

        def work():
            return engine.translate_srt_file(job, srt_path, out_dir, target_language=human,
                                             style=style, lang_code=lang_code,
                                             gemini_keys_list=keys)

        def done(result, err):
            self.set_running(False)
            if err:
                self.status_lbl.configure(text=f"❌ {err}")
                mb.showerror(APP_NAME, str(err))
                return
            self.status_lbl.configure(text=f"✅ {os.path.basename(result)}")
            self.log(f"✅ ترجمه شد → {result}")
            mb.showinfo(APP_NAME, f"ترجمه آماده است:\n{result}")

        self.start_worker(work, done)

    def _cancel(self):
        if self._job:
            self._job.cancel()
            self.log("⏳ در حال لغو…")


# =============================== Settings ===================================

class SettingsTab(Tab):
    def __init__(self, master, app):
        # Settings uses a plain scrolling column; no progress block.
        super().__init__(master, app)
        self.rowconfigure(0, weight=1)
        self._busy = False

        card = ctk.CTkFrame(self, corner_radius=12)
        card.grid(row=0, column=0, sticky="new", padx=2, pady=(0, 8))
        card.columnconfigure(1, weight=1)

        ctk.CTkLabel(card, text="⚙️ تنظیمات", font=("", 15, "bold"),
                     anchor="w").grid(row=0, column=0, columnspan=3, sticky="ew",
                                      padx=12, pady=(10, 6))

        ctk.CTkLabel(card, text="کلید Groq API").grid(row=1, column=0, sticky="w", padx=12, pady=3)
        self.groq_var = ctk.StringVar(value="•" * 8 if app.settings.get("groq_key") else "")
        self.groq_entry = ctk.CTkEntry(card, textvariable=self.groq_var, show="•",
                                       placeholder_text="gsk_…  (API Whisper رایگان Groq)")
        self.groq_entry.grid(row=1, column=1, sticky="ew", padx=6, pady=3)

        ctk.CTkLabel(card, text="کلید Gemini API").grid(row=2, column=0, sticky="w", padx=12, pady=3)
        self.gem_var = ctk.StringVar(value="•" * 8 if app.settings.get("gemini_key") else "")
        self.gem_entry = ctk.CTkEntry(card, textvariable=self.gem_var, show="•",
                                      placeholder_text="AIza…  (برای ترجمه و حالت عمیق)")
        self.gem_entry.grid(row=2, column=1, sticky="ew", padx=6, pady=3)

        self.save_keys_var = ctk.BooleanVar(value=app.settings.get("save_keys", False))
        ctk.CTkCheckBox(card, text="کلیدها را هم در استخر محلی (keys/) ذخیره کن",
                        variable=self.save_keys_var).grid(
            row=3, column=0, columnspan=3, sticky="w", padx=12, pady=(6, 0))

        ctk.CTkLabel(card, text="پوشه پیش‌فرض خروجی").grid(row=4, column=0, sticky="w", padx=12, pady=3)
        self.out_var = ctk.StringVar(value=app.settings["out_dir"])
        ctk.CTkEntry(card, textvariable=self.out_var).grid(row=4, column=1, sticky="ew", padx=6, pady=3)
        ctk.CTkButton(card, text="…", width=34,
                      command=lambda: self.out_var.set(
                          fd.askdirectory(parent=self, initialdir=self.out_var.get() or HERE,
                                          title="پوشه خروجی") or self.out_var.get())
                      ).grid(row=4, column=2, padx=(6, 12), pady=3)

        ctk.CTkLabel(card, text="پروکسی یوتیوب (اختیاری)").grid(row=5, column=0, sticky="w", padx=12, pady=3)
        self.proxy_var = ctk.StringVar(value=app.settings.get("proxy", ""))
        ctk.CTkEntry(card, textvariable=self.proxy_var,
                     placeholder_text="http://user:pass@host:port  — خالی = بدون پروکسی").grid(
            row=5, column=1, columnspan=2, sticky="ew", padx=(6, 12), pady=3)

        ctk.CTkButton(card, text="💾 ذخیره تنظیمات", height=36, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, command=self._save).grid(
            row=6, column=0, columnspan=3, sticky="ew", padx=12, pady=(12, 12))

        guide = ctk.CTkFrame(self, corner_radius=12)
        guide.grid(row=1, column=0, sticky="new", padx=2)
        guide.columnconfigure(0, weight=1)
        ctk.CTkLabel(guide, text="📖 پیوندهای مفید", font=("", 14, "bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        for i, (text, url) in enumerate([
            ("دریافت کلید رایگان Groq", "https://console.groq.com/keys"),
            ("دریافت کلید Gemini (Google AI Studio)", "https://aistudio.google.com/apikey"),
            ("افزونه‌ی Get cookies.txt LOCALLY (کروم)", "https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc"),
            ("مخزن CustomTkinter", "https://github.com/TomSchimansky/CustomTkinter"),
        ]):
            ctk.CTkButton(guide, text=text, height=30, anchor="w",
                          fg_color="transparent", hover_color=("#ddd", "#333"),
                          text_color=("#1f6feb", "#8ab4f8"),
                          command=lambda u=url: webbrowser.open(u)).grid(
                row=1 + i, column=0, sticky="ew", padx=12, pady=2)
        ctk.CTkLabel(guide, justify="left", anchor="w", wraplength=560,
                     text="پیش‌نیازها: Python 3.10+، ffmpeg روی PATH، و بسته‌های requirements.txt\n"
                          "(اسکریپت run.bat این‌ها را برایتان خودکار می‌کند)").grid(
            row=5, column=0, sticky="ew", padx=12, pady=(6, 10))

        # start/cancel not used here; give inert buttons so set_running never crashes
        self.start_btn = ctk.CTkButton(self, width=0, fg_color="transparent", state="disabled")
        self.cancel_btn = ctk.CTkButton(self, width=0, fg_color="transparent", state="disabled")
        self._start_text = ""

    def _save(self):
        s = self.app.settings
        groq = self.groq_var.get().strip()
        gem = self.gem_var.get().strip()
        if groq and not groq.startswith("•"):
            s["groq_key"] = groq
        if gem and not gem.startswith("•"):
            s["gemini_key"] = gem
        s["save_keys"] = bool(self.save_keys_var.get())
        if s["save_keys"]:
            if s["groq_key"]:
                added, total = engine.save_key("groq", s["groq_key"])
                self.log(f"🔑 Groq keys pool: {total} (اضافه شد)" if added else f"🔑 Groq keys pool: {total}")
            if s["gemini_key"]:
                added, total = engine.save_key("gemini", s["gemini_key"])
                self.log(f"🔑 Gemini keys pool: {total}" + (" (اضافه شد)" if added else ""))
        s["out_dir"] = self.out_var.get().strip() or s["out_dir"]
        s["proxy"] = self.proxy_var.get().strip()
        self.app.apply_proxy(s["proxy"])
        save_settings(s)
        mb.showinfo(APP_NAME, "تنظیمات ذخیره شد ✅")


# =============================== App ========================================

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.title(f"{APP_NAME} v{VERSION}")
        self.geometry(self.settings.get("geometry", "1180x760"))
        self.minsize(960, 640)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.apply_proxy(self.settings.get("proxy", ""))

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- sidebar ----------------------------------------------------------
        self.sidebar = ctk.CTkFrame(self, corner_radius=0, width=220)
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.sidebar.grid_propagate(False)
        self.sidebar.columnconfigure(0, weight=1)
        self.sidebar.rowconfigure(98, weight=1)  # spacer pushes controls to bottom

        ctk.CTkLabel(self.sidebar, text=f"🤖 {APP_NAME}", font=("", 20, "bold"),
                     anchor="w").grid(row=0, column=0, padx=16, pady=(18, 0), sticky="ew")
        ctk.CTkLabel(self.sidebar, text="نسخه‌ی دسکتاپ موتور ربات Arion",
                     text_color="gray50", anchor="w").grid(row=1, column=0, padx=16, sticky="ew")

        self.nav_btns = {}
        for i, (name, label) in enumerate([
            ("transcribe", "🎬  ساخت زیرنویس"),
            ("download", "📺  دانلود یوتیوب"),
            ("translate", "🌍  ترجمه‌ی SRT"),
            ("settings", "⚙️  تنظیمات"),
        ]):
            b = ctk.CTkButton(self.sidebar, text=label, height=40, anchor="w",
                              corner_radius=8, fg_color="transparent",
                              hover_color=("#ddd", "#333"),
                              command=lambda n=name: self.show(n))
            b.grid(row=2 + i, column=0, padx=10, pady=3, sticky="ew")
            self.nav_btns[name] = b

        ui = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        ui.grid(row=99, column=0, padx=12, pady=10, sticky="sew")
        ui.columnconfigure(0, weight=1)

        ctk.CTkLabel(ui, text="🔍 اندازه‌ی عناصر رابط", font=("", 12),
                     anchor="w").grid(row=0, column=0, sticky="ew")
        self.scale_val = ctk.DoubleVar(value=float(self.settings.get("scale", 1.0)))
        ctk.CTkSlider(ui, from_=0.7, to=1.6, number_of_steps=18,
                      variable=self.scale_val, command=self._on_scale
                      ).grid(row=1, column=0, sticky="ew", pady=(2, 6))

        ctk.CTkLabel(ui, text="🎨 ظاهر (تیره/روشن)", font=("", 12),
                     anchor="w").grid(row=2, column=0, sticky="ew")
        self.theme_menu = ctk.CTkOptionMenu(ui, values=["system", "dark", "light"],
                                           command=self._on_theme)
        self.theme_menu.set(self.settings.get("theme", "system"))
        self.theme_menu.grid(row=3, column=0, sticky="ew", pady=(2, 4))

        ctk.CTkLabel(ui, text="💡 پنجره کاملاً قابل تغییر اندازه است؛ ستون‌ها و کارت‌ها\nهمراه با پنجره کش می‌آیند.",
                     font=("", 11), justify="left", text_color="gray50",
                     wraplength=190).grid(row=4, column=0, sticky="ew", pady=(8, 0))
        self._apply_scale(float(self.scale_val.get()))

        # --- content ----------------------------------------------------------
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew", padx=(8, 12), pady=10)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.tabs = {
            "transcribe": TranscribeTab(self.content, self),
            "download": DownloadTab(self.content, self),
            "translate": TranslateTab(self.content, self),
            "settings": SettingsTab(self.content, self),
        }
        self.show("transcribe")

    # --- behavior -------------------------------------------------------------
    def show(self, name):
        for n, tab in self.tabs.items():
            if n == name:
                tab.grid(row=0, column=0, sticky="nsew")
            else:
                tab.grid_forget()
        for n, btn in self.nav_btns.items():
            btn.configure(fg_color=("#dcdcdc", "#2f3044") if n == name else "transparent")

    def _on_scale(self, value):
        self._apply_scale(value)

    @staticmethod
    def _apply_scale(value):
        ctk.set_widget_scaling(float(value))
        ctk.set_window_scaling(float(value))

    def _on_theme(self, choice):
        ctk.set_appearance_mode(choice)
        self.settings["theme"] = choice

    def apply_proxy(self, proxy):
        from core import config as _cfg
        _cfg.YT_PROXY = (proxy or "").strip()

    def show_proxy_dialog(self):
        proxy = mb.askstring(APP_NAME,
                             "پروکسی یوتیوب:\n(http://user:pass@host:port — خالی = بدون پروکسی)",
                             initialvalue=self.settings.get("proxy", ""),
                             parent=self)
        if proxy is not None:
            proxy = proxy.strip()
            self.settings["proxy"] = proxy
            self.apply_proxy(proxy)
            save_settings(self.settings)
            mb.showinfo(APP_NAME, "پروکسی اعمال شد." if proxy else "پروکسی برداشته شد.")

    def refresh_out_dirs(self):
        for t in self.tabs.values():
            if hasattr(t, "out_var"):
                t.out_var.set(self.settings["out_dir"])

    def _on_close(self):
        self.settings["geometry"] = self.geometry()
        self.settings["scale"] = float(self.scale_val.get())
        self.settings["theme"] = self.theme_menu.get()
        save_settings(dict(self.settings))
        self.destroy()


def _check_ffmpeg():
    """Warn (and continue) when the ffmpeg toolchain is missing."""
    import shutil
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    root = tk.Tk()
    root.withdraw()
    mb.showwarning(
        "ffmpeg پیدا نشد",
        "برای پردازش صدا/ویدیو به ffmpeg و ffprobe نیاز است.\n\n"
        "ویندوز:  winget install Gyan.FFmpeg\n"
        "(یا از ffmpeg.org دانلود و به PATH اضافه کن)\n"
        "لینوکس:  sudo apt install ffmpeg      مک:  brew install ffmpeg\n\n"
        "برنامه ادامه می‌دهد ولی کارهای صوتی/دانلود کار نخواهند کرد.",
    )
    root.destroy()


def main():
    _check_ffmpeg()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
