"""Unit tests for the free OpenRouter reviewer used by deep mode."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import openrouter, transcribe  # noqa: E402

SRT = """1
00:00:01,000 --> 00:00:03,000
salam donya

2
00:00:03,000 --> 00:00:06,000
in yek test ast
"""

FIXED = """1
00:00:01,000 --> 00:00:03,000
سلام دنیا

2
00:00:03,000 --> 00:00:06,000
این یک تست است
"""


class _Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _Session:
    """Records each call and replays a scripted list of responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers,
                           "timeout": timeout})
        return self.responses.pop(0)


def _chat(text, status=200, raw_text=""):
    return _Resp(status, {"choices": [{"message": {"content": text}}]}, raw_text)


class CleanSrtTests(unittest.TestCase):
    def test_markdown_fences_are_stripped(self):
        text = "Sure!\n```srt\n" + FIXED + "```\nHope that helps."
        self.assertEqual(openrouter._clean_srt(text).strip(), FIXED.strip())

    def test_chatter_without_timestamps_is_rejected(self):
        self.assertEqual(openrouter._clean_srt("I cannot do that."), "")


class RefineTests(unittest.TestCase):
    def test_a_good_reply_becomes_the_corrected_srt(self):
        session = _Session([_chat("```srt\n" + FIXED + "```")])
        status, out = openrouter.refine(SRT, "sk-or-1", "vendor/model:free",
                                        session=session)
        self.assertEqual(status, openrouter.OK)
        self.assertEqual(out.strip(), FIXED.strip())
        call = session.calls[0]
        self.assertTrue(call["url"].endswith("/chat/completions"))
        self.assertEqual(call["json"]["model"], "vendor/model:free")
        self.assertEqual(call["headers"]["Authorization"], "Bearer sk-or-1")
        self.assertIn("--- SRT to review ---", call["json"]["messages"][1]["content"])

    def test_rate_limit_bad_key_and_missing_model_are_distinguished(self):
        for status_code, expected in ((429, openrouter.RATE),
                                      (401, openrouter.BAD_KEY),
                                      (404, openrouter.MODEL)):
            session = _Session([_Resp(status_code, text="nope")])
            status, _detail = openrouter.refine(SRT, "k", "m", session=session)
            self.assertEqual(status, expected, f"HTTP {status_code}")

    def test_an_empty_key_never_reaches_the_network(self):
        session = _Session([])
        status, _detail = openrouter.refine(SRT, "  ", "m", session=session)
        self.assertEqual(status, openrouter.BAD_KEY)
        self.assertEqual(session.calls, [])

    def test_a_reply_without_srt_is_an_error(self):
        session = _Session([_chat("Sorry, I cannot.")])
        status, _detail = openrouter.refine(SRT, "k", "m", session=session)
        self.assertEqual(status, openrouter.ERROR)


class RefinePipelineTests(unittest.TestCase):
    def test_the_reviewer_returns_the_polished_text(self):
        seen = []

        def fake_refine(text, key, model, **_kw):
            seen.append((key, model))
            return openrouter.OK, FIXED

        real = openrouter.refine
        openrouter.refine = fake_refine
        try:
            out = transcribe._refine_srt(SRT, "/tmp", None, ["k1"],
                                         provider="openrouter",
                                         models=["m1", "m2"])
        finally:
            openrouter.refine = real
        self.assertEqual(out, FIXED)
        self.assertEqual(seen, [("k1", "m1")])

    def test_a_retired_model_moves_to_the_next_one(self):
        seen = []

        def fake_refine(text, key, model, **_kw):
            seen.append(model)
            if model == "gone":
                return openrouter.MODEL, "not found"
            return openrouter.OK, FIXED

        real = openrouter.refine
        openrouter.refine = fake_refine
        try:
            out = transcribe._refine_srt(SRT, "/tmp", None, ["k1"],
                                         provider="openrouter",
                                         models=["gone", "alive"])
        finally:
            openrouter.refine = real
        self.assertEqual(out, FIXED)
        self.assertEqual(seen, ["gone", "alive"])

    def test_a_rate_limit_moves_to_the_next_key(self):
        seen = []

        def fake_refine(text, key, model, **_kw):
            seen.append(key)
            if key == "limited":
                return openrouter.RATE, "429"
            return openrouter.OK, FIXED

        real = openrouter.refine
        openrouter.refine = fake_refine
        try:
            out = transcribe._refine_srt(SRT, "/tmp", None, ["limited", "good"],
                                         provider="openrouter", models=["m1"])
        finally:
            openrouter.refine = real
        self.assertEqual(out, FIXED)
        self.assertEqual(seen, ["limited", "good"])

    def test_every_model_failing_keeps_the_transcript(self):
        real = openrouter.refine
        openrouter.refine = lambda *a, **k: (openrouter.ERROR, "boom")
        try:
            out = transcribe._refine_srt(SRT, "/tmp", None, ["k1"],
                                         provider="openrouter", models=["a", "b"])
        finally:
            openrouter.refine = real
        self.assertEqual(out, SRT)

    def test_no_keys_means_no_review(self):
        self.assertEqual(
            transcribe._refine_srt(SRT, "/tmp", None, [], provider="openrouter"),
            SRT)


class EngineKeyTests(unittest.TestCase):
    def setUp(self):
        import engine
        self.engine = engine
        self.engine_key = "sk-or-saved"

    def test_the_saved_key_comes_first_and_duplicates_are_dropped(self):
        import engine
        real_load = engine.keypool.load_keys
        engine.keypool.load_keys = lambda provider: ([self.engine_key]
                                                     if provider == "openrouter" else [])
        try:
            keys = engine.openrouter_keys(self.engine_key)
        finally:
            engine.keypool.load_keys = real_load
        self.assertEqual(keys, [self.engine_key])

    def test_the_environment_status_counts_the_openrouter_key(self):
        import engine
        real_load = engine.keypool.load_keys
        engine.keypool.load_keys = lambda provider: []
        try:
            status = engine.environment_status("", "", "sk-or-1")
        finally:
            engine.keypool.load_keys = real_load
        self.assertEqual(status["keys_openrouter"], 1)

    def test_deep_keys_follows_the_selected_reviewer(self):
        import engine
        real_load = engine.keypool.load_keys
        engine.keypool.load_keys = lambda provider: []
        try:
            self.assertEqual(engine.deep_keys("openrouter", openrouter_key="a"), ["a"])
            self.assertEqual(engine.deep_keys("gemini", gemini_key="b"), ["b"])
        finally:
            engine.keypool.load_keys = real_load

    def test_test_api_key_reports_an_openrouter_failure(self):
        import engine
        real = engine.openrouter.check_key
        engine.openrouter.check_key = lambda key, **k: (False, "HTTP 401: nope")
        try:
            ok, message = engine.test_api_key("openrouter", "sk-bad")
        finally:
            engine.openrouter.check_key = real
        self.assertFalse(ok)
        self.assertIn("401", message)

    def test_test_api_key_accepts_a_working_openrouter_key(self):
        import engine
        real = engine.openrouter.check_key
        engine.openrouter.check_key = lambda key, **k: (True, "usage=0 limit=50")
        try:
            ok, message = engine.test_api_key("openrouter", "sk-good")
        finally:
            engine.openrouter.check_key = real
        self.assertTrue(ok)
        self.assertIn("OpenRouter", message)


class ModelListTests(unittest.TestCase):
    def test_default_models_are_free(self):
        models = openrouter.models()
        self.assertTrue(models, "no OpenRouter models configured")
        for model in models:
            self.assertTrue(model.endswith(":free"), model)


if __name__ == "__main__":
    unittest.main()