"""Manual GUI smoke test: build every tab, pump the event loop, then close.

Run:  set PYTHONPATH=.deps && python tests/_smoke_gui.py
"""

import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import main  # noqa: E402


def main_smoke():
    main.enable_high_dpi()
    # Never touch the user's real settings.json / logs while smoke testing.
    scratch = os.path.join(ROOT, "tests", "_artifacts")
    os.makedirs(scratch, exist_ok=True)
    main.SETTINGS_PATH = os.path.join(scratch, "smoke_settings.json")
    main.LOG_DIR = os.path.join(scratch, "smoke_logs")
    app = main.App()
    errors = []

    def step(delay=0):
        app.update_idletasks()
        app.update()

    def settle(seconds=0.35):
        """Run the Tk loop long enough for the 100 ms progress pump to drain."""
        import time as _time
        end = _time.monotonic() + seconds
        while _time.monotonic() < end:
            step()
            _time.sleep(0.02)

    step()
    print("App created; UI_FAMILY =", main.UI_FAMILY)

    # Build/scroll every tab and make sure focus + fonts do not explode.
    for name in main.TAB_ORDER:
        try:
            app.show(name)
            step()
            tab = app.tabs[name]
            print(f"tab {name:10s} ok  widgets={len(tab.winfo_children())}")
        except Exception:
            errors.append((name, traceback.format_exc()))

    # Exercise the progress rendering with a fake job.
    try:
        tab = app.tabs["transcribe"]
        job = tab.make_job()
        tab.reset_progress()
        job.started = 0.0
        job.report(30, "🎙️ ترنسکرایب بخش 1/3 (Whisper)\n📄 🔄 ▫️ ▫️", 30,
                   "کلید 1/2")
        settle()
        assert tab.percent_lbl.cget("text").endswith("%"), "percent label not set"
        assert "1/3" in tab.status_lbl.cget("text"), "status label not set"
        assert "▫️" in tab.stage_lbl.cget("text"), "stage label not set"
        assert "🔑" in tab.info_lbl.cget("text"), "note not rendered"
        print("progress render ok:", tab.percent_lbl.cget("text"),
              "|", tab.info_lbl.cget("text"))
        # A transfer stage must be throttled, not spam the log.
        for pct in (5, 15, 25, 35):
            job.dl_progress()(pct=pct, speed="2MiB/s", eta="00:30")
        job.report(100, "✅ تمام شد", 100)
        settle()
        tab.set_running(False)
        print("download progress ok:", tab.percent_lbl.cget("text"))
    except Exception:
        errors.append(("progress", traceback.format_exc()))

    # Shortcut resolution through a real Tk event object.
    try:
        class Ev:
            keysym = "م"
            keycode = 86
            state = 0x4
        assert main.App._resolve_letter(Ev()) == "v"
        print("shortcut resolution ok (Persian layout -> Ctrl+V)")
    except Exception:
        errors.append(("shortcut", traceback.format_exc()))

    # The whole non-English path: a real CTkEntry, Persian keysym, Ctrl+V/A.
    try:
        import customtkinter as ctk
        app.show("transcribe")
        app.focus_force()
        settle(0.15)
        tab = app.tabs["transcribe"]
        entry = main.make_entry(tab, placeholder_text="تست")
        entry.grid(row=3, column=0, sticky="ew")
        app.clipboard_clear()
        app.clipboard_append("متن فارسی چسبانده شد")
        inner = main.inner_text_widget(entry)
        assert inner is not None, "inner tk Entry not found on CTkEntry"

        class CtrlV:
            keysym = "م"      # Persian layout reports the letter, not 'v'
            keycode = 86      # ...but the physical key is still V
            state = 0x4
            widget = inner
        inner.focus_force()
        settle(0.15)
        assert app.focus_get() is inner, "entry did not take focus"
        app._on_ctrl_press(CtrlV())
        settle(0.15)
        assert inner.get() == "متن فارسی چسبانده شد", f"paste failed: {inner.get()!r}"

        class CtrlA:
            keysym = "ش"      # Persian 'a' position
            keycode = 65
            state = 0x4
            widget = inner
        app._on_ctrl_press(CtrlA())
        settle(0.15)
        assert inner.selection_present(), "select-all failed"
        assert inner.selection_get() == "متن فارسی چسبانده شد"
        print("Persian-layout Ctrl+V / Ctrl+A on a real entry: ok")

        # English layout must not double-paste (native binding already ran).
        class LatinV:
            keysym = "v"
            keycode = 86
            state = 0x4
            widget = inner
        inner.delete(0, "end")
        app.clipboard_clear()
        app.clipboard_append("x")
        assert app._on_ctrl_press(LatinV()) is None, "should defer to Tk binding"
        print("English-layout behaviour deferred to Tk: ok")
        entry.destroy()
    except Exception:
        errors.append(("persian-shortcuts", traceback.format_exc()))

    # Right-click context menu wiring on the log box.
    try:
        tab = app.tabs["transcribe"]
        box = main.inner_text_widget(tab.log_box)
        assert box is not None, "log box inner widget missing"
        assert box.bind("<Button-3>"), "no right-click binding on log box"
        tab.log("خط آزمایشی لاگ")
        step()
        assert "خط آزمایشی لاگ" in box.get("1.0", "end-1c"), "log not written"
        print("log + context menu ok")
    except Exception:
        errors.append(("log", traceback.format_exc()))

    # Fonts / scaling.
    try:
        app._apply_scale(1.2)
        step()
        app._apply_scale(1.0)
        step()
        print("scale ok; font registry size =", len(main._FONT_REGISTRY))
    except Exception:
        errors.append(("scale", traceback.format_exc()))

    try:
        app._on_close()
    except Exception:
        errors.append(("close", traceback.format_exc()))

    if errors:
        print("\n=== FAILURES ===")
        for name, tb in errors:
            print(f"\n--- {name} ---\n{tb}")
        return 1
    print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main_smoke())