"""Arion Studio — desktop GUI for the Arion subtitle / download / translate engine.

Runs on CustomTkinter (https://github.com/TomSchimansky/CustomTkinter).

Two things this file takes seriously:

1. **Precise reporting** — every job pushes a monotonic percentage, the current
   stage, elapsed time, ETA, transfer speed and a timestamped log line. All
   widget work happens on the Tk main loop through a queue; worker threads only
   push messages.
2. **Non-English keyboards** — Tk maps Ctrl+<key> through the *active keyboard
   layout*, so on a Persian/Arabic/Cyrillic layout ``event.keysym`` is "ث"
   instead of "c" and every keysym-based shortcut and paste silently dies. Here
   shortcuts are resolved from the **physical key code** (Windows virtual key)
   with keysym as fallback, and every text field also gets a right-click menu.
   Fonts are chosen from families that actually contain Persian glyphs.

Run:  python main.py
"""

import ctypes
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.filedialog as fd
import tkinter.font as tkfont
import tkinter.messagebox as mb
import webbrowser

import customtkinter as ctk

import engine
import i18n
from i18n import t

APP_NAME = "Arion Studio"
VERSION = "0.2.0a1"
HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(HERE, "settings.json")
LOG_DIR = os.path.join(HERE, "logs")

ACCENT = "#7C5CFF"
ACCENT_HOVER = "#6547e0"
DANGER = "#B44"
DANGER_HOVER = "#d55"
MUTED = ("#5b5b5b", "#9aa0a6")

TAB_ORDER = ["transcribe", "download", "translate", "settings"]

DEFAULT_GEOMETRY = "1240x800"
MIN_WIDTH, MIN_HEIGHT = 980, 660

DEFAULTS = {
    "groq_key": "",
    "gemini_key": "",
    "save_keys": False,
    "out_dir": os.path.join(HERE, "output"),
    "cookies": "",
    "proxy": "",
    "theme": "system",
    "scale": 1.0,
    "geometry": DEFAULT_GEOMETRY,
    "transcribe_source": "file",
    "last_file": "",
    "last_srt": "",
    "last_url": "",
    "download_kind": "video",
    "language": i18n.DEFAULT_LANGUAGE,
}

# Families that ship Persian/Arabic glyphs *and* Latin, most attractive first.
FONT_CANDIDATES = (
    "Vazirmatn", "Vazir", "IRANSansX", "IRANSans", "Sahel", "Shabnam",
    "Segoe UI", "Tahoma", "Noto Sans Arabic", "Noto Naskh Arabic",
    "Arial Unicode MS", "DejaVu Sans", "Arial",
)
# Plain system families: enough for English, preferred when the UI is English.
LATIN_FONT_CANDIDATES = (
    "Segoe UI", "Inter", "Noto Sans", "DejaVu Sans", "Liberation Sans",
    "Helvetica Neue", "Helvetica", "Arial",
)
UI_FAMILY = "Segoe UI"
_FONT_REGISTRY = []


# ---------------------------------------------------------------- settings I/O

def load_settings():
    data = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            data.update(loaded)
    except Exception:
        pass
    return data


def save_settings(data):
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH) or ".", exist_ok=True)
        tmp = SETTINGS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_PATH)
    except Exception:
        pass


def fmt_duration(seconds):
    """Human readable duration: 12s · 4:05 · 1:02:33."""
    try:
        seconds = max(0, int(round(float(seconds))))
    except (TypeError, ValueError):
        return "—"
    if seconds < 60:
        return t("ui.time.seconds", v1=seconds)
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}:{s:02d}"
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}"


def open_in_file_manager(path):
    """Reveal a file/folder in the OS file manager (best effort)."""
    try:
        path = os.path.abspath(path)
        if sys.platform.startswith("win"):
            if os.path.isfile(path):
                subprocess.Popen(["explorer", "/select,", path])
            else:
                os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path if os.path.isdir(path) else
                              os.path.dirname(path)])
        else:
            subprocess.Popen(["xdg-open", path if os.path.isdir(path) else
                              os.path.dirname(path)])
    except Exception:
        pass


# ------------------------------------------------------------------ fonts / DPI


def label_list(pairs):
    """Display labels for an engine constant of (code, translation_key[, extra])."""
    return [t(pair[1]) for pair in pairs]


def label_map(pairs):
    """Reverse lookup {display label: code} for an engine constant."""
    return {t(pair[1]): pair[0] for pair in pairs}

def choose_font_family(root, language=None):
    """Pick a family that can render both the UI language and Latin text."""
    try:
        families = set(tkfont.families(root))
    except Exception:
        families = set()
    if i18n.is_rtl(language):
        preferred = FONT_CANDIDATES          # need Persian/Arabic glyphs
    else:
        preferred = LATIN_FONT_CANDIDATES + FONT_CANDIDATES
    for name in preferred:
        if name in families:
            return name
    return "TkDefaultFont"


def F(size, weight="normal"):
    """Create (and remember) a UI font so the scale slider can resize it live."""
    font = ctk.CTkFont(family=UI_FAMILY, size=int(size), weight=weight)
    _FONT_REGISTRY.append((font, int(size)))
    return font


def rescale_fonts(scale):
    """Resize every registered font; CTk widget scaling handles the geometry."""
    factor = max(0.75, min(1.45, float(scale)))
    for font, base in list(_FONT_REGISTRY):
        try:
            font.configure(size=max(8, int(round(base * factor))))
        except Exception:
            pass


def apply_tk_default_fonts(root):
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont",
                 "TkCaptionFont", "TkSmallCaptionFont", "TkIconFont",
                 "TkTooltipFont"):
        try:
            tkfont.nametofont(name).configure(family=UI_FAMILY)
        except Exception:
            pass
    try:
        ctk.ThemeManager.theme["CTkFont"]["family"] = UI_FAMILY
    except Exception:
        pass


def enable_high_dpi():
    """Crisp text on Windows scaling (must run before Tk is created)."""
    if not sys.platform.startswith("win"):
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# --------------------------------------------------- text widgets & shortcuts

# Windows virtual-key codes and X11 keycodes for the QWERTY positions we bind.
# Both are layout-independent (unlike event.keysym), which is what keeps the
# shortcuts alive on a Persian/Arabic/Cyrillic keyboard layout.
VK = {
    "a": 65, "c": 67, "v": 86, "x": 88, "z": 90, "y": 89,
    "o": 79, "s": 83, "q": 81, "l": 76, "f": 70, "n": 78, "w": 87,
    "r": 82, "t": 84,
}
X11_KEYCODE = {
    "q": 24, "w": 25, "r": 27, "t": 28, "y": 29, "o": 32,
    "a": 38, "s": 39, "f": 41, "l": 46,
    "z": 52, "x": 53, "c": 54, "v": 55, "n": 57,
}
TEXT_KEYS = {"a": "select_all", "c": "copy", "v": "paste", "x": "cut",
             "z": "undo", "y": "redo"}


def inner_text_widget(widget):
    """Return the real tk Entry/Text behind a CTk widget, if any."""
    if isinstance(widget, (tk.Entry, tk.Text)):
        return widget
    for attr in ("_entry", "_textbox", "_text", "textbox"):
        child = getattr(widget, attr, None)
        if isinstance(child, (tk.Entry, tk.Text)):
            return child
    return None


def text_operation(widget, op):
    """Run a clipboard/edit operation on a tk text widget in any layout."""
    target = inner_text_widget(widget) or widget
    try:
        if op == "select_all":
            if isinstance(target, tk.Text):
                target.tag_add("sel", "1.0", "end-1c")
                target.mark_set("insert", "end-1c")
            elif hasattr(target, "selection_range"):
                target.selection_range(0, "end")
                target.icursor("end")
            return True
        if op == "copy":
            target.event_generate("<<Copy>>")
            return True
        if op == "cut":
            target.event_generate("<<Cut>>")
            return True
        if op == "paste":
            target.event_generate("<<Paste>>")
            return True
        if op == "undo":
            if hasattr(target, "edit_undo"):
                target.edit_undo()
            return True
        if op == "redo":
            if hasattr(target, "edit_redo"):
                target.edit_redo()
            return True
    except Exception:
        return False
    return False


def attach_text_menu(ctk_widget, on_open=None):
    """Right-click menu for an entry/textbox (works with every keyboard layout)."""
    inner = inner_text_widget(ctk_widget)
    if inner is None:
        return
    menu = tk.Menu(inner, tearoff=0)
    menu.add_command(label=t("ui.menu.cut"), command=lambda: text_operation(inner, "cut"))
    menu.add_command(label=t("ui.menu.copy"), command=lambda: text_operation(inner, "copy"))
    menu.add_command(label=t("ui.menu.paste"), command=lambda: text_operation(inner, "paste"))
    menu.add_separator()
    menu.add_command(label=t("ui.menu.select_all"),
                     command=lambda: text_operation(inner, "select_all"))
    if on_open is not None:
        menu.add_separator()
        menu.add_command(label=t("ui.menu.choose_file"), command=on_open)

    def _popup(event):
        try:
            inner.focus_set()
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    inner.bind("<Button-3>", _popup, add="+")
    inner.bind("<Button-2>", _popup, add="+")   # macOS right click / middle
    if isinstance(inner, tk.Entry):
        # Persian/Arabic text is right-to-left; make the caret behave sanely.
        try:
            inner.configure(exportselection=True)
        except Exception:
            pass


def make_entry(parent, on_open=None, **kwargs):
    kwargs.setdefault("font", F(13))
    try:
        widget = ctk.CTkEntry(parent, **kwargs)
    except TypeError:
        kwargs.pop("font", None)
        widget = ctk.CTkEntry(parent, **kwargs)
    attach_text_menu(widget, on_open)
    return widget


def make_textbox(parent, **kwargs):
    kwargs.setdefault("font", F(12))
    try:
        widget = ctk.CTkTextbox(parent, **kwargs)
    except TypeError:
        kwargs.pop("font", None)
        widget = ctk.CTkTextbox(parent, **kwargs)
    attach_text_menu(widget)
    return widget


def wrap_text(widget, text):
    """Insert into a (possibly disabled) CTkTextbox without flicker."""
    try:
        widget.configure(state="normal")
        widget.insert("end", text)
        widget.see("end")
        widget.configure(state="disabled")
    except Exception:
        pass


# ------------------------------------------------------------- progress pump

class ProgressPump:
    """Worker threads push messages; the Tk loop drains them.

    Kinds: ``progress`` (job snapshot), ``log`` (text) and ``call`` (a callable
    that must run on the UI thread, e.g. a job's completion handler).
    """

    def __init__(self, tab):
        self.tab = tab
        self.q = queue.Queue()
        self._alive = True
        self._after_id = None
        self._schedule()

    def _schedule(self):
        if not self._alive:
            return
        try:
            self._after_id = self.tab.after(100, self._drain)
        except tk.TclError:
            self._alive = False

    def push(self, *item):
        try:
            self.q.put_nowait(item)
        except Exception:
            pass

    def stop(self):
        """Stop pumping and cancel the pending timer (called on window close)."""
        self._alive = False
        if self._after_id is not None:
            try:
                self.tab.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _drain(self):
        self._after_id = None
        if not self._alive:
            return
        try:
            if not self.tab.winfo_exists():
                self._alive = False
                return
        except tk.TclError:
            self._alive = False
            return
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "progress":
                    self.tab._apply_snapshot(item[1])
                elif kind == "log":
                    self.tab._append_log(item[1])
                elif kind == "call":
                    try:
                        item[1]()
                    except Exception:
                        pass
        except queue.Empty:
            pass
        except tk.TclError:
            self._alive = False
            return
        self._schedule()


# ------------------------------------------------------------------ tab base

class Tab(ctk.CTkFrame):
    #: Translation key of the "start" button; resolved in __init__ so the tab
    #: can be rebuilt when the UI language changes.
    _START_KEY = "ui.btn.start"

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.pump = ProgressPump(self)
        self._job = None
        self._start_text = t(self._START_KEY)
        self._last_label = ""
        self._last_logged_pct = -100.0
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

    # ---- progress block (status + bar + detail + log) ----------------------
    def _progress_block(self, title_hint=""):
        card = ctk.CTkFrame(self, corner_radius=12)
        card.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        card.columnconfigure(0, weight=1)

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 2))
        head.columnconfigure(0, weight=1)
        self.status_lbl = ctk.CTkLabel(
            head, text=title_hint or t("ui.status.idle_ready"),
            anchor="w", font=F(14, "bold"))
        self.status_lbl.grid(row=0, column=0, sticky="ew")
        self.percent_lbl = ctk.CTkLabel(head, text="0.0%", anchor="e",
                                        font=F(15, "bold"), text_color=ACCENT)
        self.percent_lbl.grid(row=0, column=1, sticky="e", padx=(8, 0))

        self.overall_bar = ctk.CTkProgressBar(card, progress_color=ACCENT, height=16)
        self.overall_bar.grid(row=1, column=0, sticky="ew", padx=14, pady=(2, 4))
        self.overall_bar.set(0)

        self.stage_lbl = ctk.CTkLabel(card, text="", anchor="w", font=F(12),
                                      text_color=MUTED, justify="right")
        self.stage_lbl.grid(row=2, column=0, sticky="ew", padx=14)

        self.info_lbl = ctk.CTkLabel(card, text="", anchor="w", font=F(11),
                                     text_color=MUTED)
        self.info_lbl.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 6))

        self.log_box = make_textbox(card, activate_scrollbars=True, wrap="word",
                                    height=150)
        self.log_box.grid(row=4, column=0, sticky="nsew", padx=14, pady=(0, 4))
        self.log_box.configure(state="disabled")
        card.rowconfigure(4, weight=1)

        foot = ctk.CTkFrame(card, fg_color="transparent")
        foot.grid(row=5, column=0, sticky="ew", padx=14, pady=(0, 10))
        for text, cmd in ((t("ui.btn.copy_log"), self.copy_log),
                          (t("ui.btn.clear_log"), self.clear_log),
                          (t("ui.btn.save_log"), self.save_log)):
            ctk.CTkButton(foot, text=text, width=110, height=26, font=F(11),
                          fg_color="transparent", hover_color=("#ddd", "#333"),
                          border_width=1, command=cmd).pack(side="left", padx=(0, 6))

    # ---- logging -----------------------------------------------------------
    def _append_log(self, line):
        wrap_text(self.log_box, str(line) + "\n")

    def log(self, line):
        """UI-thread logging with a timestamp."""
        stamp = time.strftime("%H:%M:%S")
        self._append_log(f"[{stamp}] {line}")

    def logf(self, line):
        """Worker-thread logging (queued onto the Tk loop)."""
        self.pump.push("log", f"[{time.strftime('%H:%M:%S')}] {line}")

    def clear_log(self):
        try:
            self.log_box.configure(state="normal")
            self.log_box.delete("1.0", "end")
            self.log_box.configure(state="disabled")
        except Exception:
            pass

    def copy_log(self):
        inner = inner_text_widget(self.log_box)
        if inner is None:
            return
        try:
            selected = inner.get("sel.first", "sel.last")
        except Exception:
            selected = ""
        try:
            content = selected or inner.get("1.0", "end-1c")
            self.clipboard_clear()
            self.clipboard_append(content)
            self.log(t("ui.log.log_copied"))
        except Exception:
            pass

    def save_log(self):
        try:
            content = inner_text_widget(self.log_box).get("1.0", "end-1c")
        except Exception:
            content = ""
        if not content.strip():
            mb.showinfo(APP_NAME, t("ui.log.log_empty"), parent=self)
            return
        os.makedirs(LOG_DIR, exist_ok=True)
        path = os.path.join(LOG_DIR, f"arion-{time.strftime('%Y%m%d-%H%M%S')}.log")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            self.log(t("ui.log.log_saved", v1=path))
            open_in_file_manager(path)
        except Exception as exc:
            mb.showerror(APP_NAME, t("ui.err.log_save_failed", v1=exc), parent=self)

    # ---- progress rendering ------------------------------------------------
    def _apply_snapshot(self, snap):
        ov = float(snap.get("overall") or 0.0)
        try:
            self.overall_bar.set(max(0.0, min(1.0, ov / 100.0)))
            self.percent_lbl.configure(text=f"{ov:5.1f}%")
        except Exception:
            return

        label = (snap.get("label") or "").strip()
        if label:
            first, _, rest = label.partition("\n")
            try:
                self.status_lbl.configure(text=first)
                self.stage_lbl.configure(text=rest.strip())
            except Exception:
                pass

        info = [f"⏱ {fmt_duration(snap.get('elapsed') or 0)}"]
        if snap.get("eta") is not None:
            info.append(t("ui.info.remaining", v1=fmt_duration(snap['eta'])))
        if snap.get("speed"):
            info.append(f"🚀 {snap['speed']}")
        if snap.get("note"):
            info.append(f"🔑 {snap['note']}")
        try:
            self.info_lbl.configure(text="   ·   ".join(info))
        except Exception:
            pass

        # Log stage transitions; for downloads throttle to every ~10%.
        if label and label != self._last_label:
            is_transfer = label.startswith("📥")
            if (not is_transfer) or abs(ov - self._last_logged_pct) >= 10:
                self._last_label = label
                self._last_logged_pct = ov
                self.log("• " + label.replace("\n", " — "))

    def reset_progress(self, status=t("ui.status.idle_ready")):
        self._last_label = ""
        self._last_logged_pct = -100.0
        try:
            self.overall_bar.set(0)
            self.percent_lbl.configure(text="0.0%")
            self.status_lbl.configure(text=status)
            self.stage_lbl.configure(text="")
            self.info_lbl.configure(text="")
        except Exception:
            pass

    # ---- job plumbing ------------------------------------------------------
    def make_job(self):
        job = engine.Job(progress_cb=self._progress_cb(), log_cb=self._log_cb())
        job.running = True
        job.started = time.monotonic()
        self._job = job
        return job

    def _progress_cb(self):
        push = self.pump.push
        holder = {}

        def cb(stage_pct, label, overall=None, note=""):
            job = holder.get("job")
            if job is None:
                job = holder["job"] = self._job
            snap = job.snapshot() if job else {
                "overall": overall or stage_pct or 0, "label": label,
                "elapsed": 0, "eta": None, "speed": "", "note": note,
            }
            push("progress", snap)

        return cb

    def _log_cb(self):
        push = self.pump.push

        def cb(line):
            push("log", f"[{time.strftime('%H:%M:%S')}] {line}")

        return cb

    def start_worker(self, fn, on_done):
        """Run ``fn`` in a thread; deliver result/error on the Tk thread."""
        def run():
            try:
                result = fn()
            except engine.Cancelled:
                self.pump.push("call", self._on_cancelled)
            except Exception as exc:  # noqa: BLE001 - surfaced to the user
                message = str(exc) or exc.__class__.__name__
                self.pump.push("call", lambda: on_done(None, message))
            else:
                self.pump.push("call", lambda: on_done(result, None))

        threading.Thread(target=run, daemon=True).start()

    def _on_cancelled(self):
        self.set_running(False)
        self.log(t("ui.log.job_cancelled"))
        self.pump.push("progress", {
            "overall": self._job.overall if self._job else 0,
            "label": t("ui.status.cancelled"), "elapsed": 0, "eta": None,
            "speed": "", "note": "",
        })

    def set_running(self, running):
        try:
            self.start_btn.configure(state="disabled" if running else "normal")
            self.cancel_btn.configure(state="normal" if running else "disabled")
            self.start_btn.configure(text=t("ui.status.running") if running
                                     else self._start_text)
        except Exception:
            pass
        if not running and self._job:
            self._job.running = False

    def trigger_start(self):
        if self._job is not None and self._job.running:
            self.log(t("ui.err.job_running"))
            return
        try:
            self._start()
        except Exception as exc:
            mb.showerror(APP_NAME, t("ui.err.start_failed", v1=exc), parent=self)

    def cancel(self):
        if self._job is not None and self._job.running:
            self._job.cancel()
            self.log(t("ui.log.cancel_requested"))
        else:
            self.log(t("ui.err.no_job_running"))

    def focus_first(self):
        pass

    # ---- helpers -----------------------------------------------------------
    def _pick_out_dir(self, var, title=t("ui.label.output_dir")):
        path = fd.askdirectory(parent=self, initialdir=var.get() or HERE,
                               title=title)
        if path:
            var.set(path)
            self.app.settings["out_dir"] = path
            save_settings(self.app.settings)
            self.app.refresh_out_dirs()

    def _open_out_dir(self, var=None):
        path = (var.get() if var is not None else self.app.settings["out_dir"])
        path = (path or "").strip() or self.app.settings["out_dir"]
        if os.path.isdir(path):
            open_in_file_manager(path)
        else:
            mb.showwarning(APP_NAME, t("ui.err.folder_missing", v1=path), parent=self)


# =============================== Transcribe =================================

class TranscribeTab(Tab):
    _START_KEY = "ui.btn.start_transcribe"

    def __init__(self, master, app):
        super().__init__(master, app)
        self._build_control_card()
        self._progress_block(t("ui.status.transcribe_ready"))
        self._start_text = t(self._START_KEY)
        self._sync_deep()

    def _build_control_card(self):
        card = ctk.CTkFrame(self, corner_radius=12)
        card.grid(row=0, column=0, sticky="new", padx=2, pady=(0, 8))
        card.columnconfigure(0, weight=1)

        ctk.CTkLabel(card, text=t("ui.title.transcribe_tab"),
                     font=F(15, "bold"), anchor="w").grid(
            row=0, column=0, columnspan=3, sticky="ew", padx=12, pady=(10, 6))

        self.seg = ctk.CTkSegmentedButton(
            card, values=[t("ui.seg.local_file"), t("ui.seg.youtube_link")],
            command=self._switch_source, font=F(12))
        self.seg.set(t("ui.seg.local_file") if self.app.settings["transcribe_source"] == "file"
                     else t("ui.seg.youtube_link"))
        self.seg.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 8))

        # file row
        self.file_row = ctk.CTkFrame(card, fg_color="transparent")
        self.file_row.columnconfigure(0, weight=1)
        self.path_var = tk.StringVar(value=self.app.settings.get("last_file", ""))
        self.path_entry = make_entry(
            self.file_row, textvariable=self.path_var, on_open=self._pick_file,
            placeholder_text=t("ui.placeholder.media_path"))
        self.path_entry.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(self.file_row, text=t("ui.menu.choose_file"), width=110, font=F(12),
                      command=self._pick_file).grid(row=0, column=1, padx=(8, 0))
        self.path_entry.bind("<Return>", lambda _e: self.trigger_start())

        # url row
        self.url_row = ctk.CTkFrame(card, fg_color="transparent")
        self.url_row.columnconfigure(0, weight=1)
        self.url_var = tk.StringVar(value=self.app.settings.get("last_url", ""))
        self.url_entry = make_entry(
            self.url_row, textvariable=self.url_var,
            placeholder_text="https://www.youtube.com/watch?v=…")
        self.url_entry.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(self.url_row, text=t("ui.btn.estimate_size"), width=110, font=F(12),
                      command=self._check_url).grid(row=0, column=1, padx=(8, 0))
        self.url_entry.bind("<Return>", lambda _e: self.trigger_start())

        # options
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.grid(row=3, column=0, columnspan=3, sticky="ew", padx=12, pady=(2, 0))
        for i in range(4):
            row.columnconfigure(i, weight=1, uniform="ropt")
        for col, (text, values, attr) in enumerate([
                (t("ui.label.language"), label_list(engine.LANGUAGES), "lang_menu"),
                (t("ui.label.subtitle_style"), label_list(engine.SUBTITLE_STYLES), "style_menu"),
                (t("ui.label.output_format"), ["SRT", "TXT", "SRT + TXT"], "fmt_menu"),
                (t("ui.label.engine"), label_list(engine.PROVIDERS), "prov_menu")]):
            ctk.CTkLabel(row, text=text, anchor="w", font=F(12)).grid(
                row=0, column=col, sticky="ew", padx=(0 if col == 0 else 6, 0))
            menu = ctk.CTkOptionMenu(row, values=values, font=F(12),
                                     dropdown_font=F(12))
            menu.set(values[0])
            menu.grid(row=1, column=col, sticky="ew",
                      padx=(0 if col == 0 else 6, 0))
            setattr(self, attr, menu)
        self.prov_menu.configure(command=lambda _v: self._sync_deep())

        # output + deep + cookie
        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.grid(row=4, column=0, columnspan=3, sticky="ew", padx=12, pady=(8, 0))
        row2.columnconfigure(1, weight=1)
        ctk.CTkLabel(row2, text=t("ui.label.output_dir"), font=F(12)).grid(
            row=0, column=0, sticky="w", padx=(0, 6))
        self.out_var = tk.StringVar(value=self.app.settings["out_dir"])
        make_entry(row2, textvariable=self.out_var).grid(row=0, column=1, sticky="ew")
        ctk.CTkButton(row2, text="…", width=34, font=F(12),
                      command=lambda: self._pick_out_dir(self.out_var)
                      ).grid(row=0, column=2, padx=(6, 0))
        ctk.CTkButton(row2, text="📂", width=34, font=F(12),
                      command=lambda: self._open_out_dir(self.out_var)
                      ).grid(row=0, column=3, padx=(6, 0))

        row3 = ctk.CTkFrame(card, fg_color="transparent")
        row3.grid(row=5, column=0, columnspan=3, sticky="ew", padx=12, pady=(6, 0))
        row3.columnconfigure(1, weight=1)
        ctk.CTkLabel(row3, text=t("ui.label.cookies_optional"), font=F(12)).grid(
            row=0, column=0, sticky="w", padx=(0, 6))
        self.cookie_var = tk.StringVar(value=self.app.settings.get("cookies", ""))
        make_entry(row3, textvariable=self.cookie_var,
                   placeholder_text=t("ui.placeholder.cookies_limited")).grid(
            row=0, column=1, sticky="ew")
        ctk.CTkButton(row3, text="…", width=34, font=F(12),
                      command=self._pick_cookie).grid(row=0, column=2, padx=(6, 0))

        self.deep_var = tk.BooleanVar(value=False)
        self.deep_chk = ctk.CTkCheckBox(
            card, text=t("ui.check.deep_mode"),
            variable=self.deep_var, font=F(12), command=self._sync_deep)
        self.deep_chk.grid(row=6, column=0, columnspan=3, sticky="w",
                           padx=12, pady=(8, 0))

        act = ctk.CTkFrame(card, fg_color="transparent")
        act.grid(row=7, column=0, columnspan=3, sticky="ew", padx=12, pady=(10, 12))
        self.start_btn = ctk.CTkButton(act, text=self._start_text, height=38, width=190,
                                       font=F(13, "bold"), fg_color=ACCENT,
                                       hover_color=ACCENT_HOVER, command=self._start)
        self.start_btn.pack(side="right")
        self.cancel_btn = ctk.CTkButton(act, text=t("ui.btn.cancel"), height=38, width=90,
                                        font=F(12), fg_color=DANGER,
                                        hover_color=DANGER_HOVER,
                                        command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="right", padx=(0, 8))

        self._switch_source(t("ui.seg.local_file") if self.app.settings["transcribe_source"] == "file"
                            else t("ui.seg.youtube_link"))

    # ---- interactions ------------------------------------------------------
    def _switch_source(self, choice):
        val = "file" if choice.startswith("📁") else "url"
        self.app.settings["transcribe_source"] = val
        if val == "file":
            self.url_row.grid_forget()
            self.file_row.grid(row=2, column=0, columnspan=3, sticky="ew",
                               padx=12, pady=2)
        else:
            self.file_row.grid_forget()
            self.url_row.grid(row=2, column=0, columnspan=3, sticky="ew",
                              padx=12, pady=2)

    def _sync_deep(self, *_):
        uses_gemini = self.prov_menu.get() == t(engine.PROVIDERS[1][1])
        try:
            self.deep_chk.configure(state="normal" if uses_gemini else "disabled")
        except Exception:
            pass
        if not uses_gemini and self.deep_var.get():
            self.deep_var.set(False)
            self.log(t("ui.log.deep_needs_gemini"))

    def _pick_file(self):
        path = fd.askopenfilename(
            parent=self, title=t("ui.dialog.media_files"),
            filetypes=[("Media", "*.mp4 *.mkv *.mov *.avi *.webm *.mp3 *.wav "
                                  "*.m4a *.opus *.ogg *.aac *.flac"),
                       (t("ui.dialog.all_files"), "*.*")])
        if path:
            self.path_var.set(path)
            self.app.settings["last_file"] = path
            save_settings(self.app.settings)
            self.log(t("ui.log.file_selected", v1=os.path.basename(path)))

    def _pick_cookie(self):
        path = fd.askopenfilename(parent=self, initialdir=HERE,
                                  filetypes=[("cookies.txt", "*.txt"),
                                             (t("ui.dialog.all"), "*.*")])
        if path:
            self.cookie_var.set(path)
            self.app.settings["cookies"] = path
            save_settings(self.app.settings)
            self.log(t("ui.log.cookies_selected", v1=path))

    def _check_url(self):
        url = self.url_var.get().strip()
        if not url:
            mb.showwarning(APP_NAME, t("ui.err.need_youtube_link"), parent=self)
            return
        self.status_lbl.configure(text=t("ui.status.estimating_duration"))
        self.percent_lbl.configure(text="…")
        cookies = self.cookie_var.get().strip()

        def work():
            return engine.probe_sizes(url, cookies=cookies)

        def done(result, err):
            if err:
                self.status_lbl.configure(text=t("ui.status.estimate_failed"))
                self.percent_lbl.configure(text="0.0%")
                self.log(t("ui.err.estimate_failed", v1=err))
                return
            text = self._format_sizes(result)
            self.status_lbl.configure(text=text or t("ui.label.nothing_found"))
            self.percent_lbl.configure(text="0.0%")
            self.log(f"📊 {text}")

        self.start_worker(work, done)

    @staticmethod
    def _format_sizes(result):
        result = result or {}
        video = result.get("video") or {}
        parts = [f"{t(engine.DL_VIDEO_LABELS.get(k, k))}: {v}MB"
                 for k, v in video.items() if v]
        dur = result.get("duration") or 0
        head = f"⏱ {fmt_duration(dur)}  |  " if dur else ""
        return head + ("  |  ".join(parts[:4]) if parts else "")

    # ---- start/cancel ------------------------------------------------------
    def _start(self):
        out_dir = self.out_var.get().strip() or self.app.settings["out_dir"]
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as exc:
            mb.showerror(APP_NAME, t("ui.err.out_dir_create_failed", v1=exc),
                         parent=self)
            return
        self.app.settings["out_dir"] = out_dir

        source = self.app.settings.get("transcribe_source", "file")
        if source == "file":
            path = self.path_var.get().strip()
            if not path or not os.path.exists(path):
                mb.showerror(APP_NAME, t("ui.err.input_missing"), parent=self)
                return
            self.app.settings["last_file"] = path
            payload = ("file", path)
        else:
            url = self.url_var.get().strip()
            if "youtube.com" not in url and "youtu.be" not in url:
                mb.showerror(APP_NAME, t("ui.err.bad_youtube_link"), parent=self)
                return
            self.app.settings["last_url"] = url
            payload = ("url", url)

        lang_code = label_map(engine.LANGUAGES)[self.lang_menu.get()]
        style_code = label_map(engine.SUBTITLE_STYLES)[self.style_menu.get()]
        fmt = {"SRT": "srt", "TXT": "txt", "SRT + TXT": "both"}[self.fmt_menu.get()]
        prov = label_map(engine.PROVIDERS)[self.prov_menu.get()]
        deep = bool(self.deep_var.get()) and prov == "gemini"
        cookies = self.cookie_var.get().strip()

        groq = engine.groq_keys(self.app.settings.get("groq_key"))
        gem = engine.gemini_keys(self.app.settings.get("gemini_key"))
        if prov == "groq" and not groq:
            mb.showerror(APP_NAME, t("ui.err.need_groq_key"),
                         parent=self)
            return
        if prov == "gemini" and not gem:
            mb.showerror(APP_NAME, t("ui.err.need_gemini_key"),
                         parent=self)
            return
        if deep and not gem:
            mb.showerror(APP_NAME, t("ui.err.deep_needs_gemini_key"), parent=self)
            return

        save_settings(self.app.settings)
        job = self.make_job()
        self.set_running(True)
        self.reset_progress(t("ui.status.starting"))
        self.log(t("ui.log.job_started", v1=source, v2=prov, v3=lang_code, v4=fmt, v5=t("ui.value.yes") if deep else t("ui.value.no")))

        def work():
            if payload[0] == "file":
                return engine.transcribe_file(
                    job, groq, payload[1], out_dir, language=lang_code,
                    output_format=fmt, style=style_code, provider=prov,
                    deep=deep, refine_keys=gem, cookies=cookies)
            keys = gem if prov == "gemini" else groq
            return engine.transcribe_youtube(
                job, keys, payload[1], out_dir, language=lang_code,
                output_format=fmt, style=style_code, provider=prov,
                deep=deep, refine_keys=gem, cookies=cookies)

        def done(result, err):
            self.set_running(False)
            if err:
                self.status_lbl.configure(text=t("ui.status.failed"))
                self.log(f"❌ {err}")
                mb.showerror(APP_NAME, str(err), parent=self)
                return
            paths = [p for p in (result or {}).values() if p]
            names = ", ".join(os.path.basename(p) for p in paths)
            self.status_lbl.configure(text=t("ui.status.done", v1=names))
            self.percent_lbl.configure(text="100.0%")
            self.overall_bar.set(1)
            self.log(t("ui.log.files_in", v1=out_dir))
            mb.showinfo(APP_NAME,
                        t("ui.dialog.transcribe_done", v1=names, v2=out_dir),
                        parent=self)

        self.start_worker(work, done)

    def focus_first(self):
        try:
            (self.path_entry if self.app.settings.get("transcribe_source") == "file"
             else self.url_entry).focus_set()
        except Exception:
            pass


# =============================== Download ===================================

class DownloadTab(Tab):
    _START_KEY = "ui.btn.start_download"
    SUB_LANG_KEYS = ["ui.lang.original", "ui.lang.fa", "ui.lang.en", "ui.lang.de",
                     "ui.lang.ar", "ui.lang.tr", "ui.lang.ru", "ui.lang.fr", "ui.lang.es"]
    SUB_LANG_CODES = [None, "fa", "en", "de", "ar", "tr", "ru", "fr", "es"]

    def __init__(self, master, app):
        super().__init__(master, app)
        self.kind = app.settings.get("download_kind", "video")
        self._kind_default = None
        self._build_control_card()
        self._progress_block(t("ui.status.download_ready"))
        self._start_text = t(self._START_KEY)

    def _build_control_card(self):
        card = ctk.CTkFrame(self, corner_radius=12)
        card.grid(row=0, column=0, sticky="new", padx=2, pady=(0, 8))
        card.columnconfigure(0, weight=1)

        ctk.CTkLabel(card, text=t("ui.title.download_tab"),
                     font=F(15, "bold"), anchor="w").grid(
            row=0, column=0, columnspan=3, sticky="ew", padx=12, pady=(10, 6))

        self.url_var = tk.StringVar(value=self.app.settings.get("last_url", ""))
        self.url_entry = make_entry(card, textvariable=self.url_var,
                                    placeholder_text=t("ui.placeholder.youtube_link"))
        self.url_entry.grid(row=1, column=0, columnspan=3, sticky="ew",
                            padx=12, pady=(0, 8))
        self.url_entry.bind("<Return>", lambda _e: self.trigger_start())

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.grid(row=2, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 8))
        for i in range(4):
            row.columnconfigure(i, weight=1, uniform="kct")
        self.kind_btns = {}
        for i, (code, lbl) in enumerate([("video", t("ui.kind.video")), ("audio", t("ui.kind.audio")),
                                         ("subs", t("ui.kind.subs")), ("txt", "📄 TXT")]):
            btn = ctk.CTkButton(row, text=lbl, height=30, corner_radius=8, font=F(12),
                                command=lambda c=code: self._set_kind(c))
            btn.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0))
            if self._kind_default is None:
                self._kind_default = btn.cget("fg_color")
            self.kind_btns[code] = btn

        qual_row = ctk.CTkFrame(card, fg_color="transparent")
        qual_row.grid(row=3, column=0, columnspan=3, sticky="ew", padx=12)
        qual_row.columnconfigure(0, weight=1)
        ctk.CTkLabel(qual_row, text=t("ui.label.quality_format_lang"), anchor="w",
                     font=F(12)).grid(row=0, column=0, sticky="ew")
        self.quality_menu = ctk.CTkOptionMenu(
            qual_row, values=label_list(engine.DL_VIDEO_QUALITIES),
            font=F(12), dropdown_font=F(12), command=self._quality_changed)
        self.quality_menu.set(t(engine.DL_VIDEO_QUALITIES[0][1]))
        self.quality_menu.grid(row=1, column=0, columnspan=2, sticky="ew")

        size_row = ctk.CTkFrame(card, fg_color="transparent")
        size_row.grid(row=4, column=0, columnspan=3, sticky="ew", padx=12, pady=(6, 0))
        size_row.columnconfigure(0, weight=1)
        self.size_label = ctk.CTkLabel(size_row, text="", anchor="w", font=F(11),
                                       text_color=MUTED)
        self.size_label.grid(row=0, column=0, sticky="ew")
        self.probe_btn = ctk.CTkButton(size_row, text=t("ui.btn.estimate_size"), width=110,
                                       font=F(12), command=self._probe)
        self.probe_btn.grid(row=0, column=1, padx=(6, 0))

        ck = ctk.CTkFrame(card, fg_color="transparent")
        ck.grid(row=5, column=0, columnspan=3, sticky="ew", padx=12, pady=(6, 0))
        ck.columnconfigure(1, weight=1)
        ctk.CTkLabel(ck, text=t("ui.label.cookies"), font=F(12)).grid(row=0, column=0,
                                                          sticky="w", padx=(0, 6))
        self.cookie_var = tk.StringVar(value=self.app.settings.get("cookies", ""))
        make_entry(ck, textvariable=self.cookie_var,
                   placeholder_text=t("ui.placeholder.cookies_age")).grid(
            row=0, column=1, sticky="ew")
        ctk.CTkButton(ck, text="…", width=34, font=F(12),
                      command=self._pick_cookie).grid(row=0, column=2, padx=(6, 0))

        out = ctk.CTkFrame(card, fg_color="transparent")
        out.grid(row=6, column=0, columnspan=3, sticky="ew", padx=12, pady=(6, 0))
        out.columnconfigure(1, weight=1)
        ctk.CTkLabel(out, text=t("ui.label.save_folder"), font=F(12)).grid(row=0, column=0,
                                                               sticky="w", padx=(0, 6))
        self.out_var = tk.StringVar(value=self.app.settings["out_dir"])
        make_entry(out, textvariable=self.out_var).grid(row=0, column=1, sticky="ew")
        ctk.CTkButton(out, text="…", width=34, font=F(12),
                      command=lambda: self._pick_out_dir(self.out_var,
                                                         t("ui.label.save_folder"))
                      ).grid(row=0, column=2, padx=(6, 0))
        ctk.CTkButton(out, text="📂", width=34, font=F(12),
                      command=lambda: self._open_out_dir(self.out_var)
                      ).grid(row=0, column=3, padx=(6, 0))

        ctk.CTkButton(card, text=t("ui.btn.proxy_settings"), width=200, height=26, font=F(11),
                      fg_color="#555", hover_color="#666",
                      command=self.app.show_proxy_dialog).grid(
            row=7, column=0, columnspan=3, sticky="w", padx=12, pady=(8, 0))

        act = ctk.CTkFrame(card, fg_color="transparent")
        act.grid(row=8, column=0, columnspan=3, sticky="ew", padx=12, pady=(10, 12))
        self.start_btn = ctk.CTkButton(act, text=self._start_text, height=38, width=150,
                                       font=F(13, "bold"), fg_color=ACCENT,
                                       hover_color=ACCENT_HOVER, command=self._start)
        self.start_btn.pack(side="right")
        self.cancel_btn = ctk.CTkButton(act, text=t("ui.btn.cancel"), height=38, width=90,
                                        font=F(12), fg_color=DANGER,
                                        hover_color=DANGER_HOVER,
                                        command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="right", padx=(0, 8))

        self._set_kind(self.kind)

    # ---- interactions ------------------------------------------------------
    def _sub_langs(self):
        """Subtitle language labels for the current UI language."""
        return [t(key) for key in self.SUB_LANG_KEYS]

    def _sub_lang_code(self, label):
        for key, code in zip(self.SUB_LANG_KEYS, self.SUB_LANG_CODES):
            if t(key) == label:
                return code
        return None

    def _set_kind(self, code):
        self.kind = code
        self.app.settings["download_kind"] = code
        for c, b in self.kind_btns.items():
            b.configure(fg_color=ACCENT if c == code else self._kind_default)
        menu = self.quality_menu
        if code == "video":
            menu.configure(values=label_list(engine.DL_VIDEO_QUALITIES))
            menu.set(t(engine.DL_VIDEO_QUALITIES[0][1]))
            self.probe_btn.configure(state="normal")
            self.size_label.configure(
                text=t("ui.hint.choose_quality"))
        elif code == "audio":
            menu.configure(values=label_list(engine.DL_AUDIO_QUALITIES))
            menu.set(t(engine.DL_AUDIO_QUALITIES[0][1]))
            self.probe_btn.configure(state="normal")
            self.size_label.configure(text=t("ui.hint.choose_audio_format"))
        elif code == "subs":
            menu.configure(values=self._sub_langs())
            menu.set(self._sub_langs()[0])
            self.probe_btn.configure(state="disabled")
            self.size_label.configure(
                text=t("ui.hint.subs_available"))
        else:
            menu.configure(values=["—"])
            menu.set("—")
            self.probe_btn.configure(state="disabled")
            self.size_label.configure(text=t("ui.hint.info_txt"))

    def _quality_changed(self, _value):
        pass

    def _pick_cookie(self):
        path = fd.askopenfilename(parent=self, initialdir=HERE,
                                  filetypes=[("cookies.txt", "*.txt"),
                                             (t("ui.dialog.all"), "*.*")])
        if path:
            self.cookie_var.set(path)
            self.app.settings["cookies"] = path
            save_settings(self.app.settings)
            self.log(t("ui.log.cookies_selected", v1=path))

    def _probe(self):
        url = self.url_var.get().strip()
        if "youtube.com" not in url and "youtu.be" not in url:
            mb.showwarning(APP_NAME, t("ui.err.need_valid_link"), parent=self)
            return
        self.size_label.configure(text=t("ui.status.estimating"))
        cookies = self.cookie_var.get().strip()
        kind = self.kind

        def work():
            return engine.probe_sizes(url, cookies=cookies)

        def done(result, err):
            if err:
                self.size_label.configure(text=t("ui.status.estimate_failed_short"))
                self.log(t("ui.err.estimate_failed", v1=err))
                return
            result = result or {}
            if kind == "video":
                video = result.get("video") or {}
                parts = [f"{t(engine.DL_VIDEO_LABELS.get(k, k))}: {v}MB"
                         for k, v in video.items() if v]
                text = "  |  ".join(parts[:5]) or t("ui.label.nothing_found")
            else:
                audio = result.get("audio") or {}
                parts = [f"{t(engine.DL_AUDIO_LABELS.get(k, k))}: {v}MB"
                         for k, v in audio.items() if v]
                text = "  |  ".join(parts) or t("ui.label.nothing_found")
            dur = result.get("duration") or 0
            if dur:
                text = f"⏱ {fmt_duration(dur)}  |  " + text
            self.size_label.configure(text=text)
            self.log(t("ui.log.size_estimate", v1=text))

        self.start_worker(work, done)

    # ---- start/cancel ------------------------------------------------------
    def _start(self):
        url = self.url_var.get().strip()
        if "youtube.com" not in url and "youtu.be" not in url:
            mb.showerror(APP_NAME, t("ui.err.bad_youtube_link"), parent=self)
            return
        out_dir = self.out_var.get().strip() or self.app.settings["out_dir"]
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as exc:
            mb.showerror(APP_NAME, t("ui.err.save_dir_create_failed", v1=exc), parent=self)
            return
        self.app.settings["out_dir"] = out_dir
        self.app.settings["last_url"] = url

        cookies = self.cookie_var.get().strip()
        self.app.settings["cookies"] = cookies
        kind = self.kind
        choice = self.quality_menu.get()

        video_map = label_map(engine.DL_VIDEO_QUALITIES)
        audio_map = label_map(engine.DL_AUDIO_QUALITIES)
        lang_map = {t(key): code
                    for key, code in zip(self.SUB_LANG_KEYS, self.SUB_LANG_CODES)}
        quality = video_map.get(choice) or audio_map.get(choice) or "best"

        save_settings(self.app.settings)
        job = self.make_job()
        self.set_running(True)
        self.reset_progress(t("ui.status.download_starting"))
        self.log(t("ui.log.download_started", v1=kind, v2=choice))

        def work():
            if kind == "subs":
                return engine.download_subtitles(job, url, out_dir,
                                                 lang=lang_map.get(choice),
                                                 cookies=cookies)
            if kind == "txt":
                return engine.download_info_txt(job, url, out_dir, cookies=cookies)
            return engine.download_media(job, url, out_dir, quality=quality,
                                         cookies=cookies)

        def done(result, err):
            self.set_running(False)
            if err:
                self.status_lbl.configure(text=t("ui.status.download_failed"))
                self.log(f"❌ {err}")
                mb.showerror(APP_NAME, str(err), parent=self)
                return
            self.overall_bar.set(1)
            self.percent_lbl.configure(text="100.0%")
            if kind == "subs" and isinstance(result, tuple) and len(result) == 4:
                path, target, sub_kind, title = result
                self.status_lbl.configure(
                    text=t("ui.log.subtitle_saved", v1=target, v2=os.path.basename(path)))
                self.log(t("ui.log.subtitle_titled", v1=title, v2=target, v3=sub_kind, v4=path))
                open_in_file_manager(path)
                return
            if kind == "txt" and isinstance(result, tuple) and len(result) == 2:
                path, title = result
                self.status_lbl.configure(text=f"✅ TXT: {os.path.basename(path)}")
                self.log(t("ui.log.info_saved", v1=title, v2=path))
                open_in_file_manager(path)
                return
            self.status_lbl.configure(text=f"✅ {os.path.basename(result)}")
            self.log(t("ui.log.downloaded", v1=result))
            open_in_file_manager(result)

        self.start_worker(work, done)

    def focus_first(self):
        try:
            self.url_entry.focus_set()
        except Exception:
            pass


# =============================== Translate ==================================

class TranslateTab(Tab):
    _START_KEY = "ui.btn.start_translate"

    def __init__(self, master, app):
        super().__init__(master, app)
        self._build_control_card()
        self._progress_block(t("ui.status.translate_ready"))
        self._start_text = t(self._START_KEY)

    def _build_control_card(self):
        card = ctk.CTkFrame(self, corner_radius=12)
        card.grid(row=0, column=0, sticky="new", padx=2, pady=(0, 8))
        card.columnconfigure(0, weight=1)

        ctk.CTkLabel(card, text=t("ui.title.translate_tab"), font=F(15, "bold"),
                     anchor="w").grid(row=0, column=0, columnspan=3, sticky="ew",
                                      padx=12, pady=(10, 6))

        self.srt_var = tk.StringVar(value=self.app.settings.get("last_srt", ""))
        fr = ctk.CTkFrame(card, fg_color="transparent")
        fr.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 8))
        fr.columnconfigure(0, weight=1)
        self.srt_entry = make_entry(fr, textvariable=self.srt_var,
                                    on_open=self._pick,
                                    placeholder_text=t("ui.placeholder.srt_path"))
        self.srt_entry.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(fr, text=t("ui.menu.choose_file"), width=110, font=F(12),
                      command=self._pick).grid(row=0, column=1, padx=(8, 0))
        self.srt_entry.bind("<Return>", lambda _e: self.trigger_start())

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.grid(row=2, column=0, columnspan=3, sticky="ew", padx=12)
        for i in range(2):
            row.columnconfigure(i, weight=1, uniform="topt")
        ctk.CTkLabel(row, text=t("ui.label.translate_to"), anchor="w", font=F(12)).grid(
            row=0, column=0, sticky="ew")
        self.lang_menu = ctk.CTkOptionMenu(
            row, values=label_list(engine.TRANSLATE_LANGUAGES),
            font=F(12), dropdown_font=F(12))
        self.lang_menu.set(t(engine.TRANSLATE_LANGUAGES[0][1]))
        self.lang_menu.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkLabel(row, text=t("ui.label.translate_style"), anchor="w", font=F(12)).grid(
            row=0, column=1, sticky="ew")
        self.style_menu = ctk.CTkOptionMenu(
            row, values=label_list(engine.TRANSLATE_STYLES),
            font=F(12), dropdown_font=F(12))
        self.style_menu.set(t(engine.TRANSLATE_STYLES[0][1]))
        self.style_menu.grid(row=1, column=1, sticky="ew", padx=(6, 0))

        out = ctk.CTkFrame(card, fg_color="transparent")
        out.grid(row=3, column=0, columnspan=3, sticky="ew", padx=12, pady=(8, 0))
        out.columnconfigure(1, weight=1)
        ctk.CTkLabel(out, text=t("ui.label.output_dir"), font=F(12)).grid(
            row=0, column=0, sticky="w", padx=(0, 6))
        self.out_var = tk.StringVar(value=self.app.settings["out_dir"])
        make_entry(out, textvariable=self.out_var).grid(row=0, column=1, sticky="ew")
        ctk.CTkButton(out, text="…", width=34, font=F(12),
                      command=lambda: self._pick_out_dir(self.out_var)
                      ).grid(row=0, column=2, padx=(6, 0))
        ctk.CTkButton(out, text="📂", width=34, font=F(12),
                      command=lambda: self._open_out_dir(self.out_var)
                      ).grid(row=0, column=3, padx=(6, 0))

        act = ctk.CTkFrame(card, fg_color="transparent")
        act.grid(row=4, column=0, columnspan=3, sticky="ew", padx=12, pady=(10, 12))
        self.start_btn = ctk.CTkButton(act, text=self._start_text, height=38, width=130,
                                       font=F(13, "bold"), fg_color=ACCENT,
                                       hover_color=ACCENT_HOVER, command=self._start)
        self.start_btn.pack(side="right")
        self.cancel_btn = ctk.CTkButton(act, text=t("ui.btn.cancel"), height=38, width=90,
                                        font=F(12), fg_color=DANGER,
                                        hover_color=DANGER_HOVER,
                                        command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="right", padx=(0, 8))

    def _pick(self):
        path = fd.askopenfilename(parent=self, filetypes=[("SRT", "*.srt"),
                                                          (t("ui.dialog.all"), "*.*")])
        if path:
            self.srt_var.set(path)
            self.app.settings["last_srt"] = path
            save_settings(self.app.settings)
            self._describe(path)

    def _describe(self, path):
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                text = f.read()
            count = text.count("-->")
            self.log(t("ui.log.srt_loaded", v1=os.path.basename(path), v2=count))
        except Exception as exc:
            self.log(t("ui.err.srt_read_failed", v1=exc))

    def _start(self):
        srt_path = self.srt_var.get().strip()
        if not srt_path or not os.path.exists(srt_path):
            mb.showerror(APP_NAME, t("ui.err.srt_missing"), parent=self)
            return
        out_dir = self.out_var.get().strip() or self.app.settings["out_dir"]
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as exc:
            mb.showerror(APP_NAME, t("ui.err.out_dir_create_failed", v1=exc), parent=self)
            return
        self.app.settings["out_dir"] = out_dir
        self.app.settings["last_srt"] = srt_path

        lang_label = self.lang_menu.get()
        lang_code = next(c for c, lbl, _ in engine.TRANSLATE_LANGUAGES
                         if t(lbl) == lang_label)
        human = next(h for _, lbl, h in engine.TRANSLATE_LANGUAGES
                     if t(lbl) == lang_label)
        style = label_map(engine.TRANSLATE_STYLES)[
            self.style_menu.get()]
        keys = engine.gemini_keys(self.app.settings.get("gemini_key"))
        if not keys:
            mb.showerror(APP_NAME, t("ui.err.need_gemini_key_settings"),
                         parent=self)
            return

        save_settings(self.app.settings)
        job = self.make_job()
        self.set_running(True)
        self.reset_progress(t("ui.status.translate_starting"))
        self.log(t("ui.log.translate_started", v1=human, v2=style, v3=len(keys)))

        def work():
            return engine.translate_srt_file(
                job, srt_path, out_dir, target_language=human, style=style,
                lang_code=lang_code, gemini_keys_list=keys)

        def done(result, err):
            self.set_running(False)
            if err:
                self.status_lbl.configure(text=t("ui.status.translate_failed"))
                self.log(f"❌ {err}")
                mb.showerror(APP_NAME, str(err), parent=self)
                return
            self.overall_bar.set(1)
            self.percent_lbl.configure(text="100.0%")
            self.status_lbl.configure(text=f"✅ {os.path.basename(result)}")
            self.log(t("ui.log.translated", v1=result))
            mb.showinfo(APP_NAME, t("ui.dialog.translate_done", v1=result), parent=self)

        self.start_worker(work, done)

    def focus_first(self):
        try:
            self.srt_entry.focus_set()
        except Exception:
            pass


# =============================== Settings ===================================

class SettingsTab(Tab):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        body = ctk.CTkScrollableFrame(self, corner_radius=12)
        body.grid(row=0, column=0, sticky="nsew", padx=2, pady=(0, 8))
        body.columnconfigure(1, weight=1)
        self.body = body

        ctk.CTkLabel(body, text=t("ui.tab.settings"), font=F(15, "bold"), anchor="w").grid(
            row=0, column=0, columnspan=3, sticky="ew", padx=12, pady=(10, 8))

        # keys
        ctk.CTkLabel(body, text=t("ui.label.groq_key"), font=F(12)).grid(
            row=1, column=0, sticky="w", padx=12, pady=3)
        self.groq_var = tk.StringVar(value="•" * 8 if app.settings.get("groq_key") else "")
        self.groq_entry = make_entry(
            body, textvariable=self.groq_var, show="•",
            placeholder_text=t("ui.placeholder.groq_key"))
        self.groq_entry.grid(row=1, column=1, sticky="ew", padx=6, pady=3)
        ctk.CTkButton(body, text=t("ui.btn.test"), width=52, height=26, font=F(11),
                      command=lambda: self._test_key("groq", self.groq_var.get())
                      ).grid(row=1, column=2, padx=(0, 12), pady=3)

        ctk.CTkLabel(body, text=t("ui.label.gemini_key"), font=F(12)).grid(
            row=2, column=0, sticky="w", padx=12, pady=3)
        self.gem_var = tk.StringVar(value="•" * 8 if app.settings.get("gemini_key") else "")
        self.gem_entry = make_entry(
            body, textvariable=self.gem_var, show="•",
            placeholder_text=t("ui.placeholder.gemini_key"))
        self.gem_entry.grid(row=2, column=1, sticky="ew", padx=6, pady=3)
        ctk.CTkButton(body, text=t("ui.btn.test"), width=52, height=26, font=F(11),
                      command=lambda: self._test_key("gemini", self.gem_var.get())
                      ).grid(row=2, column=2, padx=(0, 12), pady=3)

        self.save_keys_var = tk.BooleanVar(value=app.settings.get("save_keys", False))
        ctk.CTkCheckBox(body, text=t("ui.check.save_key_pool"),
                        variable=self.save_keys_var, font=F(12)).grid(
            row=3, column=0, columnspan=3, sticky="w", padx=12, pady=(6, 2))

        ctk.CTkLabel(body, text=t("ui.label.default_out_dir"), font=F(12)).grid(
            row=4, column=0, sticky="w", padx=12, pady=3)
        self.out_var = tk.StringVar(value=app.settings["out_dir"])
        make_entry(body, textvariable=self.out_var).grid(
            row=4, column=1, sticky="ew", padx=6, pady=3)
        ctk.CTkButton(body, text="…", width=34, font=F(12),
                      command=lambda: self._pick_out_dir(self.out_var,
                                                         t("ui.label.output_dir"))
                      ).grid(row=4, column=2, padx=(0, 12), pady=3)

        ctk.CTkLabel(body, text=t("ui.label.cookies_file"), font=F(12)).grid(
            row=5, column=0, sticky="w", padx=12, pady=3)
        self.cookie_var = tk.StringVar(value=app.settings.get("cookies", ""))
        make_entry(body, textvariable=self.cookie_var,
                   placeholder_text="cookies.txt").grid(
            row=5, column=1, sticky="ew", padx=6, pady=3)
        ctk.CTkButton(body, text="…", width=34, font=F(12),
                      command=self._pick_cookie).grid(
            row=5, column=2, padx=(0, 12), pady=3)

        ctk.CTkLabel(body, text=t("ui.label.youtube_proxy"), font=F(12)).grid(
            row=6, column=0, sticky="w", padx=12, pady=3)
        self.proxy_var = tk.StringVar(value=app.settings.get("proxy", ""))
        make_entry(body, textvariable=self.proxy_var,
                   placeholder_text=t("ui.placeholder.proxy")).grid(
            row=6, column=1, columnspan=2, sticky="ew", padx=(6, 12), pady=3)

        ctk.CTkButton(body, text=t("ui.btn.save_settings"), height=38, font=F(13, "bold"),
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._save).grid(
            row=7, column=0, columnspan=3, sticky="ew", padx=12, pady=(12, 8))

        # environment status
        env = ctk.CTkFrame(body, corner_radius=10)
        env.grid(row=8, column=0, columnspan=3, sticky="ew", padx=12, pady=(4, 8))
        env.columnconfigure(0, weight=1)
        self.env_lbl = ctk.CTkLabel(env, text=t("ui.status.checking_env"), anchor="w",
                                    justify="right", font=F(11), text_color=MUTED)
        self.env_lbl.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        ctk.CTkButton(env, text=t("ui.btn.recheck"), width=110, height=26, font=F(11),
                      command=self.refresh_env).grid(row=1, column=0, sticky="w",
                                                     padx=10, pady=(0, 8))

        # links
        guide = ctk.CTkFrame(body, corner_radius=10)
        guide.grid(row=9, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 8))
        guide.columnconfigure(0, weight=1)
        ctk.CTkLabel(guide, text=t("ui.label.useful_links"), font=F(13, "bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=10,
                                      pady=(8, 2))
        for i, (text, url) in enumerate([
            (t("ui.link.groq_key"), "https://console.groq.com/keys"),
            (t("ui.link.gemini_key"),
             "https://aistudio.google.com/apikey"),
            (t("ui.link.cookies_extension"),
             "https://chromewebstore.google.com/detail/get-cookiestxt-locally/"
             "cclelndahbckbenkjhflpdbgdldlbecc"),
            (t("ui.link.customtkinter"),
             "https://github.com/TomSchimansky/CustomTkinter"),
        ]):
            ctk.CTkButton(guide, text=text, height=28, anchor="w", font=F(11),
                          fg_color="transparent", hover_color=("#ddd", "#333"),
                          text_color=("#1f6feb", "#8ab4f8"),
                          command=lambda u=url: webbrowser.open(u)).grid(
                row=1 + i, column=0, sticky="ew", padx=10, pady=1)

        # log for feedback (so self.log works here too)
        self.log_box = make_textbox(body, height=110, wrap="word")
        self.log_box.grid(row=10, column=0, columnspan=3, sticky="ew",
                          padx=12, pady=(0, 10))
        self.log_box.configure(state="disabled")

        # inert buttons so set_running() never explodes here
        self.start_btn = ctk.CTkButton(self, width=0, height=0, text="")
        self.cancel_btn = ctk.CTkButton(self, width=0, height=0, text="")
        self.start_btn.grid_remove()
        self.cancel_btn.grid_remove()
        self._start_text = ""

        self.refresh_env()

    # ---- actions -----------------------------------------------------------
    def refresh_env(self):
        try:
            status = engine.environment_status()
        except Exception as exc:
            self.env_lbl.configure(text=t("ui.err.env_check_failed", v1=exc))
            return
        ffmpeg = "✅ ffmpeg" if status["ffmpeg"] else t("ui.status.ffmpeg_missing")
        ytdlp = "✅ yt-dlp" if status["ytdlp"] else t("ui.status.ytdlp_missing")
        text = (f"{ffmpeg}   ·   {ytdlp}   ·   "
                f"🔑 Groq: {status['keys_groq']}   ·   "
                f"🔑 Gemini: {status['keys_gemini']}")
        self.env_lbl.configure(text=text)
        if not status["ffmpeg"]:
            self.log(t("ui.warn.ffmpeg_not_on_path"))

    def _pick_cookie(self):
        path = fd.askopenfilename(parent=self, initialdir=HERE,
                                  filetypes=[("cookies.txt", "*.txt"),
                                             (t("ui.dialog.all"), "*.*")])
        if path:
            self.cookie_var.set(path)

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
            for provider, key in (("groq", s.get("groq_key")),
                                  ("gemini", s.get("gemini_key"))):
                if not key:
                    continue
                try:
                    added, total = engine.save_key(provider, key)
                    self.log(t("ui.log.key_pool", v1=provider, v2=total)
                             + (t("ui.log.key_added") if added else ""))
                except Exception as exc:
                    self.log(t("ui.err.key_save_failed", v1=provider, v2=exc))
        out_dir = self.out_var.get().strip()
        if out_dir:
            s["out_dir"] = out_dir
            try:
                os.makedirs(out_dir, exist_ok=True)
            except Exception as exc:
                mb.showerror(APP_NAME, t("ui.err.out_dir_create_failed", v1=exc),
                             parent=self)
        s["cookies"] = self.cookie_var.get().strip()
        s["proxy"] = self.proxy_var.get().strip()
        self.app.apply_proxy(s["proxy"])
        save_settings(s)
        self.app.refresh_out_dirs()
        self.refresh_env()
        self.log(t("ui.log.settings_saved"))
        mb.showinfo(APP_NAME, t("ui.status.settings_saved"), parent=self)

    def _test_key(self, provider, key):
        key = (key or "").strip()
        if key.startswith("•"):
            key = self.app.settings.get(f"{provider}_key", "")
        if not key:
            mb.showwarning(APP_NAME, t("ui.err.need_key_first"), parent=self)
            return
        self.log(t("ui.log.testing_key", v1=provider))

        def work():
            return engine.test_api_key(provider, key)

        def done(result, err):
            if err:
                self.log(t("ui.err.test_failed", v1=err))
                return
            ok, message = result
            self.log(message)
            if not ok:
                mb.showwarning(APP_NAME, message, parent=self)

        self.start_worker(work, done)

    def focus_first(self):
        try:
            self.groq_entry.focus_set()
        except Exception:
            pass


# =============================== App ========================================

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        # Settings first: the saved (or default English) language decides which
        # font families are acceptable and what every widget says.
        global UI_FAMILY
        self.settings = load_settings()
        i18n.set_language(self.settings.get("language", i18n.DEFAULT_LANGUAGE))
        UI_FAMILY = choose_font_family(self)
        self.title(f"{APP_NAME} v{VERSION}")
        self.minsize(MIN_WIDTH, MIN_HEIGHT)
        self._restore_geometry()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        apply_tk_default_fonts(self)
        self.apply_proxy(self.settings.get("proxy", ""))
        self._closing = False
        self._after_ids = []
        self.sidebar = None
        self.content = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_ui()
        self._schedule(80, self._restore_geometry)
        self._schedule(300, self._startup_checks)

    def _build_ui(self):
        self._build_sidebar()
        self._build_content()
        self._bind_shortcuts()
        current = getattr(self, "current", None)
        self.show(current if current in self.tabs else TAB_ORDER[0])
        self._apply_scale(float(self.settings.get("scale", 1.0)))

    def set_language(self, code):
        """Switch the UI language and rebuild every widget in place."""
        code = i18n.set_language(code)
        if code == self.settings.get("language"):
            return code
        for tab in getattr(self, "tabs", {}).values():
            if getattr(tab, "_job", None) is not None and tab._job.running:
                mb.showwarning(APP_NAME, t("ui.err.language_job_running"),
                               parent=self)
                return self.settings.get("language", i18n.DEFAULT_LANGUAGE)
        self.settings["language"] = code
        save_settings(dict(self.settings))
        self.rebuild_ui()
        return code

    def rebuild_ui(self):
        """Recreate sidebar + tabs (used when the language changes)."""
        global UI_FAMILY
        current = getattr(self, "current", TAB_ORDER[0])
        for tab in getattr(self, "tabs", {}).values():
            try:
                tab.pump.stop()
                if getattr(tab, "_job", None) is not None:
                    tab._job.cancel()
            except Exception:
                pass
        self.tabs = {}
        for widget in (self.sidebar, self.content):
            try:
                widget.destroy()
            except Exception:
                pass
        _FONT_REGISTRY.clear()
        UI_FAMILY = choose_font_family(self)
        apply_tk_default_fonts(self)
        self._build_ui()

    def _restore_geometry(self):
        """Apply the saved size, clamped to the screen and to our minimum."""
        raw = str(self.settings.get("geometry") or DEFAULT_GEOMETRY)
        match = re.match(r"^(\d+)x(\d+)(?:\+(-?\d+)\+(-?\d+))?$", raw.strip())
        width, height = 1240, 800
        pos = None
        if match:
            width, height = int(match.group(1)), int(match.group(2))
            if match.group(3) is not None:
                pos = (int(match.group(3)), int(match.group(4)))
        try:
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
        except Exception:
            screen_w, screen_h = 1280, 800
        width = max(MIN_WIDTH, min(width, max(MIN_WIDTH, screen_w - 80)))
        height = max(MIN_HEIGHT, min(height, max(MIN_HEIGHT, screen_h - 100)))
        if pos is None or not (-20 <= pos[0] <= screen_w - 100
                               and -20 <= pos[1] <= screen_h - 100):
            pos = (max(0, (screen_w - width) // 2), max(0, (screen_h - height) // 3))
        try:
            self.geometry(f"{width}x{height}+{pos[0]}+{pos[1]}")
        except Exception:
            try:
                self.geometry(DEFAULT_GEOMETRY)
            except Exception:
                pass

    # ---- timers that must not fire after the window is destroyed ------------
    def _schedule(self, delay_ms, fn):
        """``after`` with bookkeeping so shutdown can cancel every timer."""
        holder = {}

        def runner():
            try:
                self._after_ids.remove(holder.get("id"))
            except Exception:
                pass
            self._run_timer(fn)

        try:
            holder["id"] = self.after(delay_ms, runner)
        except tk.TclError:
            return None
        self._after_ids.append(holder["id"])
        return holder["id"]

    def _run_timer(self, fn):
        if self._closing:
            return
        try:
            fn()
        except tk.TclError:
            pass
        except Exception:
            pass

    def _cancel_timers(self):
        for after_id in list(getattr(self, "_after_ids", [])):
            try:
                self.after_cancel(after_id)
            except Exception:
                pass
        self._after_ids = []

    # ---- sidebar -----------------------------------------------------------
    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, corner_radius=0, width=230)
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.sidebar.grid_propagate(False)
        self.sidebar.columnconfigure(0, weight=1)
        self.sidebar.rowconfigure(98, weight=1)

        ctk.CTkLabel(self.sidebar, text=f"🤖 {APP_NAME}", font=F(20, "bold"),
                     anchor="w").grid(row=0, column=0, padx=16, pady=(18, 0),
                                      sticky="ew")
        ctk.CTkLabel(self.sidebar, text=t("ui.app.subtitle"),
                     text_color="gray50", font=F(11), anchor="w").grid(
            row=1, column=0, padx=16, sticky="ew")

        self.nav_btns = {}
        for i, (name, label) in enumerate([
                ("transcribe", t("ui.nav.transcribe")),
                ("download", t("ui.nav.download")),
                ("translate", t("ui.nav.translate")),
                ("settings", t("ui.nav.settings"))]):
            btn = ctk.CTkButton(self.sidebar, text=label, height=42, anchor="w",
                                corner_radius=8, font=F(13),
                                fg_color="transparent",
                                hover_color=("#ddd", "#333"),
                                command=lambda n=name: self.show(n))
            btn.grid(row=2 + i, column=0, padx=10, pady=3, sticky="ew")
            self.nav_btns[name] = btn

        ui = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        ui.grid(row=99, column=0, padx=12, pady=10, sticky="sew")
        ui.columnconfigure(0, weight=1)

        ctk.CTkLabel(ui, text=t("ui.label.ui_scale"), font=F(11),
                     anchor="w").grid(row=0, column=0, sticky="ew")
        self.scale_val = tk.DoubleVar(value=float(self.settings.get("scale", 1.0)))
        ctk.CTkSlider(ui, from_=0.75, to=1.5, number_of_steps=15,
                      variable=self.scale_val, command=self._on_scale).grid(
            row=1, column=0, sticky="ew", pady=(2, 6))

        ctk.CTkLabel(ui, text=t("ui.label.appearance"), font=F(11), anchor="w").grid(
            row=2, column=0, sticky="ew")
        self.theme_menu = ctk.CTkOptionMenu(ui, values=["system", "dark", "light"],
                                            font=F(11), dropdown_font=F(11),
                                            command=self._on_theme)
        self.theme_menu.set(self.settings.get("theme", "system"))
        self.theme_menu.grid(row=3, column=0, sticky="ew", pady=(2, 6))

        ctk.CTkLabel(ui, text=t("ui.label.language"), font=F(11), anchor="w").grid(
            row=4, column=0, sticky="ew")
        self.lang_ui_menu = ctk.CTkOptionMenu(
            ui, values=[i18n.language_label(code) for code in i18n.language_codes()],
            font=F(11), dropdown_font=F(11), command=self._on_language)
        self.lang_ui_menu.set(i18n.language_label(i18n.get_language()))
        self.lang_ui_menu.grid(row=5, column=0, sticky="ew", pady=(2, 6))

        ctk.CTkButton(ui, text=t("ui.btn.shortcuts"), height=28, font=F(11),
                      fg_color="transparent", hover_color=("#ddd", "#333"),
                      border_width=1, command=self.show_shortcuts).grid(
            row=6, column=0, sticky="ew", pady=(0, 4))
        ctk.CTkLabel(
            ui, text=t("ui.hint.shortcuts_layout"),
            font=F(10), justify="right", text_color="gray50",
            wraplength=190).grid(row=7, column=0, sticky="ew")

    def _on_language(self, label):
        for code in i18n.language_codes():
            if i18n.language_label(code) == label:
                self.set_language(code)
                return

    def _build_content(self):
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

    # ---- shortcuts ---------------------------------------------------------
    def _bind_shortcuts(self):
        # Bind on key *presses* and resolve from the physical key code, so the
        # shortcut keeps working when the OS layout is Persian/Arabic/Cyrillic.
        self.bind_all("<Control-KeyPress>", self._on_ctrl_press, add="+")
        if sys.platform.startswith("win"):
            # These have no native Tk binding on Windows, but do on X11.
            self.bind_all("<Shift-Insert>",
                          lambda _e: self._text_op_focus("paste"), add="+")
            self.bind_all("<Control-Insert>",
                          lambda _e: self._text_op_focus("copy"), add="+")
            self.bind_all("<Shift-Delete>",
                          lambda _e: self._text_op_focus("cut"), add="+")
        self.bind_all("<F1>", lambda _e: self.show_shortcuts(), add="+")
        self.bind_all("<F5>", lambda _e: self._start_current(), add="+")
        self.bind_all("<Escape>", lambda _e: self._cancel_current(), add="+")
        self.bind_all("<Control-Tab>", lambda _e: self._cycle_tab(1), add="+")

    @staticmethod
    def _resolve_letter(event):
        """Return the logical key ('c', '1', 'tab', …) regardless of layout."""
        keysym = (getattr(event, "keysym", "") or "")
        low = keysym.lower()
        if len(low) == 1 and low.isascii() and low.isalnum():
            return low
        if low in ("tab", "return", "kp_enter", "escape", "space"):
            return "return" if low == "kp_enter" else low
        code = getattr(event, "keycode", 0) or 0
        if sys.platform.startswith("win"):
            for name, vk in VK.items():
                if code == vk:
                    return name
            if 48 <= code <= 57:      # VK 0x30..0x39 -> '0'..'9'
                return chr(code)
            if code == 9:
                return "tab"
            if code in (13, 10):
                return "return"
        elif sys.platform.startswith("linux"):
            # X11 keycodes follow physical QWERTY positions.
            for name, kc in X11_KEYCODE.items():
                if code == kc:
                    return name
            if 10 <= code <= 19:      # keycodes 10..19 -> '1'..'9', then '0'
                return "0" if code == 19 else str(code - 9)
            if code == 23:
                return "tab"
            if code == 36:
                return "return"
        return None

    def _focused_text(self):
        try:
            widget = self.focus_get()
        except Exception:
            widget = None
        return inner_text_widget(widget)

    def _text_op_focus(self, op):
        target = self._focused_text()
        if target is None:
            # fall back to the current tab's log so Ctrl+C always copies something
            tab = self.current_tab()
            target = inner_text_widget(getattr(tab, "log_box", None))
        if target is not None:
            text_operation(target, op)
        return "break"

    def _on_ctrl_press(self, event):
        key = self._resolve_letter(event)
        if not key:
            return None
        keysym = (getattr(event, "keysym", "") or "").lower()
        # When the layout produced a real Latin keysym, Tk's own class bindings
        # already handled Ctrl+C/V/X/A/Z. Only step in when they could not.
        native_letter = (len(keysym) == 1 and keysym.isascii() and keysym.isalpha())

        focused = self._focused_text()
        if key in TEXT_KEYS:
            if focused is not None:
                if native_letter:
                    return None
                text_operation(focused, TEXT_KEYS[key])
                return "break"
            if key == "c":
                return self._text_op_focus("copy")
            return "break"

        if key == "o":
            self._open_shortcut()
            return "break"
        if key == "s":
            self._save_shortcut()
            return "break"
        if key == "q":
            self._on_close()
            return "break"
        if key == "l":
            self._clear_log_shortcut()
            return "break"
        if key == "return":
            self._start_current()
            return "break"
        if key == "tab":
            step = -1 if (getattr(event, "state", 0) & 0x0001) else 1
            self._cycle_tab(step)
            return "break"
        if key in ("1", "2", "3", "4"):
            self.show(TAB_ORDER[int(key) - 1])
            return "break"
        return None

    def _start_current(self):
        tab = self.current_tab()
        trigger = getattr(tab, "trigger_start", None)
        if callable(trigger):
            trigger()
        return "break"

    def _cancel_current(self):
        tab = self.current_tab()
        cancel = getattr(tab, "cancel", None)
        if callable(cancel):
            cancel()
        return "break"

    def _open_shortcut(self):
        tab = self.current_tab()
        picker = getattr(tab, "_pick_file", None) or getattr(tab, "_pick", None)
        if callable(picker):
            try:
                picker()
            except Exception:
                pass
        return "break"

    def _save_shortcut(self):
        tab = self.current_tab()
        saver = getattr(tab, "_save", None)
        if callable(saver):
            try:
                saver()
            except Exception:
                pass
        else:
            save_settings(self.settings)
        return "break"

    def _clear_log_shortcut(self):
        tab = self.current_tab()
        clearer = getattr(tab, "clear_log", None)
        if callable(clearer):
            clearer()
        return "break"

    def _cycle_tab(self, step):
        try:
            idx = TAB_ORDER.index(self.current) + step
        except (ValueError, AttributeError):
            idx = 0
        self.show(TAB_ORDER[idx % len(TAB_ORDER)])
        return "break"

    # ---- navigation --------------------------------------------------------
    def current_tab(self):
        return self.tabs.get(getattr(self, "current", "transcribe"),
                             self.tabs["transcribe"])

    def show(self, name):
        if name not in self.tabs:
            return
        self.current = name
        for key, tab in self.tabs.items():
            if key == name:
                tab.grid(row=0, column=0, sticky="nsew")
            else:
                tab.grid_forget()
        for key, btn in self.nav_btns.items():
            btn.configure(fg_color=("#dcdcdc", "#2f3044") if key == name
                          else "transparent")
        tab = self.tabs[name]
        focus = getattr(tab, "focus_first", None)
        if callable(focus):
            self._schedule(30, focus)

    # ---- scaling / theme ---------------------------------------------------
    def _on_scale(self, value):
        self._apply_scale(float(value))
        self.settings["scale"] = float(value)

    def _apply_scale(self, value):
        value = max(0.75, min(1.5, float(value)))
        try:
            ctk.set_widget_scaling(value)
            ctk.set_window_scaling(value)
        except Exception:
            pass
        rescale_fonts(value)

    def _on_theme(self, choice):
        try:
            ctk.set_appearance_mode(choice)
        except Exception:
            pass
        self.settings["theme"] = choice

    # ---- misc --------------------------------------------------------------
    def apply_proxy(self, proxy):
        try:
            from core import config as cfg
            cfg.YT_PROXY = (proxy or "").strip()
        except Exception:
            pass

    def show_proxy_dialog(self):
        proxy = mb.askstring(
            APP_NAME,
            t("ui.dialog.proxy"),
            initialvalue=self.settings.get("proxy", ""), parent=self)
        if proxy is not None:
            proxy = proxy.strip()
            self.settings["proxy"] = proxy
            self.apply_proxy(proxy)
            save_settings(self.settings)
            mb.showinfo(APP_NAME, t("ui.log.proxy_applied") if proxy else t("ui.log.proxy_cleared"),
                        parent=self)

    def refresh_out_dirs(self):
        for tab in self.tabs.values():
            var = getattr(tab, "out_var", None)
            if var is not None:
                try:
                    var.set(self.settings["out_dir"])
                except Exception:
                    pass

    def show_shortcuts(self):
        win = ctk.CTkToplevel(self)
        win.title(t("ui.title.shortcuts"))
        win.geometry("560x460")
        win.transient(self)
        text = (
            t("ui.help.shortcuts")
        )
        box = make_textbox(win, wrap="word")
        box.pack(fill="both", expand=True, padx=14, pady=(14, 8))
        box.insert("1.0", text)
        box.configure(state="disabled")
        ctk.CTkButton(win, text=t("ui.btn.close"), width=100,
                      command=win.destroy).pack(pady=(0, 12))
        try:
            win.grab_set()
        except Exception:
            pass

    def _startup_checks(self):
        try:
            status = engine.environment_status()
        except Exception:
            return
        tab = self.tabs.get("transcribe")
        if not status["ffmpeg"]:
            tab.log(t("ui.warn.ffmpeg_missing_install"))
            mb.showwarning(
                t("ui.err.ffmpeg_missing"),
                t("ui.dialog.ffmpeg_help"),
                parent=self)
        if not status["ytdlp"]:
            tab.log(t("ui.warn.ytdlp_missing"))
        tab.log(t("ui.log.env_ready", v1=status['keys_groq'], v2=status['keys_gemini']))

    def _current_geometry(self):
        """Window geometry worth persisting, or None.

        A window that was never mapped, is minimised/zoomed, or is still at its
        starting size must not overwrite the saved size — otherwise a fast
        open/close (or a crash) permanently shrinks the next launch.
        """
        try:
            if self.winfo_width() <= 1 or self.winfo_height() <= 1:
                return None
            if str(self.state()) != "normal":
                return None
            win_w, win_h = self.winfo_width(), self.winfo_height()
            if win_w < MIN_WIDTH or win_h < MIN_HEIGHT:
                return None
            return f"{win_w}x{win_h}+{self.winfo_x()}+{self.winfo_y()}"
        except Exception:
            return None

    def _on_close(self):
        self._closing = True
        try:
            geometry = self._current_geometry()
            if geometry:
                self.settings["geometry"] = geometry
            self.settings["scale"] = float(self.scale_val.get())
            self.settings["theme"] = self.theme_menu.get()
            self.settings["language"] = i18n.get_language()
            save_settings(dict(self.settings))
        except Exception:
            pass
        # Stop timers and pumps first: a queued callback running after destroy
        # makes Tk print "application has been destroyed" errors on exit.
        try:
            self._cancel_timers()
        except Exception:
            pass
        for tab in getattr(self, "tabs", {}).values():
            try:
                tab.pump.stop()
            except Exception:
                pass
            if getattr(tab, "_job", None) is not None:
                try:
                    tab._job.cancel()
                except Exception:
                    pass
        # Also drop every remaining timer in this interpreter — CustomTkinter
        # schedules its own DPI-tracking loop, and a callback firing after
        # destroy makes Tk print "invalid command name …" on exit.
        try:
            for after_id in str(self.tk.eval("after info")).split():
                try:
                    self.after_cancel(after_id)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass


def main():
    enable_high_dpi()
    global UI_FAMILY
    settings = load_settings()
    try:
        ctk.set_appearance_mode(settings.get("theme", "system"))
    except Exception:
        pass
    ctk.set_default_color_theme("dark-blue")

    app = App()
    try:
        # Fonts may have been created before the family was known; reapply.
        for font, base in list(_FONT_REGISTRY):
            try:
                font.configure(family=UI_FAMILY)
            except Exception:
                pass
        app._apply_scale(float(settings.get("scale", 1.0)))
    except Exception:
        pass
    app.mainloop()


if __name__ == "__main__":
    main()