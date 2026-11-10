"""Manual check: the UI starts in English and switches to Persian in place."""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import i18n  # noqa: E402
import main  # noqa: E402

tmp = tempfile.mkdtemp()
main.SETTINGS_PATH = os.path.join(tmp, "settings.json")
main.LOG_DIR = os.path.join(tmp, "logs")


def texts(app):
    """A handful of visible strings for each state."""
    tab = app.tabs["transcribe"]
    return {
        "nav": app.nav_btns["transcribe"].cget("text"),
        "start": tab.start_btn.cget("text"),
        "cancel": tab.cancel_btn.cget("text"),
        "status": tab.status_lbl.cget("text"),
        "lang_menu": app.lang_ui_menu.get(),
        "title_hint": app.tabs["download"].url_entry.cget("placeholder_text"),
        "engine_label": tab.prov_menu.get(),
        "lang_field": tab.lang_menu.get(),
    }


def settle(app, seconds=0.6):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.update_idletasks()
        app.update()
        time.sleep(0.02)


app = main.App()
settle(app)

print("first run, no settings.json ->", i18n.get_language())
before = texts(app)
for key, value in before.items():
    print(f"  {key:12s} {value!r}")
assert i18n.get_language() == "en", "first run must be English"
assert "Transcribe" in before["nav"]
assert before["start"].startswith("🚀 Start")
assert before["lang_menu"] == "English"
assert before["engine_label"].startswith("⚡")

# switch to Persian through the same path the dropdown uses
app._on_language("فارسی")
settle(app)
after = texts(app)
print("\nafter switching to Persian ->", i18n.get_language())
for key, value in after.items():
    print(f"  {key:12s} {value!r}")
assert i18n.get_language() == "fa"
assert after["start"] != before["start"], "labels were not rebuilt"
assert after["nav"] == "🎬  ساخت زیرنویس", after["nav"]
assert after["lang_menu"] == "فارسی"
assert after["engine_label"].startswith("⚡")
assert app.settings["language"] == "fa"

# settings survive a restart
app._on_close()
app2 = main.App()
settle(app2)
print("\nafter restart ->", i18n.get_language(), "| start:", app2.tabs["transcribe"].start_btn.cget("text"))
assert i18n.get_language() == "fa", "the chosen language must persist"
app2._on_close()

# and back to English
import json  # noqa: E402
import io  # noqa: E402
with io.open(main.SETTINGS_PATH, encoding="utf-8") as f:
    data = json.load(f)
print("persisted settings language:", data.get("language"))
assert data.get("language") == "fa"
print("\nLANGUAGE SWITCH OK")