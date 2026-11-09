import math
import os
import re
import subprocess


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def compress_to_mp3(src, dst=None, bitrate="64k"):
    """Convert any input media to mono 64kbps mp3 (small + Groq-friendly)."""
    if dst is None:
        dst = os.path.splitext(src)[0] + "_compressed.mp3"
    _run(["ffmpeg", "-i", src, "-acodec", "libmp3lame", "-ab", bitrate, "-ac", "1", dst, "-y"])
    if not os.path.exists(dst) or os.path.getsize(dst) == 0:
        raise RuntimeError("ffmpeg نتوانست فایل را به mp3 تبدیل کند.")
    return dst


def get_duration(path):
    out = _run(
        ["ffprobe", "-i", path, "-show_entries", "format=duration",
         "-v", "quiet", "-of", "csv=p=0"]
    ).stdout.strip()
    return float(out) if out else 0.0


def detect_silences(path, noise_db="-30dB", min_dur=0.5):
    log = _run(
        ["ffmpeg", "-i", path, "-af", f"silencedetect=noise={noise_db}:d={min_dur}",
         "-f", "null", "-"]
    ).stderr
    starts = [float(x) for x in re.findall(r"silence_start:\s*([\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)", log)]
    return list(zip(starts, ends))


def find_cut_points(total_duration, num_chunks, silences, search_window=30):
    if num_chunks <= 1:
        return [0.0, total_duration]
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


def split_audio(src, out_dir, max_minutes=20):
    """Split src into ~max_minutes mp3 chunks, cutting at silent gaps when possible.

    Returns (chunk_paths, start_seconds) where start_seconds[i] is the exact
    start time of chunk i in the source audio (used for precise SRT offsets).
    """
    os.makedirs(out_dir, exist_ok=True)
    total = get_duration(src)
    num_chunks = 1 if total / 60 <= max_minutes else math.ceil((total / 60) / max_minutes)

    if num_chunks == 1:
        dst = os.path.join(out_dir, "chunk_000.mp3")
        _run(["ffmpeg", "-i", src, "-acodec", "libmp3lame", "-ab", "64k", "-ac", "1", dst, "-y"])
        return [dst], [0.0]

    silences = detect_silences(src)
    cut_points = find_cut_points(total, num_chunks, silences)
    chunks, starts = [], []
    for i in range(len(cut_points) - 1):
        dst = os.path.join(out_dir, f"chunk_{i:03d}.mp3")
        _run(
            ["ffmpeg", "-i", src, "-ss", str(cut_points[i]), "-to", str(cut_points[i + 1]),
             "-acodec", "libmp3lame", "-ab", "64k", "-ac", "1", dst, "-y"]
        )
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            chunks.append(dst)
            starts.append(float(cut_points[i]))
    return chunks, starts
