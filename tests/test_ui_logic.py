"""UI-logic tests for main.py: fonts, non-English shortcuts, text operations.

main.py imports customtkinter; here it is replaced by a tiny stub so the pure
logic (key resolution, clipboard routing, duration formatting) can be tested
without a display server or the real CTk package.

Run:  python -m unittest discover -s tests -v
"""

import importlib.util
import os
import sys
import types
import unittest

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# Only fake CustomTkinter when the real package is missing: otherwise the stub
# would shadow it for every other test module in the same process.
HAS_REAL_CTK = importlib.util.find_spec("customtkinter") is not None


class _StubBase:
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return lambda *a, **k: None


def _install_stub_modules():
    if HAS_REAL_CTK:
        # Nothing to fake; the real package is importable.
        if "dotenv" not in sys.modules:
            dotenv = types.ModuleType("dotenv")
            dotenv.load_dotenv = lambda *a, **k: None
            sys.modules["dotenv"] = dotenv
        return
    if "customtkinter" not in sys.modules:
        ctk = types.ModuleType("customtkinter")

        def _font(**kwargs):
            obj = _StubBase()
            obj.kwargs = dict(kwargs)
            obj.configure = lambda **kw: obj.kwargs.update(kw)
            return obj

        ctk.CTkFont = _font
        for name in ("CTk", "CTkFrame", "CTkLabel", "CTkButton", "CTkEntry",
                     "CTkTextbox", "CTkOptionMenu", "CTkProgressBar",
                     "CTkCheckBox", "CTkSegmentedButton", "CTkSlider",
                     "CTkScrollableFrame", "CTkToplevel", "CTkImage",
                     "CTkTabview", "CTkSwitch", "CTkRadioButton"):
            setattr(ctk, name, type(name, (_StubBase,), {}))
        ctk.ThemeManager = type("ThemeManager", (_StubBase,), {})
        ctk.ThemeManager.theme = {"CTkFont": {"family": "Roboto"}}
        ctk.set_appearance_mode = lambda *a, **k: None
        ctk.set_default_color_theme = lambda *a, **k: None
        ctk.set_widget_scaling = lambda *a, **k: None
        ctk.set_window_scaling = lambda *a, **k: None
        sys.modules["customtkinter"] = ctk

    if "dotenv" not in sys.modules:
        dotenv = types.ModuleType("dotenv")
        dotenv.load_dotenv = lambda *a, **k: None
        sys.modules["dotenv"] = dotenv

    if "requests" not in sys.modules:
        requests = types.ModuleType("requests")
        requests.post = lambda *a, **k: None
        requests.get = lambda *a, **k: None
        sys.modules["requests"] = requests


_install_stub_modules()

import tkinter as tk  # noqa: E402

import main  # noqa: E402

class FakeEvent:
    """Minimal stand-in for a Tk key event."""

    def __init__(self, keysym="", keycode=0, state=0):
        self.keysym = keysym
        self.keycode = keycode
        self.state = state


class DurationTests(unittest.TestCase):
    def test_format_in_the_default_language(self):
        """A fresh install shows English (and Persian when asked for)."""
        main.i18n.set_language("en")
        self.assertEqual(main.fmt_duration(12), "12 seconds")
        self.assertEqual(main.fmt_duration(65), "1:05")
        self.assertEqual(main.fmt_duration(3725), "1:02:05")
        self.assertEqual(main.fmt_duration("bad"), "—")
        self.assertEqual(main.fmt_duration(-5), "0 seconds")
        main.i18n.set_language("fa")
        self.assertEqual(main.fmt_duration(12), "12 ثانیه")
        self.assertEqual(main.fmt_duration(-5), "0 ثانیه")
        main.i18n.set_language(main.i18n.DEFAULT_LANGUAGE)


class KeyResolutionTests(unittest.TestCase):
    """The core fix: shortcuts must survive a Persian/Arabic keyboard layout."""

    def test_latin_keysym_still_works(self):
        event = FakeEvent(keysym="v", keycode=86)
        self.assertEqual(main.App._resolve_letter(event), "v")

    def test_persian_keysym_falls_back_to_keycode(self):
        # Ctrl+V on a Persian layout reports the Persian letter as keysym.
        event = FakeEvent(keysym="م", keycode=86)
        self.assertEqual(main.App._resolve_letter(event), "v")

    def test_persian_digits_use_keycode(self):
        event = FakeEvent(keysym="۲", keycode=50)
        self.assertEqual(main.App._resolve_letter(event), "2")

    def test_cyrillic_layout(self):
        event = FakeEvent(keysym="м", keycode=86)
        self.assertEqual(main.App._resolve_letter(event), "v")

    def test_x11_keycodes(self):
        # X11 keycodes are physical positions too: 55 = V, 38 = A, 19 = 0.
        real = sys.platform
        sys.platform = "linux"
        try:
            self.assertEqual(
                main.App._resolve_letter(FakeEvent(keysym="م", keycode=55)), "v")
            self.assertEqual(
                main.App._resolve_letter(FakeEvent(keysym="ش", keycode=38)), "a")
            self.assertEqual(
                main.App._resolve_letter(FakeEvent(keysym="۰", keycode=19)), "0")
            self.assertEqual(
                main.App._resolve_letter(FakeEvent(keysym="۱", keycode=10)), "1")
            self.assertIsNone(
                main.App._resolve_letter(FakeEvent(keysym="م", keycode=999)))
        finally:
            sys.platform = real

    def test_named_keys(self):
        self.assertEqual(main.App._resolve_letter(FakeEvent(keysym="Return")), "return")
        self.assertEqual(main.App._resolve_letter(FakeEvent(keysym="Tab")), "tab")
        self.assertEqual(main.App._resolve_letter(FakeEvent(keysym="KP_Enter")), "return")

    def test_unknown_key_returns_none(self):
        self.assertIsNone(main.App._resolve_letter(FakeEvent(keysym="F9")))


class TextOperationTests(unittest.TestCase):
    """Ctrl+A/C/V and right-click menu actions go through these helpers."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
            cls.root.geometry("320x200")
            cls.root.deiconify()
            cls.root.update()
            cls.available = True
        except Exception:
            cls.available = False

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "available", False):
            try:
                cls.root.destroy()
            except Exception:
                pass

    def setUp(self):
        if not self.available:
            self.skipTest("Tk display not available")

    def test_select_all_and_copy_persian(self):
        entry = tk.Entry(self.root)
        entry.insert(0, "سلام دنیا")
        self.assertTrue(main.text_operation(entry, "select_all"))
        self.assertEqual(entry.selection_get(), "سلام دنیا")
        self.assertTrue(main.text_operation(entry, "copy"))

    def test_paste_into_second_entry(self):
        src = tk.Entry(self.root)
        src.pack()
        src.insert(0, "چسباندن تست")
        main.text_operation(src, "select_all")
        main.text_operation(src, "copy")
        self.root.update()

        dst = tk.Entry(self.root)
        dst.pack()
        dst.focus_force()
        self.root.update()
        if self.root.focus_get() is not dst:
            self.skipTest("no keyboard focus available in this environment")
        self.assertTrue(main.text_operation(dst, "paste"))
        self.root.update()
        self.assertEqual(dst.get(), "چسباندن تست")

    def test_cut_removes_text(self):
        entry = tk.Entry(self.root)
        entry.insert(0, "قطع کن")
        main.text_operation(entry, "select_all")
        self.assertTrue(main.text_operation(entry, "cut"))
        self.root.update()
        self.assertEqual(entry.get(), "")

    def test_text_widget_select_all(self):
        box = tk.Text(self.root, height=2)
        box.insert("1.0", "خط یک\nخط دو")
        self.assertTrue(main.text_operation(box, "select_all"))
        self.assertTrue(box.tag_ranges("sel"))


class InnerWidgetTests(unittest.TestCase):
    def test_finds_entry_on_ctk_like_wrapper(self):
        if not sys.platform.startswith("win") and not os.environ.get("DISPLAY"):
            self.skipTest("no display")
        try:
            root = tk.Tk()
            root.withdraw()
        except Exception:
            self.skipTest("Tk display not available")
        try:
            entry = tk.Entry(root)
            wrapper = types.SimpleNamespace(_entry=entry)
            self.assertIs(main.inner_text_widget(wrapper), entry)
            self.assertIs(main.inner_text_widget(entry), entry)
            self.assertIsNone(main.inner_text_widget(object()))
        finally:
            root.destroy()


class FontTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
            self.root.update()
        except Exception:
            self.root = None

    def tearDown(self):
        if self.root is not None:
            try:
                self.root.destroy()
            except Exception:
                pass

    def _font_size(self, font):
        if hasattr(font, "kwargs"):          # stub object
            return font.kwargs.get("size")
        try:
            return font.cget("size")         # real CTkFont
        except Exception:
            return getattr(font, "_size", None)

    def test_font_registry_rescales(self):
        if self.root is None:
            self.skipTest("Tk display not available")
        font = main.F(12)
        main.rescale_fonts(1.25)
        self.assertEqual(self._font_size(font), 15)
        main.rescale_fonts(1.0)
        self.assertEqual(self._font_size(font), 12)

    def test_family_prefers_persian_capable(self):
        if self.root is None:
            self.skipTest("Tk display not available")
        family = main.choose_font_family(self.root)
        self.assertTrue(family)
        # Segoe UI / Tahoma / Vazirmatn all carry Persian glyphs.
        self.assertIn(family, set(main.FONT_CANDIDATES) | {"TkDefaultFont"})


if __name__ == "__main__":
    unittest.main(verbosity=2)