"""i18n tests: catalog integrity, English default, translation plumbing.

These run without a display and without network access.
"""

import io
import os
import re
import sys
import unittest

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import i18n  # noqa: E402

PERSIAN = re.compile(r"[\u0600-\u06FF]")
SOURCE_FILES = ["main.py", "engine.py",
                "core/downloader.py", "core/audio.py", "core/srt_utils.py",
                "core/transcribe.py", "core/translate.py"]
KEY_USE = re.compile(r'\bt\(\s*"([A-Za-z0-9_.]+)"')


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(i18n.set_language, i18n.DEFAULT_LANGUAGE)
        i18n.set_language("en")

    def test_english_is_the_default(self):
        self.assertEqual(i18n.DEFAULT_LANGUAGE, "en")
        self.assertEqual(i18n.get_language(), "en")
        self.assertEqual(i18n.language_codes()[0], "en")

    def test_every_used_key_exists(self):
        missing = {}
        for name in SOURCE_FILES:
            path = os.path.join(ROOT, name)
            with io.open(path, encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    for key in KEY_USE.findall(line):
                        if key not in i18n.catalog():
                            missing.setdefault(key, []).append(f"{name}:{lineno}")
        self.assertEqual(missing, {}, f"keys used but not defined: {missing}")

    def test_engine_label_constants_resolve(self):
        import engine
        for attr in ("LANGUAGES", "SUBTITLE_STYLES", "PROVIDERS",
                     "DL_AUDIO_QUALITIES", "DL_VIDEO_QUALITIES",
                     "TRANSLATE_LANGUAGES", "TRANSLATE_STYLES"):
            for entry in getattr(engine, attr):
                key = entry[1]
                self.assertIn(key, i18n.catalog(), f"{attr} uses {key}")
                for code in i18n.language_codes():
                    i18n.set_language(code)
                    self.assertTrue(i18n.t(key).strip(),
                                    f"{attr} {key} is empty in {code}")
        for mapping in ("DL_VIDEO_LABELS", "DL_AUDIO_LABELS"):
            for code, key in getattr(engine, mapping).items():
                self.assertIn(key, i18n.catalog(), f"{mapping}[{code}]")

    def test_no_entry_is_incomplete(self):
        broken = {key: langs for key, langs in i18n.catalog().items()
                  if not (langs.get("en") or "").strip()
                  or not (langs.get("fa") or "").strip()}
        self.assertEqual(broken, {})

    def test_no_persian_leaks_into_english(self):
        leaked = {key: langs["en"] for key, langs in i18n.catalog().items()
                  if PERSIAN.search(langs.get("en") or "")}
        self.assertEqual(leaked, {})

    def test_keys_are_unique_across_modules(self):
        seen = {}
        clashes = {}
        for module, entries in i18n.entries_by_module().items():
            for key in entries:
                if key in seen:
                    clashes[key] = (seen[key], module)
                seen[key] = module
        self.assertEqual(clashes, {})

    def test_key_namespaces_are_lower_snake(self):
        bad = [key for key in i18n.catalog()
               if not re.fullmatch(r"[a-z0-9_]+(\.[a-z0-9_]+)+", key)]
        self.assertEqual(bad[:10], [], f"{len(bad)} badly named keys")


class PlaceholderTests(unittest.TestCase):
    """Every t("key", name=...) call must agree with the catalog text."""

    @staticmethod
    def call_sites():
        """Yield (file, line, key, {kwargs}) for statically readable calls."""
        import ast
        for name in SOURCE_FILES:
            path = os.path.join(ROOT, name)
            with io.open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not (isinstance(func, ast.Name) and func.id == "t"):
                    continue
                if not node.args or not isinstance(node.args[0], ast.Constant):
                    continue
                key = node.args[0].value
                if not isinstance(key, str):
                    continue
                if any(kw.arg is None for kw in node.keywords):
                    continue                     # t(key, **data): not static
                kwargs = {kw.arg for kw in node.keywords}
                yield name, node.lineno, key, kwargs

    def test_call_sites_match_catalog_placeholders(self):
        catalog = i18n.catalog()
        problems = []
        for name, lineno, key, kwargs in self.call_sites():
            entry = catalog.get(key)
            if entry is None:
                problems.append(f"{name}:{lineno} unknown key {key}")
                continue
            for lang in i18n.language_codes():
                wanted = set(re.findall(r"\{(\w+)(?:[!:.][^{}]*)?\}", entry[lang]))
                if wanted - kwargs:
                    problems.append(
                        f"{name}:{lineno} {key} [{lang}] needs "
                        f"{sorted(wanted - kwargs)} but passes {sorted(kwargs)}")
                elif kwargs - wanted:
                    problems.append(
                        f"{name}:{lineno} {key} [{lang}] passes unused "
                        f"{sorted(kwargs - wanted)}")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_plural_or_indexed_placeholders_are_named(self):
        """No positional ``{}`` fields: callers always use keywords."""
        offenders = [key for key, langs in i18n.catalog().items()
                     for text in langs.values() if "{}" in text]
        self.assertEqual(offenders, [])


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(i18n.set_language, i18n.DEFAULT_LANGUAGE)
        i18n.set_language("en")

    def test_switching_returns_localised_text(self):
        english = i18n.t("ui.btn.start")
        self.assertEqual(english, "🚀 Start")
        i18n.set_language("fa")
        self.assertNotEqual(i18n.t("ui.btn.start"), english)
        self.assertIn("شروع", i18n.t("ui.btn.start"))

    def test_unknown_language_falls_back_to_english(self):
        i18n.set_language("fa")
        self.assertEqual(i18n.set_language("klingon"), "en")
        self.assertEqual(i18n.t("ui.btn.cancel"), "⛔ Cancel")

    def test_unknown_key_returns_the_key(self):
        self.assertEqual(i18n.t("no.such.key"), "no.such.key")

    def test_interpolation(self):
        self.assertIn("C:/x.srt", i18n.t("ui.log.log_saved", v1="C:/x.srt"))

    def test_missing_placeholder_does_not_raise(self):
        text = i18n.t("ui.log.log_saved")          # {v1} left unfilled
        self.assertIn("{v1}", text)

    def test_rtl_detection(self):
        self.assertTrue(i18n.is_rtl("fa"))
        self.assertFalse(i18n.is_rtl("en"))

    def test_language_labels_are_self_describing(self):
        self.assertEqual(i18n.language_label("en"), "English")
        self.assertEqual(i18n.language_label("fa"), "فارسی")
        self.assertEqual(i18n.language_label("xx"), "xx")


class SettingsDefaultTests(unittest.TestCase):
    """The app must greet a first-time user in English."""

    def test_defaults_request_english(self):
        import main  # needs the CustomTkinter stub or the real package
        self.assertEqual(main.DEFAULTS["language"], "en")

    def test_missing_language_key_means_english(self):
        import main
        settings = dict(main.DEFAULTS)
        settings.pop("language", None)
        self.assertEqual(settings.get("language", i18n.DEFAULT_LANGUAGE), "en")


if __name__ == "__main__":
    unittest.main(verbosity=2)