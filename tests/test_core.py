"""Regression tests for the Arion core modules (no network, no ffmpeg needed).

Run:  python -m unittest discover -s tests -v
"""

import os
import shutil
import sys
import types
import unittest

# The Windows console defaults to cp1252; Persian assertion messages must not
# crash the test runner.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# --- stub optional third-party imports so the core modules import offline -----
if "dotenv" not in sys.modules:
    _dotenv = types.ModuleType("dotenv")
    _dotenv.load_dotenv = lambda *a, **k: None
    sys.modules["dotenv"] = _dotenv

if "requests" not in sys.modules:
    _requests = types.ModuleType("requests")
    _requests.post = lambda *a, **k: None
    _requests.get = lambda *a, **k: None
    sys.modules["requests"] = _requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import audio, downloader, srt_utils, translate  # noqa: E402
import engine  # noqa: E402

ARTIFACTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_artifacts")


class ProgressLineTests(unittest.TestCase):
    """yt-dlp's --progress-template output must parse in every NA combination.

    ``download:`` is a template *type*, so real output is the bare body — the
    parser must work with (and without) that tag.
    """

    def test_real_bare_line_from_installed_ytdlp(self):
        # Captured verbatim from yt-dlp 2026.10.26:
        #   --progress-template "download:%(progress.percent)s|%(progress.speed)s|…"
        line = "NA|15641.211888139902|16|1024|252182|NA"
        info = downloader.parse_progress_line(line)
        self.assertIsNotNone(info, "bare progress line must parse")
        self.assertAlmostEqual(info["pct"], 100.0 * 1024 / 252182, places=4)
        self.assertTrue(info["speed"].endswith("/s"), info["speed"])
        self.assertEqual(info["eta"], "00:16")

    def test_bare_line_with_percent_and_speed_units(self):
        info = downloader.parse_progress_line(
            "42.5%|1.20MiB/s|00:10|44983910|105906176|NA")
        self.assertAlmostEqual(info["pct"], 42.5)
        self.assertEqual(info["speed"], "1.20MiB/s")
        self.assertEqual(info["eta"], "00:10")

    def test_full_line_with_type_tag(self):
        line = ("download: 42.5%|1.20MiB/s|00:10|44983910.0|105906176.0|NA")
        info = downloader.parse_progress_line(line)
        self.assertAlmostEqual(info["pct"], 42.5)
        self.assertEqual(info["speed"], "1.20MiB/s")
        self.assertEqual(info["eta"], "00:10")
        self.assertAlmostEqual(info["downloaded"], 44983910.0)
        self.assertAlmostEqual(info["total"], 105906176.0)

    def test_ansi_wrapped_line(self):
        line = "\x1b[0;94mNA|1.2MiB/s|NA|1000.0|2000.0|NA\x1b[0m"
        info = downloader.parse_progress_line(line)
        self.assertAlmostEqual(info["pct"], 50.0)
        self.assertEqual(info["speed"], "1.2MiB/s")
        self.assertEqual(info["eta"], "")

    def test_unknown_percent_falls_back_to_bytes(self):
        info = downloader.parse_progress_line("NA|NA|NA|250.0|1000.0|NA")
        self.assertAlmostEqual(info["pct"], 25.0)

    def test_unknown_total_uses_estimate(self):
        info = downloader.parse_progress_line("NA|NA|NA|500.0|NA|2000.0")
        self.assertAlmostEqual(info["pct"], 25.0)

    def test_destination_line_is_not_progress(self):
        # A very common line that must never be mistaken for progress.
        self.assertIsNone(downloader.parse_progress_line(
            "[download] Destination: tests\\a.webm"))
        self.assertIsNone(downloader.parse_progress_line(
            "[download]  50.0% of 1.00MiB at 1.00MiB/s ETA 00:10"))

    def test_garbage_returns_none(self):
        self.assertIsNone(downloader.parse_progress_line("NA|NA|NA|NA|NA|NA"))
        self.assertIsNone(downloader.parse_progress_line("[youtube] Extracting URL"))
        self.assertIsNone(downloader.parse_progress_line(""))
        self.assertIsNone(downloader.parse_progress_line(None))

    def test_percent_is_clamped(self):
        info = downloader.parse_progress_line("150.0|NA|NA|NA|NA|NA")
        self.assertEqual(info["pct"], 100.0)

    def test_eta_formatting(self):
        self.assertEqual(downloader._fmt_eta(16), "00:16")
        self.assertEqual(downloader._fmt_eta(3725), "1:02:05")
        self.assertEqual(downloader._fmt_eta("00:10"), "00:10")
        self.assertEqual(downloader._fmt_eta("NA"), "")
        self.assertEqual(downloader._fmt_eta(-4), "")

    def test_speed_formatting(self):
        self.assertEqual(downloader._fmt_speed(2048), "2KB/s")
        self.assertEqual(downloader._fmt_speed(5 * 1024 * 1024), "5.0MB/s")
        self.assertEqual(downloader._fmt_speed("1.20MiB/s"), "1.20MiB/s")
        self.assertEqual(downloader._fmt_speed("NA"), "")
        self.assertEqual(downloader._fmt_speed(None), "")


class FormatTests(unittest.TestCase):
    def test_video_format_by_height(self):
        self.assertIn("height<=2160", downloader.video_format("2160"))
        self.assertIn("height<=360", downloader.video_format(360))
        self.assertIn("bestvideo+bestaudio", downloader.video_format("best"))
        self.assertIn("bestvideo+bestaudio", downloader.video_format("weird"))

    def test_sanitize_filename(self):
        self.assertEqual(downloader.sanitize_filename('a/b:c*?"<>|'), "a_b_c")
        self.assertEqual(downloader.sanitize_filename(""), "file")


class SrtTests(unittest.TestCase):
    def test_parse_time_accepts_dot_and_short_form(self):
        self.assertEqual(srt_utils.seconds_to_srt_time(
            srt_utils.parse_srt_time("00:01:02.500").total_seconds()),
            "00:01:02,500")
        self.assertEqual(srt_utils.seconds_to_srt_time(
            srt_utils.parse_srt_time("01:02,500").total_seconds()),
            "00:01:02,500")

    def test_merge_sorts_and_removes_overlap(self):
        tmp = os.path.join(ARTIFACTS, "merge")
        os.makedirs(tmp, exist_ok=True)
        try:
            p1 = os.path.join(tmp, "1.srt")
            p2 = os.path.join(tmp, "2.srt")
            with open(p1, "w", encoding="utf-8") as f:
                f.write("1\n00:00:00,000 --> 00:00:05,000\none\n\n"
                        "2\n00:00:05,000 --> 00:00:09,000\ntwo\n")
            with open(p2, "w", encoding="utf-8") as f:
                # starts before the first chunk's end -> must be trimmed
                f.write("1\n00:00:00,000 --> 00:00:03,000\ntwo\n\n"
                        "2\n00:00:04,000 --> 00:00:08,000\nthree\n")
            merged = srt_utils.merge_srt_chunks([p2, p1], [10.0, 0.0])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        blocks = merged.strip().split("\n\n")
        # p2 is offset by +10s, so its "two" is a *different* cue, not a duplicate.
        self.assertEqual(len(blocks), 4)
        self.assertTrue(blocks[0].startswith("1\n00:00:00,000"))
        self.assertIn("one", blocks[0])
        # numbering is continuous and timings never overlap
        prev_end = None
        for idx, block in enumerate(blocks, 1):
            lines = block.split("\n")
            self.assertEqual(lines[0], str(idx))
            start, end = [x.strip() for x in lines[1].split("-->")]
            self.assertLess(srt_utils.parse_srt_time(start),
                            srt_utils.parse_srt_time(end))
            if prev_end is not None:
                self.assertGreaterEqual(srt_utils.parse_srt_time(start), prev_end)
            prev_end = srt_utils.parse_srt_time(end)

    def test_merge_drops_identical_overlap(self):
        tmp = os.path.join(ARTIFACTS, "merge_dup")
        os.makedirs(tmp, exist_ok=True)
        try:
            p1 = os.path.join(tmp, "a.srt")
            p2 = os.path.join(tmp, "b.srt")
            with open(p1, "w", encoding="utf-8") as f:
                f.write("1\n00:00:00,000 --> 00:00:05,000\nhello\n")
            with open(p2, "w", encoding="utf-8") as f:
                # same text, inside the first cue -> must be dropped once
                f.write("1\n00:00:00,000 --> 00:00:04,000\nhello\n")
            merged = srt_utils.merge_srt_chunks([p1, p2], [0.0, 0.0])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(merged.count("hello"), 1)

    def test_plain_text(self):
        srt = "1\n00:00:00,000 --> 00:00:01,000\nhello\n\n" \
              "2\n00:00:01,000 --> 00:00:02,000\nworld"
        self.assertEqual(srt_utils.srt_to_plain_text(srt), "hello\nworld")

    def test_build_srt_skips_inverted_times(self):
        out = srt_utils.build_srt(
            [{"start": 5, "end": 5, "text": "x"},
             {"start": 0, "end": 2, "text": "y"}], [], srt_utils.STYLE_SENTENCE)
        self.assertIn("y", out)
        self.assertIn("00:00:00,000", out)


class TranslateParsingTests(unittest.TestCase):
    def test_parse_srt_with_bom_and_crlf(self):
        raw = "\ufeff1\r\n00:00:00,000 --> 00:00:01,000\r\nسلام\r\n\r\n" \
              "2\r\n00:00:01,000 --> 00:00:02,000\r\nworld\r\n"
        items = translate.parse_srt(raw)
        self.assertEqual([it["index"] for it in items], [1, 2])
        self.assertEqual(items[0]["text"], "سلام")

    def test_parse_translated_roundtrip(self):
        items = [{"index": 1, "time": "00:00:00,000 --> 00:00:01,000",
                  "text": "hello"}]
        payload = "1\nسلام\n\n2\nدنیا\n"
        parsed = translate._parse_translated(payload)
        self.assertEqual(parsed, {1: "سلام", 2: "دنیا"})
        out = translate.build_srt(items)
        self.assertTrue(out.startswith("1\n00:00:00,000"))
        self.assertIn("hello", out)


class JobProgressTests(unittest.TestCase):
    def _job(self):
        events = []
        job = engine.Job(progress_cb=lambda *a: events.append(a),
                         log_cb=events.append)
        return job, events

    def test_progress_is_monotonic(self):
        job, _ = self._job()
        job.report(50, "a", 40)
        job.report(10, "b", 20)          # stage restarted; overall must not drop
        self.assertAlmostEqual(job.overall, 40)
        job.report(100, "c", 70)
        self.assertAlmostEqual(job.overall, 70)

    def test_snapshot_has_eta_after_progress(self):
        job, _ = self._job()
        job.started = 0.0
        job.report(50, "half", 50)
        import time as _time
        job.started = _time.monotonic() - 100.0
        snap = job.snapshot()
        self.assertGreater(snap["eta"], 50)
        self.assertLess(snap["eta"], 150)

    def test_cancel_raises(self):
        job, _ = self._job()
        job._check()  # no-op
        job.cancel()
        with self.assertRaises(engine.Cancelled):
            job._check()

    def test_download_progress_maps_into_span(self):
        job, events = self._job()
        job.started = 0.0
        cb = job.dl_progress(start=20, span=80)
        cb(pct=50.0, speed="1MiB/s", eta="00:10")
        self.assertAlmostEqual(job.overall, 60.0)
        cb(message="مرحله‌ی بعد")
        self.assertTrue(any(e == "مرحله‌ی بعد" for e in events),
                        f"log message missing: {events!r}")

    def test_report_never_above_hundred(self):
        job, _ = self._job()
        job.report(100, "x", 180)
        self.assertAlmostEqual(job.overall, 100.0)


class CutPointTests(unittest.TestCase):
    def test_cut_points_inside_silence(self):
        points = audio.find_cut_points(60, 3, [(18, 22), (38, 42)])
        self.assertEqual(points[0], 0.0)
        self.assertEqual(points[-1], 60)
        self.assertAlmostEqual(points[1], 20.0)
        self.assertAlmostEqual(points[2], 40.0)

    def test_single_chunk_returns_whole_file(self):
        self.assertEqual(audio.find_cut_points(60, 1, []), [0.0, 60])


if __name__ == "__main__":
    unittest.main(verbosity=2)