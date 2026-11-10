"""Manual check: yt-dlp's raw --progress-template output must parse cleanly.

Run:  set PYTHONPATH=C:\\Users\\parsa\\arion-test-deps && python tests\\_smoke_template.py
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from core import downloader  # noqa: E402

URL = os.environ.get("ARION_TEST_URL",
                     "https://www.youtube.com/watch?v=jNQXAC9IVRw")
WORK = os.path.join(ROOT, "tests", "_artifacts", "template")


def main():
    os.makedirs(WORK, exist_ok=True)
    cmd = downloader._base_cmd(use_vpn=False, progress=True)
    cmd += ["-f", "bestaudio", "--no-playlist", "-o", os.path.join(WORK, "a.%(ext)s"),
            "--keep-video", "--no-part", URL]
    print("template:", downloader.PROGRESS_TEMPLATE)
    print("cmd:", " ".join(cmd[:6]), "…")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            bufsize=1)
    raw, parsed, bad = 0, 0, []
    for line in proc.stdout:
        line = line.rstrip("\n")
        if not line:
            continue
        info = downloader.parse_progress_line(line)
        if info is not None:
            raw += 1
            parsed += 1
            if parsed <= 3 or parsed % 10 == 0:
                print(f"  parsed: pct={info['pct']} speed={info['speed']!r} "
                      f"eta={info['eta']!r} got={info['downloaded']} tot={info['total']}")
        elif "download:" in line:
            raw += 1
            bad.append(line)
            print("  UNPARSED:", repr(line))
    proc.wait()
    print(f"\nprogress lines seen: {raw} | parsed: {parsed} | unparsed: {len(bad)}")
    print("returncode:", proc.returncode)


if __name__ == "__main__":
    main()