"""Manual smoke test for the ffmpeg audio layer (compress / split / silences).

Run:  python tests\\_smoke_audio.py [path-to-media]
"""

import glob
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

from core import audio  # noqa: E402

ARTIFACTS = os.path.join(ROOT, "tests", "_artifacts")
OUT = os.path.join(ARTIFACTS, "audio")


def find_input():
    if len(sys.argv) > 1:
        return sys.argv[1]
    for pattern in (os.path.join(ARTIFACTS, "download", "*.mp3"),
                    os.path.join(ARTIFACTS, "download", "*.webm"),
                    os.path.join(ARTIFACTS, "download", "*.m4a")):
        hits = glob.glob(pattern)
        if hits:
            return hits[0]
    raise SystemExit("no input media found; run tests/_smoke_download.py first")


def main():
    src = find_input()
    size = os.path.getsize(src)
    print("input:", os.path.basename(src), f"({size/1024:.0f} KB)")
    print("audio available:", audio.available())

    duration = audio.get_duration(src)
    print(f"duration: {duration} s ({duration/60:.2f} min)")
    assert duration > 0, "duration detection failed"

    print("\n== compress_to_mp3 ==")
    events = []
    mp3 = audio.compress_to_mp3(
        src, os.path.join(OUT, "compressed.mp3"),
        progress=lambda pct, msg="": events.append((pct, msg)))
    print("  out:", mp3, os.path.getsize(mp3), "bytes")
    print("  progress events:", len(events),
          "| first:", events[0] if events else None,
          "| last:", events[-1] if events else None)
    assert os.path.exists(mp3) and os.path.getsize(mp3) > 0
    assert not glob.glob(mp3 + "*part*"), "leftover .part file"
    pcts = [p for p, _ in events if isinstance(p, (int, float))]
    print("  monotonic progress:", all(b >= a for a, b in zip(pcts, pcts[1:])))
    assert pcts and pcts[-1] >= 99, f"progress did not finish: {pcts[-3:]}"

    print("\n== detect_silences ==")
    t0 = time.monotonic()
    silences = audio.detect_silences(mp3 + "", duration=duration,
                                     progress=lambda pct, msg="": None)
    print(f"  {len(silences)} silences in {time.monotonic()-t0:.1f}s:",
          silences[:4], "…" if len(silences) > 4 else "")

    print("\n== split_audio (3-minute chunks) ==")
    chunks, starts = audio.split_audio(mp3, os.path.join(OUT, "chunks"),
                                       max_minutes=3,
                                       progress=lambda pct, msg="": None)
    print(f"  {len(chunks)} chunks at starts {[round(s, 1) for s in starts]}")
    for path in chunks:
        print("   -", os.path.basename(path), f"{os.path.getsize(path)/1024:.0f} KB",
              f"{audio.get_duration(path):.1f}s")
    assert len(chunks) >= 2, "splitting produced too few chunks"
    total = sum(audio.get_duration(p) for p in chunks)
    print(f"  total chunk duration: {total:.1f}s vs source {duration:.1f}s")
    assert total > duration * 0.9, "chunks lost audio"

    print("\nAUDIO SMOKE OK")


if __name__ == "__main__":
    main()