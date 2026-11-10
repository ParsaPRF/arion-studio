"""Manual integration check: YouTube link -> audio download -> subtitle pipeline.

Only the speech-API call is stubbed; yt-dlp, ffmpeg, chunking, merging and the
output files are all real. Needs internet.

Run:  python tests\\_smoke_youtube_transcribe.py
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
from core import transcribe  # noqa: E402

URL = os.environ.get("ARION_TEST_URL",
                     "https://www.youtube.com/watch?v=jNQXAC9IVRw")
OUT = os.path.join(ROOT, "tests", "_artifacts", "yt")


def main():
    os.makedirs(OUT, exist_ok=True)
    calls = []

    def fake_chunk(rotator, chunk, lang, style, cancel_check=None):
        calls.append(chunk)
        if cancel_check:
            cancel_check()
        return ("1\n00:00:00,400 --> 00:00:02,000\nسلام دنیا (تست)\n"), "fa"

    transcribe._transcribe_chunk_groq = fake_chunk

    events = []

    def progress(stage_pct, label, overall=None, note=""):
        events.append((overall, label))

    job = engine.Job(progress_cb=progress, log_cb=lambda line: print("  log:", line))
    job.started = time.monotonic()

    t0 = time.monotonic()
    result = engine.transcribe_youtube(job, ["dummy"], URL, OUT, language="fa",
                                       output_format="both", provider="groq")
    print(f"\nfinished in {time.monotonic()-t0:.1f}s -> {result}")

    overalls = [e[0] for e in events if isinstance(e[0], (int, float))]
    print("progress updates:", len(overalls),
          "| monotonic:", all(b >= a for a, b in zip(overalls, overalls[1:])),
          "| range:", (min(overalls), max(overalls)) if overalls else None)
    print("distinct labels:", len({e[1] for e in events if e[1]}))
    print("phases seen:", [lbl for _, lbl in events if lbl][:4], "…")

    assert result.get("srt") and os.path.exists(result["srt"]), "no SRT produced"
    assert os.path.dirname(os.path.abspath(result["srt"])) == os.path.abspath(OUT)
    with open(result["srt"], encoding="utf-8") as f:
        content = f.read()
    print("\nSRT head:\n" + content[:200])
    assert "سلام دنیا" in content
    assert overalls and max(overalls) >= 99
    assert calls, "chunk transcriber never ran"

    txt = result.get("txt")
    assert txt and os.path.exists(txt)
    print("\nYT TRANSCRIBE SMOKE OK")


if __name__ == "__main__":
    main()