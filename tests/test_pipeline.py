"""End-to-end pipeline test with the speech API stubbed out.

Runs the real ffmpeg stages (compress → silence scan → split), replaces only the
network transcription call, and checks the assembled SRT: chunk offsets, output
location (final_dir, not work_dir), progress monotonicity and stats.

Run:  python -m unittest discover -s tests -v
"""

import os
import shutil
import subprocess
import sys
import unittest

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

if "dotenv" not in sys.modules:
    import types
    _dotenv = types.ModuleType("dotenv")
    _dotenv.load_dotenv = lambda *a, **k: None
    sys.modules["dotenv"] = _dotenv
if "requests" not in sys.modules:
    import types
    _requests = types.ModuleType("requests")
    _requests.post = lambda *a, **k: None
    _requests.get = lambda *a, **k: None
    sys.modules["requests"] = _requests

from core import audio, config, srt_utils, transcribe  # noqa: E402

ARTIFACTS = os.path.join(ROOT, "tests", "_artifacts", "pipeline")


def ffmpeg_available():
    return bool(audio.available() and shutil.which("ffmpeg"))


@unittest.skipUnless(ffmpeg_available(), "ffmpeg is required")
class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        shutil.rmtree(ARTIFACTS, ignore_errors=True)
        os.makedirs(ARTIFACTS, exist_ok=True)
        cls.tone = os.path.join(ARTIFACTS, "tone.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=150", "-ac", "1", "-ar", "16000",
             cls.tone],
            capture_output=True, check=True)
        # Small chunks so the 150 s tone splits into three parts.
        cls._orig_chunk_minutes = config.CHUNK_MINUTES
        config.CHUNK_MINUTES = 1

    @classmethod
    def tearDownClass(cls):
        config.CHUNK_MINUTES = cls._orig_chunk_minutes
        shutil.rmtree(ARTIFACTS, ignore_errors=True)

    def _run(self, output_format="both", **kwargs):
        calls = []

        def fake_chunk(rotator, chunk, lang, style, cancel_check=None):
            calls.append(chunk)
            if cancel_check:
                cancel_check()
            return ("1\n00:00:00,000 --> 00:00:02,000\nبخش "
                    f"{len(calls)}\n"), "fa"

        original = transcribe._transcribe_chunk_groq
        transcribe._transcribe_chunk_groq = fake_chunk
        events = []
        stats = {}
        try:
            work = os.path.join(ARTIFACTS, "work")
            final = os.path.join(ARTIFACTS, "final")
            result = transcribe.transcribe_file(
                ["dummy-key"], self.tone, work, language="fa",
                output_format=output_format,
                progress=lambda *a: events.append(a),
                provider="groq", stats=stats, final_dir=final, **kwargs)
        finally:
            transcribe._transcribe_chunk_groq = original
        return result, events, stats, calls, final, work

    def test_pipeline_outputs_and_offsets(self):
        result, events, stats, calls, final, work = self._run()
        self.assertTrue(result.get("srt"), "no srt produced")
        self.assertTrue(result.get("txt"), "no txt produced")

        # The finished files belong in the folder the user chose.
        self.assertEqual(os.path.dirname(os.path.abspath(result["srt"])),
                         os.path.abspath(final))
        self.assertNotEqual(os.path.abspath(final), os.path.abspath(work))
        self.assertTrue(os.path.exists(result["srt"]))
        self.assertTrue(os.path.exists(result["txt"]))
        self.assertGreater(os.path.getsize(result["srt"]), 0)

        # Intermediate work stays in work_dir.
        self.assertTrue(os.path.isdir(os.path.join(work, "chunks")))
        self.assertTrue(os.path.exists(os.path.join(work, "audio.mp3")))

        with open(result["srt"], encoding="utf-8") as f:
            merged = f.read()
        blocks = [b for b in merged.strip().split("\n\n") if b.strip()]
        self.assertEqual(len(calls), 3, f"expected 3 chunks, got {calls}")
        self.assertEqual(len(blocks), 3)

        starts = []
        prev_end = -1.0
        for idx, block in enumerate(blocks, 1):
            lines = block.split("\n")
            self.assertEqual(lines[0], str(idx), "numbering must be continuous")
            start_s, end_s = [x.strip() for x in lines[1].split("-->")]
            start = srt_utils.parse_srt_time(start_s).total_seconds()
            end = srt_utils.parse_srt_time(end_s).total_seconds()
            self.assertLess(start, end)
            self.assertGreaterEqual(start, prev_end - 1.0)  # no overlap
            prev_end = end
            starts.append(start)

        # Chunk 2 and 3 cues must be shifted by their chunk offsets. A pure tone
        # has no silence, so the cuts fall back to even thirds of 150 s.
        self.assertLess(starts[0], 3.0)
        self.assertGreater(starts[1], 45.0)
        self.assertGreater(starts[2], 95.0)
        self.assertIn("بخش 1", blocks[0])
        self.assertIn("بخش 3", blocks[2])

        with open(result["txt"], encoding="utf-8") as f:
            txt = f.read()
        self.assertIn("بخش 2", txt)

        # Progress must be monotonic and effectively finish.
        overalls = [e[2] for e in events if len(e) > 2 and isinstance(e[2], (int, float))]
        self.assertGreater(len(overalls), 5, "too few progress updates")
        self.assertTrue(all(b >= a for a, b in zip(overalls, overalls[1:])),
                        f"progress went backwards: {overalls}")
        self.assertGreaterEqual(max(overalls), 99.0)
        # Every update carries a human label; key notes come from the rotator.
        labels = [e[1] for e in events if len(e) > 1 and e[1]]
        self.assertTrue(all(isinstance(x, str) and x.strip() for x in labels))
        self.assertTrue(any("ترنسکرایب بخش" in x for x in labels))
        self.assertIn("chunk_count", stats)
        self.assertEqual(stats["chunk_count"], 3)
        self.assertEqual(stats["chunks"], 3)
        self.assertEqual(stats["provider"], "groq")
        self.assertEqual(stats["language"], "fa")

    def test_cancel_stops_pipeline(self):
        class Boom(Exception):
            pass

        def stop():
            raise Boom()

        with self.assertRaises(Boom):
            transcribe.transcribe_file(
                ["dummy-key"], self.tone, os.path.join(ARTIFACTS, "work2"),
                output_format="srt", provider="groq", cancel_check=stop)

    def test_txt_only_format(self):
        result, _events, _stats, _calls, _final, _work = self._run(
            output_format="txt")
        self.assertNotIn("srt", result)
        self.assertTrue(result.get("txt"))


if __name__ == "__main__":
    unittest.main(verbosity=2)