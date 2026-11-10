"""Audio helpers: probe, compress and split media into API-sized chunks.

Every long ffmpeg call reports *real* progress (0-100) through a callback, so
the GUI can show an honest percentage instead of an indeterminate spinner.

The public helpers are deliberately tolerant: a missing ffmpeg, a weird
container or a silent recording must never crash the worker with a bare
traceback — they raise RuntimeError (AudioError) with a readable message.
"""

import math
import os
import re
import shutil
import subprocess
import threading

from i18n import t

FFMPEG = os.environ.get("ARION_FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("ARION_FFPROBE", "ffprobe")

_TIME_RE = re.compile(r"out_time=(-?\d+):(\d+):(\d+(?:\.\d+)?)")
_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


class AudioError(RuntimeError):
    """Raised when an audio processing step fails (message is user-facing)."""


def available():
    """True when both ffmpeg and ffprobe can be found on PATH."""
    return bool(shutil.which(FFMPEG) and shutil.which(FFPROBE))


def _run(cmd, timeout=None):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise AudioError(
            t("audio.err.tool_missing", tool=cmd[0], error=exc))
    except subprocess.TimeoutExpired:
        raise AudioError(t("audio.err.timeout"))


def get_duration(path):
    """Duration of a media file in seconds (0.0 when it cannot be read)."""
    try:
        out = _run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=nw=1:nk=1", path], timeout=120).stdout or ""
    except AudioError:
        return 0.0
    m = re.search(r"-?\d+(?:\.\d+)?", out)
    if m:
        try:
            return max(0.0, float(m.group(0)))
        except ValueError:
            return 0.0
    # ffprobe sometimes refuses the container header; ask ffmpeg as a fallback.
    try:
        err = _run([FFMPEG, "-hide_banner", "-i", path], timeout=120).stderr or ""
    except AudioError:
        return 0.0
    m = _DUR_RE.search(err)
    if not m:
        return 0.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def _emit(progress, pct, label=None):
    if not progress:
        return
    try:
        progress(float(pct), label) if label else progress(float(pct))
    except TypeError:
        try:
            progress(float(pct))
        except Exception:
            pass
    except Exception:
        pass


def _progress_run(cmd, duration, progress=None, start_pct=0.0, end_pct=100.0,
                  label=None, loglevel="error"):
    """Run an ffmpeg command that writes ``-progress pipe:1`` and stream %.

    Returns (returncode, stderr_text). Progress is linear in media time, which
    is exactly what ffmpeg reports through ``out_time``.

    ``loglevel`` matters: filters such as ``silencedetect`` print their findings
    at info level, so forcing ``error`` there would silently lose them.
    """
    full = [cmd[0], "-hide_banner", "-nostats", "-progress", "pipe:1",
            "-loglevel", loglevel] + list(cmd[1:])
    try:
        proc = subprocess.Popen(full, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, bufsize=1)
    except FileNotFoundError as exc:
        raise AudioError(t("audio.err.spawn_failed", tool=cmd[0], error=exc))

    err_lines = []

    def _drain_err():
        try:
            for line in proc.stderr:
                err_lines.append(line)
                if len(err_lines) > 300:
                    del err_lines[:100]
        except Exception:
            pass

    th = threading.Thread(target=_drain_err, daemon=True)
    th.start()

    span = max(0.0, float(end_pct) - float(start_pct))
    try:
        for raw in proc.stdout:
            line = (raw or "").strip()
            if not line:
                continue
            if duration and span:
                secs = None
                if line.startswith("out_time="):
                    m = _TIME_RE.match(line)
                    if m:
                        secs = (int(m.group(1)) * 3600 + int(m.group(2)) * 60
                                + float(m.group(3)))
                elif line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                    try:
                        secs = float(line.split("=", 1)[1]) / 1_000_000.0
                    except (ValueError, IndexError):
                        secs = None
                if secs is not None:
                    frac = max(0.0, min(1.0, secs / duration))
                    _emit(progress, start_pct + span * frac, label)
            if line == "progress=end":
                _emit(progress, end_pct, label)
    finally:
        rc = proc.wait()
        try:
            th.join(timeout=2)
        except Exception:
            pass
        # Close the pipes: without this every ffmpeg call leaked two handles.
        for stream in (proc.stdout, proc.stderr):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass
    return rc, "".join(err_lines)


def compress_to_mp3(src, dst=None, bitrate="64k", progress=None, cancel_check=None):
    """Convert any input media to mono 16 kHz mp3 (small + Whisper-friendly)."""
    if not os.path.exists(src):
        raise AudioError(t("audio.err.input_missing", path=src))
    if dst is None:
        dst = os.path.splitext(src)[0] + "_compressed.mp3"
    parent = os.path.dirname(os.path.abspath(dst))
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError as exc:
        raise AudioError(t("audio.err.mkdir_failed", path=parent, error=exc)) from exc
    tmp = dst + ".part.mp3"
    duration = get_duration(src)
    cmd = [FFMPEG, "-y", "-i", src, "-vn", "-acodec", "libmp3lame",
           "-ab", bitrate, "-ac", "1", "-ar", "16000", tmp]
    rc, err = _progress_run(cmd, duration, progress, 0, 100, t("audio.log.compressing"))
    if cancel_check:
        cancel_check()
    if rc != 0 or not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
        try:
            os.remove(tmp)
        except OSError:
            pass
        tail = (err or "").strip().splitlines()[-4:]
        raise AudioError(t("audio.err.convert_failed")
                         + (("\n" + "\n".join(tail)) if tail else ""))
    os.replace(tmp, dst)
    return dst


def detect_silences(path, noise_db="-30dB", min_dur=0.5, duration=None,
                    progress=None, start_pct=0.0, end_pct=100.0):
    """Return [(start, end)] of silent gaps; also drives the progress bar."""
    cmd = [FFMPEG, "-y", "-i", path, "-af",
           f"silencedetect=noise={noise_db}:d={min_dur}", "-f", "null", "-"]
    # silencedetect reports at info level, so this call must not use -loglevel error.
    _rc, err = _progress_run(cmd, duration or get_duration(path), progress,
                             start_pct, end_pct, t("audio.log.finding_silences"),
                             loglevel="info")
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*(-?[\d.]+)", err)]
    return list(zip(starts, ends))


def find_cut_points(total_duration, num_chunks, silences, search_window=30):
    if num_chunks <= 1:
        return [0.0, max(0.0, total_duration)]
    raw_targets = [total_duration * i / num_chunks for i in range(1, num_chunks)]
    cut_points = [0.0]
    for target in raw_targets:
        best, best_dist = None, search_window
        for s, e in silences:
            mid = (s + e) / 2
            dist = abs(mid - target)
            if dist <= best_dist:
                best_dist, best = dist, mid
        cut_points.append(best if best is not None else target)
    cut_points.append(total_duration)
    return sorted(set(cut_points))


def split_audio(src, out_dir, max_minutes=20, progress=None, cancel_check=None,
                use_silence=True):
    """Split ``src`` into ~max_minutes mp3 chunks, cutting at silent gaps.

    Returns (chunk_paths, start_seconds) where start_seconds[i] is the exact
    start time of chunk i in the source audio (used for precise SRT offsets).
    Progress is reported across the whole operation (silence scan + each cut).
    """
    os.makedirs(out_dir, exist_ok=True)
    total = get_duration(src)
    if total <= 0:
        raise AudioError(t("audio.err.no_duration"))
    num_chunks = 1 if total / 60.0 <= max_minutes else math.ceil((total / 60.0) / max_minutes)
    num_chunks = max(1, num_chunks)

    if num_chunks == 1:
        dst = os.path.join(out_dir, "chunk_000.mp3")
        cmd = [FFMPEG, "-y", "-i", src, "-acodec", "libmp3lame",
               "-ab", "64k", "-ac", "1", dst]
        rc, err = _progress_run(cmd, total, progress, 0, 100, t("audio.log.preparing"))
        if cancel_check:
            cancel_check()
        if rc != 0 or not os.path.exists(dst) or os.path.getsize(dst) == 0:
            tail = (err or "").strip().splitlines()[-3:]
            raise AudioError(t("audio.err.split_failed")
                             + (("\n" + "\n".join(tail)) if tail else ""))
        return [dst], [0.0]

    silences = []
    if use_silence:
        try:
            silences = detect_silences(src, duration=total, progress=progress,
                                       start_pct=0, end_pct=18)
        except AudioError:
            silences = []
    if cancel_check:
        cancel_check()

    cut_points = find_cut_points(total, num_chunks, silences)
    chunks, starts = [], []
    segments = max(1, len(cut_points) - 1)
    for i in range(len(cut_points) - 1):
        if cancel_check:
            cancel_check()
        start, end = cut_points[i], cut_points[i + 1]
        if end - start < 0.05:
            continue
        dst = os.path.join(out_dir, f"chunk_{len(chunks):03d}.mp3")
        lo = 18 + (82.0 * i / segments)
        hi = 18 + (82.0 * (i + 1) / segments)
        label = t("audio.log.splitting", current=i + 1, total=segments)
        cmd = [FFMPEG, "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
               "-i", src, "-c", "copy", dst]
        rc, _err = _progress_run(cmd, end - start, progress, lo, hi, label)
        if rc != 0 or not os.path.exists(dst) or os.path.getsize(dst) == 0:
            # Stream copy can fail on odd containers; re-encode that slice.
            cmd = [FFMPEG, "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
                   "-i", src, "-acodec", "libmp3lame", "-ab", "64k",
                   "-ac", "1", "-ar", "16000", dst]
            _progress_run(cmd, end - start, progress, lo, hi, label)
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            chunks.append(dst)
            starts.append(float(start))
    if not chunks:
        raise AudioError(t("audio.err.no_chunks"))
    _emit(progress, 100, t("audio.log.split_done"))
    return chunks, starts