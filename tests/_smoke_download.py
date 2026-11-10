"""Manual network smoke test for the yt-dlp layer (needs internet).

Run:  set PYTHONPATH=C:\\Users\\parsa\\arion-test-deps && python tests\\_smoke_download.py
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import engine  # noqa: E402
from core import downloader  # noqa: E402

URL = os.environ.get("ARION_TEST_URL",
                     "https://www.youtube.com/watch?v=jNQXAC9IVRw")  # 19s test video
OUT = os.path.join(ROOT, "tests", "_artifacts", "download")


def main():
    os.makedirs(OUT, exist_ok=True)
    print("yt-dlp available:", downloader.ytdlp_available())
    print("supports --remote-components:", downloader.supports("--remote-components"))
    print("supports --progress-template:", downloader.supports("--progress-template"))

    events = []

    def progress(stage_pct, label, overall=None, note=""):
        events.append((overall, label))
        print(f"  progress: overall={overall!s:>6} stage={stage_pct!s:>6} {label!r} {note}")

    job = engine.Job(progress_cb=progress, log_cb=lambda line: print("  log:", line))
    job.started = time.monotonic()

    print("\n== probe_sizes ==")
    try:
        info = engine.probe_sizes(URL, job=job)
        print("  title:", info.get("title"))
        print("  duration:", info.get("duration"))
        print("  video:", info.get("video"))
        print("  audio:", info.get("audio"))
    except Exception as exc:
        print("  PROBE FAILED:", type(exc).__name__, exc)

    print("\n== download_subtitles ==")
    try:
        path, target, kind, title = engine.download_subtitles(job, URL, OUT)
        print(f"  saved: {path} (target={target} kind={kind}) size={os.path.getsize(path)}")
        with open(path, encoding="utf-8", errors="replace") as f:
            print("  head:", f.read(160).replace("\n", " | "))
    except Exception as exc:
        print("  SUBTITLE FAILED:", type(exc).__name__, exc)

    print("\n== download audio (real transfer, checks live progress) ==")
    try:
        dl_events = []

        def dl_progress(stage_pct, label, overall=None, note=""):
            dl_events.append((overall, label))
            if len(dl_events) % 5 == 0 or overall in (None, 100):
                print(f"  progress: overall={overall!s:>6} {label!r} {note}")

        djob = engine.Job(progress_cb=dl_progress,
                          log_cb=lambda line: print("  log:", line))
        djob.started = time.monotonic()
        path = engine.download_media(djob, URL, OUT, quality="audio")
        print("  saved:", path, "size:", os.path.getsize(path))
        overalls = [e[0] for e in dl_events if isinstance(e[0], (int, float))]
        print("  samples:", len(overalls),
              "| monotonic:", all(b >= a for a, b in zip(overalls, overalls[1:])),
              "| range:", (min(overalls), max(overalls)) if overalls else None)
        stages = [e[1] for e in dl_events if e[1]]
        print("  distinct stage labels:", len(set(stages)))
        print("  last stage:", stages[-1] if stages else None)
    except Exception as exc:
        print("  AUDIO FAILED:", type(exc).__name__, exc)

    print("\n== progress samples ==")
    parsed = [p for p in (downloader.parse_progress_line(e[1]) for e in events) if p]
    print("  parsed progress lines:", len(parsed), parsed[:3])
    overalls = [e[0] for e in events if isinstance(e[0], (int, float))]
    print("  monotonic:", all(b >= a for a, b in zip(overalls, overalls[1:])),
          "| range:", (min(overalls), max(overalls)) if overalls else None)


if __name__ == "__main__":
    main()