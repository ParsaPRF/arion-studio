"""GUI wiring test: press Start with the engine stubbed out.

This exercises what used to be broken: validation → key checks → worker thread →
queue pump → progress rendering → completion handler, for every job type.

It needs the real CustomTkinter package, so it is skipped when it is absent
(CI without the dependency), and it never touches the network.

Run:  python -m unittest tests.test_gui_flow -v
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import types
import unittest

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

HAS_CTK = importlib.util.find_spec("customtkinter") is not None


class _MsgBox:
    """Records dialogs instead of blocking on them."""

    def __init__(self):
        self.infos, self.errors, self.warnings = [], [], []

    def showinfo(self, *a, **k):
        self.infos.append(a)

    def showerror(self, *a, **k):
        self.errors.append(a)

    def showwarning(self, *a, **k):
        self.warnings.append(a)

    def askstring(self, *a, **k):
        return None


@unittest.skipUnless(HAS_CTK, "customtkinter is not installed")
class GuiFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main as main_mod
        cls.main = main_mod
        cls.tmp = tempfile.mkdtemp(prefix="arion-gui-")
        main_mod.SETTINGS_PATH = os.path.join(cls.tmp, "settings.json")
        main_mod.LOG_DIR = os.path.join(cls.tmp, "logs")
        cls.msgbox = _MsgBox()
        main_mod.mb = cls.msgbox
        main_mod.open_in_file_manager = lambda *a, **k: None
        main_mod.enable_high_dpi()
        cls.app = main_mod.App()
        cls.app.settings["out_dir"] = os.path.join(cls.tmp, "out")
        os.makedirs(cls.app.settings["out_dir"], exist_ok=True)
        cls.app.refresh_out_dirs()
        cls.dummy_media = os.path.join(cls.tmp, "input.mp4")
        with open(cls.dummy_media, "wb") as f:
            f.write(b"\x00" * 32)
        cls.dummy_srt = os.path.join(cls.tmp, "in.srt")
        with open(cls.dummy_srt, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:01,000\nhello\n")

    @classmethod
    def tearDownClass(cls):
        # Exercise the real shutdown path: it must cancel every pending timer
        # and stop the pumps before Tk goes away.
        try:
            cls.app._on_close()
        except Exception:
            try:
                cls.app.destroy()
            except Exception:
                pass
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- helpers -------------------------------------------------------------
    def setUp(self):
        self.calls = {}
        # No job may leak from a previous test into this one.
        for tab in self.app.tabs.values():
            tab._job = None
            tab.set_running(False)
            tab.reset_progress()
            # The app instance is shared by the whole class, so a checkbox left
            # ticked would leak deep mode into the next test.
            if hasattr(tab, "deep_var"):
                tab.deep_var.set(False)
        m = self.main
        self._saved = {name: getattr(m.engine, name) for name in (
            "groq_keys", "gemini_keys", "openrouter_keys",
            "environment_status", "transcribe_file",
            "transcribe_youtube", "download_media", "download_subtitles",
            "download_info_txt", "translate_srt_file")}
        m.engine.groq_keys = lambda *a, **k: ["groq-key"]
        m.engine.gemini_keys = lambda *a, **k: ["gem-key"]
        m.engine.openrouter_keys = lambda *a, **k: ["or-key"]
        m.engine.environment_status = lambda *a, **k: {
            "ffmpeg": True, "ytdlp": True, "work_dir": self.tmp,
            "keys_groq": 1, "keys_gemini": 1, "keys_openrouter": 1}
        self.msgbox.infos.clear()
        self.msgbox.errors.clear()
        self.msgbox.warnings.clear()

    def _t(self, key, **kwargs):
        """Current-language text for a catalog key."""
        return self.main.t(key, **kwargs)

    def _label(self, pairs, code):
        """Display label for an engine constant entry (codes -> t(key))."""
        return self.main.t({c: key for c, key in pairs}[code])

    def tearDown(self):
        for name, fn in self._saved.items():
            setattr(self.main.engine, name, fn)

    def _stub(self, name, result):
        def fn(*args, **kwargs):
            self.calls[name] = {"args": args, "kwargs": kwargs}
            return result
        setattr(self.main.engine, name, fn)

    def _settle(self, tab, timeout=15.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.app.update_idletasks()
            self.app.update()
            time.sleep(0.02)
            if tab._job is None or not tab._job.running:
                # let the queue flush the final messages
                self._pump(0.1)
                return
        self.fail("job did not finish in time")

    def _pump(self, seconds=0.3):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.update_idletasks()
            self.app.update()
            time.sleep(0.02)

    def _log_text(self, tab):
        inner = self.main.inner_text_widget(tab.log_box)
        return inner.get("1.0", "end-1c") if inner else ""

    # -- transcription -------------------------------------------------------
    def _prepare_transcribe_file(self):
        tab = self.app.tabs["transcribe"]
        self.app.show("transcribe")
        self.app.settings["transcribe_source"] = "file"
        tab.seg.set(self._t("ui.seg.local_file"))
        tab.path_var.set(self.dummy_media)
        tab.cookie_var.set("")
        tab.lang_menu.set(self._label(self.main.engine.LANGUAGES, "fa"))
        return tab

    def test_gemini_only_key_is_used_for_a_file_transcription(self):
        # Regression: the file branch always handed engine.transcribe_file the
        # *Groq* list, so a user with only a Gemini key got "no API key".
        self.main.engine.groq_keys = lambda *a, **k: []
        self.main.engine.gemini_keys = lambda *a, **k: ["gem-key"]
        tab = self._prepare_transcribe_file()
        tab.prov_menu.set(self._label(self.main.engine.PROVIDERS, "gemini"))
        self._stub("transcribe_file", {"srt": os.path.join(self.tmp, "g.srt")})

        tab.trigger_start()
        self._settle(tab)

        self.assertFalse(self.msgbox.errors, "a saved Gemini key was rejected")
        call = self.calls.get("transcribe_file")
        self.assertIsNotNone(call, "engine.transcribe_file was never called")
        self.assertEqual(call["args"][1], ["gem-key"])
        self.assertEqual(call["kwargs"]["provider"], "gemini")

    def test_groq_only_key_still_works_for_the_groq_engine(self):
        self.main.engine.gemini_keys = lambda *a, **k: []
        self.main.engine.groq_keys = lambda *a, **k: ["groq-key"]
        tab = self._prepare_transcribe_file()
        tab.prov_menu.set(self._label(self.main.engine.PROVIDERS, "groq"))
        self._stub("transcribe_file", {"srt": os.path.join(self.tmp, "g.srt")})

        tab.trigger_start()
        self._settle(tab)

        self.assertFalse(self.msgbox.errors, "a saved Groq key was rejected")
        self.assertEqual(self.calls["transcribe_file"]["args"][1], ["groq-key"])

    def test_wrong_engine_with_one_key_says_what_to_do(self):
        # Only a Groq key, but the engine selector is on Gemini: the message
        # must name the missing key *and* point at the selector.
        self.main.engine.gemini_keys = lambda *a, **k: []
        tab = self._prepare_transcribe_file()
        tab.prov_menu.set(self._label(self.main.engine.PROVIDERS, "gemini"))
        self._stub("transcribe_file", {"srt": os.path.join(self.tmp, "g.srt")})

        tab.trigger_start()
        self._settle(tab)

        self.assertIsNone(self.calls.get("transcribe_file"))
        self.assertTrue(self.msgbox.errors, "no explanation was shown")
        text = str(self.msgbox.errors[-1][-1])
        self.assertIn("Gemini", text)
        self.assertIn("Groq", text, "the message should point at the other engine")
        self.assertGreater(len(text), 60,
                           "the message should explain the alternative, not just refuse")

    def test_settings_saves_the_openrouter_key(self):
        tab = self._settings_tab()
        tab.or_var.set("sk-or-v1-secret")
        tab.save_keys_var.set(False)

        tab._save()

        self.assertEqual(self.app.settings["openrouter_key"], "sk-or-v1-secret")
        self.assertEqual(tab.or_var.get(), "", "the field should clear after saving")

    def test_settings_saves_the_deep_review_engine(self):
        tab = self._settings_tab()
        tab.deep_menu.set(self._label(self.main.engine.DEEP_ENGINES, "openrouter"))

        tab._save()

        self.assertEqual(self.app.settings["deep_engine"], "openrouter")
        tab.deep_menu.set(self._label(self.main.engine.DEEP_ENGINES, "gemini"))
        tab._save()
        self.assertEqual(self.app.settings["deep_engine"], "gemini")

    def test_deep_review_with_openrouter_passes_the_reviewer(self):
        self.app.settings["deep_engine"] = "openrouter"
        tab = self._prepare_transcribe_file()
        tab.deep_var.set(True)
        self._stub("transcribe_file", {"srt": os.path.join(self.tmp, "d.srt")})

        tab.trigger_start()
        self._settle(tab)

        call = self.calls.get("transcribe_file")
        self.assertIsNotNone(call, "engine.transcribe_file was never called")
        self.assertTrue(call["kwargs"]["deep"])
        self.assertEqual(call["kwargs"]["refine_provider"], "openrouter")
        self.assertEqual(call["kwargs"]["refine_keys"], ["or-key"])
        self.assertTrue(call["kwargs"]["refine_models"],
                        "the free model list must reach the engine")

    def test_deep_review_without_an_openrouter_key_explains(self):
        self.main.engine.openrouter_keys = lambda *a, **k: []
        self.app.settings["deep_engine"] = "openrouter"
        tab = self._prepare_transcribe_file()
        tab.deep_var.set(True)
        self._stub("transcribe_file", {"srt": os.path.join(self.tmp, "d.srt")})

        tab.trigger_start()
        self._settle(tab)

        self.assertIsNone(self.calls.get("transcribe_file"))
        self.assertTrue(self.msgbox.errors, "no explanation was shown")
        text = str(self.msgbox.errors[-1][-1])
        self.assertIn("OpenRouter", text)

    def test_deep_review_with_gemini_still_works_for_a_groq_transcript(self):
        self.app.settings["deep_engine"] = "gemini"
        tab = self._prepare_transcribe_file()
        tab.prov_menu.set(self._label(self.main.engine.PROVIDERS, "groq"))
        tab.deep_var.set(True)
        self._stub("transcribe_file", {"srt": os.path.join(self.tmp, "d.srt")})

        tab.trigger_start()
        self._settle(tab)

        call = self.calls.get("transcribe_file")
        self.assertIsNotNone(call, "deep mode was blocked for a Groq transcript")
        self.assertTrue(call["kwargs"]["deep"])
        self.assertEqual(call["kwargs"]["refine_provider"], "gemini")
        self.assertEqual(call["kwargs"]["refine_keys"], ["gem-key"])

    def test_transcribe_file_flow(self):
        tab = self.app.tabs["transcribe"]
        self.app.show("transcribe")
        self.app.settings["transcribe_source"] = "file"
        tab.seg.set(self._t("ui.seg.local_file"))
        tab.path_var.set(self.dummy_media)
        tab.cookie_var.set("")
        tab.lang_menu.set(self._label(self.main.engine.LANGUAGES, "fa"))
        expected_out = tab.out_var.get()
        self._stub("transcribe_file", {"srt": os.path.join(self.tmp, "out.mp4.srt"),
                                       "txt": os.path.join(self.tmp, "out.mp4.txt")})

        tab.trigger_start()
        self._settle(tab)

        call = self.calls.get("transcribe_file")
        self.assertIsNotNone(call, "engine.transcribe_file was never called")
        kwargs = call["kwargs"]
        self.assertEqual(kwargs["language"], "fa")
        self.assertEqual(kwargs["output_format"], "srt")
        self.assertEqual(kwargs["provider"], "groq")
        self.assertFalse(kwargs["deep"])
        self.assertEqual(call["args"][1], ["groq-key"])       # API keys
        self.assertEqual(call["args"][2], self.dummy_media)   # input path
        self.assertEqual(call["args"][3], expected_out)
        self.assertTrue(self.msgbox.infos, "success was never reported to the user")
        self.assertIn("Subtitles created", str(self.msgbox.infos[-1]))
        self.assertIn("Done", tab.status_lbl.cget("text"))
        self.assertIn("Files written", self._log_text(tab))
        self.assertEqual(tab.percent_lbl.cget("text"), "100.0%")
        self.assertFalse(self.msgbox.errors, self.msgbox.errors)

    def test_transcribe_requires_keys(self):
        tab = self.app.tabs["transcribe"]
        self.main.engine.groq_keys = lambda *a, **k: []
        self.app.settings["groq_key"] = ""
        self.app.settings["transcribe_source"] = "file"
        tab.seg.set(self._t("ui.seg.local_file"))
        tab.path_var.set(self.dummy_media)
        tab.trigger_start()
        self.app.update()
        self.assertTrue(self.msgbox.errors, "a missing key must be reported")
        self.assertIn("Groq", str(self.msgbox.errors[-1]))
        self.assertIsNone(tab._job, "no job may start without keys")

    def test_transcribe_missing_file_is_reported(self):
        tab = self.app.tabs["transcribe"]
        self.app.settings["transcribe_source"] = "file"
        tab.seg.set(self._t("ui.seg.local_file"))
        tab.path_var.set(os.path.join(self.tmp, "nope.mp4"))
        tab.trigger_start()
        self.app.update()
        self.assertTrue(self.msgbox.errors)
        self.assertIsNone(tab._job)

    def test_youtube_transcribe_flow(self):
        tab = self.app.tabs["transcribe"]
        self.app.settings["transcribe_source"] = "url"
        tab.seg.set(self._t("ui.seg.youtube_link"))
        tab.url_var.set("https://www.youtube.com/watch?v=abc123")
        tab.prov_menu.set(self._label(self.main.engine.PROVIDERS, "gemini"))
        tab._sync_deep()
        tab.deep_var.set(True)
        self._stub("transcribe_youtube", {"srt": os.path.join(self.tmp, "yt.srt")})

        tab.trigger_start()
        self._settle(tab)

        call = self.calls.get("transcribe_youtube")
        self.assertIsNotNone(call)
        self.assertEqual(call["args"][1], ["gem-key"])   # gemini keys for gemini
        self.assertEqual(call["kwargs"]["provider"], "gemini")
        self.assertTrue(call["kwargs"]["deep"])
        self.assertFalse(self.msgbox.errors, self.msgbox.errors)

    # -- downloads -----------------------------------------------------------
    def test_download_video_flow(self):
        tab = self.app.tabs["download"]
        self.app.show("download")
        tab.url_var.set("https://www.youtube.com/watch?v=abc123")
        tab._set_kind("video")
        tab.quality_menu.set(self._label(self.main.engine.DL_VIDEO_QUALITIES, "1080"))
        out = os.path.join(self.tmp, "dl.mp4")
        self._stub("download_media", out)

        tab.trigger_start()
        self._settle(tab)

        call = self.calls["download_media"]
        self.assertEqual(call["kwargs"]["quality"], "1080")
        self.assertIn("dl.mp4", self._log_text(tab))
        self.assertEqual(tab.percent_lbl.cget("text"), "100.0%")

    def test_download_audio_quality_is_honoured(self):
        tab = self.app.tabs["download"]
        tab.url_var.set("https://youtu.be/abc123")
        tab._set_kind("audio")
        tab.quality_menu.set(self._label(self.main.engine.DL_AUDIO_QUALITIES, "flac"))
        self._stub("download_media", os.path.join(self.tmp, "dl.flac"))
        tab.trigger_start()
        self._settle(tab)
        self.assertEqual(self.calls["download_media"]["kwargs"]["quality"], "flac")

    def test_download_subtitles_flow(self):
        tab = self.app.tabs["download"]
        tab.url_var.set("https://youtu.be/abc123")
        tab._set_kind("subs")
        tab.quality_menu.set(self._t("ui.lang.de"))
        path = os.path.join(self.tmp, "sub.de.srt")
        self._stub("download_subtitles", (path, "de", "manual", "Titel"))
        tab.trigger_start()
        self._settle(tab)
        self.assertEqual(self.calls["download_subtitles"]["kwargs"]["lang"], "de")
        self.assertIn("Subtitle", self._log_text(tab))

    def test_download_info_txt_flow(self):
        tab = self.app.tabs["download"]
        tab.url_var.set("https://youtu.be/abc123")
        tab._set_kind("txt")
        self._stub("download_info_txt", (os.path.join(self.tmp, "info.txt"), "Title"))
        tab.trigger_start()
        self._settle(tab)
        self.assertIn("download_info_txt", self.calls)

    def test_download_bad_url_is_reported(self):
        tab = self.app.tabs["download"]
        tab.url_var.set("not a url")
        tab.trigger_start()
        self.app.update()
        self.assertTrue(self.msgbox.errors)
        self.assertEqual(tab._job, None)

    # -- translation ---------------------------------------------------------
    def test_translate_flow(self):
        tab = self.app.tabs["translate"]
        self.app.show("translate")
        tab.srt_var.set(self.dummy_srt)
        tab.lang_menu.set(self._t(self.main.engine.TRANSLATE_LANGUAGES[2][1]))
        out = os.path.join(self.tmp, "in_de.srt")
        self._stub("translate_srt_file", out)
        tab.trigger_start()
        self._settle(tab)
        call = self.calls["translate_srt_file"]
        self.assertEqual(call["args"][1], self.dummy_srt)
        self.assertEqual(call["kwargs"]["gemini_keys_list"], ["gem-key"])
        self.assertTrue(call["kwargs"]["target_language"])
        self.assertIn("Translat", self._log_text(tab))

    # -- failure + cancel ----------------------------------------------------
    def test_engine_error_is_shown_and_unlocks_ui(self):
        tab = self.app.tabs["transcribe"]
        self.app.settings["transcribe_source"] = "file"
        tab.seg.set(self._t("ui.seg.local_file"))
        tab.path_var.set(self.dummy_media)

        def boom(*a, **k):
            raise RuntimeError("شبکه قطع است")

        self.main.engine.transcribe_file = boom
        tab.trigger_start()
        self._settle(tab)
        self.assertTrue(self.msgbox.errors)
        self.assertIn("شبکه قطع است", str(self.msgbox.errors[-1]))
        self.assertEqual(tab.start_btn.cget("state"), "normal")
        self.assertEqual(tab.cancel_btn.cget("state"), "disabled")

    def test_cancel_path_unlocks_ui(self):
        tab = self.app.tabs["transcribe"]
        self.app.settings["transcribe_source"] = "file"
        tab.seg.set(self._t("ui.seg.local_file"))
        tab.path_var.set(self.dummy_media)

        def cancellable(job, *a, **k):
            job.report(50, "وسط کار", 50)
            job.cancel()
            job._check()          # raises engine.Cancelled
            return {}

        self.main.engine.transcribe_file = cancellable
        tab.trigger_start()
        self._settle(tab)
        self.assertIn("cancelled", self._log_text(tab))
        self.assertEqual(tab.start_btn.cget("state"), "normal")

    # -- misc UI paths -------------------------------------------------------
    def test_progress_panel_renders_details(self):
        tab = self.app.tabs["transcribe"]
        job = tab.make_job()
        job.started = time.monotonic() - 30
        job.report(40, "🎙️ بخش 2/3\n📄 ✅ 🔄 ▫️", 40, "کلید 2/2")
        job.report(40, "🎙️ بخش 2/3\n📄 ✅ 🔄 ▫️", 40, "کلید 2/2")
        self._pump(0.4)
        self.assertEqual(tab.percent_lbl.cget("text"), " 40.0%")
        self.assertIn("بخش 2/3", tab.status_lbl.cget("text"))
        self.assertIn("✅ 🔄", tab.stage_lbl.cget("text"))
        info = tab.info_lbl.cget("text")
        self.assertIn("⏱", info)
        self.assertIn("⏳", info)
        self.assertIn("کلید 2/2", info)
        # Progress must never tick backwards, even if a stage restarts.
        job.report(10, "🏁 مرحله‌ی جدید", 10)
        self._pump(0.3)
        self.assertEqual(tab.percent_lbl.cget("text"), " 40.0%")
        job.report(100, "تمام", 100)
        self._pump(0.3)
        self.assertEqual(tab.percent_lbl.cget("text"), "100.0%")
        self.assertIn("تمام", tab.status_lbl.cget("text"))
        tab.set_running(False)

    def test_settings_save_and_log(self):
        tab = self.app.tabs["settings"]
        self.app.show("settings")
        tab.groq_var.set("gsk_test_key")
        tab.gem_var.set("AIza_test_key")
        tab.out_var.set(os.path.join(self.tmp, "out2"))
        before = len(self.msgbox.infos)
        tab._save()
        self.assertEqual(len(self.msgbox.infos), before + 1)
        self.assertEqual(self.app.settings["groq_key"], "gsk_test_key")
        self.assertEqual(self.app.settings["gemini_key"], "AIza_test_key")
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "out2")))
        self.assertIn("saved", self._log_text(tab))

    def test_shortcut_dispatch_on_real_widgets(self):
        from tests.test_ui_logic import FakeEvent
        app = self.app
        app.show("transcribe")
        app.update()
        self.assertEqual(app._cycle_tab(1), "break")
        self.assertEqual(app.current, "download")
        app.show("transcribe")
        app.update()
        # Ctrl+L clears the current tab's log.
        tab = app.current_tab()
        tab.log("چیزی برای پاک شدن")
        app.update()
        self.assertIn("چیزی", self._log_text(tab))
        app._on_ctrl_press(FakeEvent(keysym="ل", keycode=76, state=0x4))
        app.update()
        self.assertNotIn("چیزی", self._log_text(tab))
        # F1 opens the shortcut help without raising.
        app.show_shortcuts()
        app.update()
        for child in app.winfo_children():
            if isinstance(child, type(app)) or child.winfo_class() == "Toplevel":
                child.destroy()
        app.update()

    def test_tab_switch_and_scale_do_not_break(self):
        for name in ("download", "translate", "settings", "transcribe"):
            self.app.show(name)
            self.app.update()
            self.assertEqual(self.app.current, name)
        self.app._apply_scale(1.3)
        self.app.update()
        self.app._apply_scale(1.0)
        self.app.update()

    def test_first_run_is_english_and_switchable(self):
        """A fresh install (no settings.json) starts in English; Persian is one click away."""
        original = self.main.SETTINGS_PATH
        original_language = self.main.i18n.get_language()
        first_run = os.path.join(self.tmp, "first-run-settings.json")
        if os.path.exists(first_run):
            os.remove(first_run)
        self.main.SETTINGS_PATH = first_run
        app = None
        try:
            app = self.main.App()
            app.update()
            self.assertEqual(self.main.i18n.get_language(), "en",
                             "a first run must default to English")
            english = app.tabs["transcribe"].start_btn.cget("text")
            self.assertTrue(english.startswith("🚀 Start"), english)
            self.assertEqual(app.lang_ui_menu.get(), "English")

            app._on_language("فارسی")
            app.update()
            self.assertEqual(self.main.i18n.get_language(), "fa")
            self.assertNotEqual(app.tabs["transcribe"].start_btn.cget("text"), english)
            self.assertEqual(app.settings["language"], "fa")
            for tab in ("download", "translate", "settings"):
                app.show(tab)
                app.update()

            app._on_close()
            with open(first_run, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["language"], "fa",
                                 "the chosen language must persist")
        finally:
            if app is not None:
                try:
                    app.destroy()
                except Exception:
                    pass
            self.main.SETTINGS_PATH = original
            self.main.i18n.set_language(original_language)

    def test_shutdown_cancels_timers_and_pumps(self):
        # A fresh app so the class-level one survives for the other tests.
        app = self.main.App()
        app.update()
        pump = app.tabs["transcribe"].pump
        self.assertTrue(pump._alive)
        app._on_close()
        self.assertFalse(pump._alive, "pump kept running after close")
        self.assertIsNone(pump._after_id, "pending pump timer not cancelled")
        self.assertEqual(app._after_ids, [], "pending timers not cancelled")
        self.assertTrue(app._closing)

    def test_geometry_restore_clamps_and_survives_garbage(self):
        app = self.main.App()

        def settle(seconds=0.7):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                app.update_idletasks()
                app.update()
                time.sleep(0.02)

        settle()
        if app.winfo_screenwidth() < self.main.MIN_WIDTH + 80:
            app._on_close()
            self.skipTest("screen too small for the minimum window size")

        app.settings["geometry"] = "9999x9999+9000+9000"
        app._restore_geometry()
        settle()
        self.assertGreaterEqual(app.winfo_width(), self.main.MIN_WIDTH)
        self.assertLessEqual(app.winfo_width(), app.winfo_screenwidth())
        self.assertLessEqual(app.winfo_height(), app.winfo_screenheight())

        app.settings["geometry"] = "nonsense"
        app._restore_geometry()
        settle()
        self.assertGreaterEqual(app.winfo_width(), self.main.MIN_WIDTH)

        saved = app._current_geometry()
        self.assertIsNotNone(saved, "a normal window must be saveable")
        app._on_close()
        self.assertIsNotNone(self.main.load_settings().get("geometry"))

    # -- settings: API keys and documentation links --------------------------
    def _settings_tab(self):
        self.app.show("settings")
        self._pump(0.05)
        return self.app.tabs["settings"]

    def test_settings_saves_a_typed_key(self):
        tab = self._settings_tab()
        tab.groq_var.set("gsk_typed_by_hand")
        tab._save()
        self.assertEqual(self.app.settings["groq_key"], "gsk_typed_by_hand")
        with open(self.main.SETTINGS_PATH, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["groq_key"], "gsk_typed_by_hand")
        # The field clears, and its hint now says a key is stored.
        self.assertEqual(tab.groq_var.get(), "")
        self.assertEqual(tab.groq_entry.cget("placeholder_text"),
                         self._t("ui.placeholder.key_saved"))

    def test_settings_keeps_a_key_even_if_the_mask_is_still_in_the_field(self):
        # Regression: the field used to be pre-filled with bullets, so a key
        # typed after them was discarded while the dialog still said "saved".
        tab = self._settings_tab()
        tab.groq_var.set("\u2022" * 8 + "gsk_survives_the_mask")
        tab._save()
        self.assertEqual(self.app.settings["groq_key"], "gsk_survives_the_mask")

    def test_settings_does_not_invent_a_key_from_an_empty_field(self):
        tab = self._settings_tab()
        self.app.settings["groq_key"] = "gsk_already_there"
        tab.groq_var.set("")
        tab._save()
        self.assertEqual(self.app.settings["groq_key"], "gsk_already_there")

    def test_saved_key_reaches_the_engine(self):
        tab = self._settings_tab()
        tab.groq_var.set("gsk_engine_sees_me")
        tab._save()
        real_groq_keys = self._saved["groq_keys"]
        self.assertEqual(real_groq_keys(self.app.settings["groq_key"]),
                         ["gsk_engine_sees_me"])

    def test_settings_links_call_the_url_opener(self):
        tab = self._settings_tab()
        opened = []
        original = self.main.open_url
        self.main.open_url = lambda url: (opened.append(url), True)[1]
        try:
            tab._open_link("https://console.groq.com/keys")
        finally:
            self.main.open_url = original
        self.assertEqual(opened, ["https://console.groq.com/keys"])

    def test_settings_link_failure_shows_the_url_instead_of_nothing(self):
        tab = self._settings_tab()
        original = self.main.open_url
        self.main.open_url = lambda url: False
        try:
            tab._open_link("https://example.test/some-key-page")
        finally:
            self.main.open_url = original
        self.assertTrue(self.msgbox.warnings, "a failed link must say something")
        message = str(self.msgbox.warnings[-1][-1])
        self.assertIn("https://example.test/some-key-page", message)
        self.assertIn("https://example.test/some-key-page", self._log_text(tab))

    def test_status_line_counts_the_saved_key(self):
        # Regression: environment_status() used to count only the key pool, so
        # the settings page kept saying "Groq: 0" after a key was saved.
        real_status = self._saved["environment_status"]
        status = real_status("gsk_counted_here", "")
        self.assertGreaterEqual(status["keys_groq"], 1)

    def test_settings_link_buttons_also_react_to_a_release(self):
        # A touch tap does not always drive CTkButton's internal state machine,
        # so every link button carries its own release binding as well.
        tab = self._settings_tab()

        found = []

        def walk(widget):
            if "Button" in type(widget).__name__:
                try:
                    if str(widget.cget("text")).startswith("Get a"):
                        found.append(widget)
                except Exception:
                    pass
            for child in widget.winfo_children():
                walk(child)

        walk(tab)
        self.assertGreaterEqual(len(found), 2, "expected the 'Get a ...' links")
        for button in found:
            # CTkButton.bind() forwards to its canvas, which is what receives
            # the pointer event, so check the binding there.
            canvas = getattr(button, "_canvas", button)
            self.assertTrue(canvas.bind("<ButtonRelease-1>"),
                            "link canvas has no release binding")
            # The whole row must be a target too: a tap that misses the text by
            # a few pixels still has to open the page.  binding it on the row's
            # raw canvas is what makes that work (CTkFrame.bind drops it).
            row_canvas = getattr(button.master, "_canvas", None)
            self.assertIsNotNone(row_canvas, "link row has no canvas")
            self.assertTrue(row_canvas.bind("<ButtonRelease-1>"),
                            "link row canvas has no release binding")

    def test_open_url_rejects_an_empty_url(self):
        self.assertFalse(self.main.open_url(""))
        self.assertFalse(self.main.open_url("   "))


if __name__ == "__main__":
    unittest.main(verbosity=2)