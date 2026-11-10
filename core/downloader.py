"""YouTube download helpers built on yt-dlp.

Everything long-running here reports live progress (percent / speed / ETA /
bytes) and is cancellable: the worker thread can kill the child process.
The helpers also self-check which yt-dlp flags the installed version supports,
so an older yt-dlp does not make every download fail on an unknown option.
"""

import glob
import json
import os
import re
import subprocess
import sys
import threading
import time

from . import config


class DownloadError(Exception):
    """A download/Extraction step failed (message is user-facing)."""


class DownloadCancelled(DownloadError):
    """The user pressed Stop while a child process was running."""


# Networking flags shared by the media download commands. YouTube throttles a
# single connection, so pulling several fragments at once (and in bigger HTTP
# chunks) is what actually keeps downloads fast.
SPEED_FLAGS = [
    "--concurrent-fragments", "8",
    "--http-chunk-size", "10M",
    "--socket-timeout", "20",
    "--retries", "10",
    "--sleep-requests", "1",
    "--extractor-retries", "3",
    "--fragment-retries", "10",
]

# The ``download:`` part is a yt-dlp *type* prefix, not literal output: yt-dlp
# prints only the template body (e.g. "NA|1.2MiB/s|00:10|123|456|NA").
PROGRESS_TEMPLATE = (
    "download:%(progress.percent)s|%(progress.speed)s|%(progress.eta)s"
    "|%(progress.downloaded_bytes)s|%(progress.total_bytes)s"
    "|%(progress.total_bytes_estimate)s"
)

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*(?:\x07|\x1b\\)")

_HELP_CACHE = {}
_HELP_LOCK = threading.Lock()


def sanitize_filename(name):
    """Make a title safe to use as a file name, with underscores between words."""
    name = (name or "").strip()
    name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", " ", name)
    name = re.sub(r"\s+", "_", name)
    name = name.strip("_.")
    return name[:120] or "file"


# ---------------------------------------------------------------- yt-dlp utils

def _help_text():
    with _HELP_LOCK:
        if "text" not in _HELP_CACHE:
            try:
                r = subprocess.run([sys.executable, "-m", "yt_dlp", "--help"],
                                   capture_output=True, text=True, timeout=60)
                _HELP_CACHE["text"] = (r.stdout or "") + (r.stderr or "")
            except Exception as exc:  # yt-dlp missing / broken
                _HELP_CACHE["text"] = ""
                _HELP_CACHE["error"] = str(exc)
    return _HELP_CACHE.get("text") or ""


def supports(flag):
    """True when the installed yt-dlp knows ``flag`` (cached)."""
    return flag in _help_text()


def ytdlp_available():
    return bool(_help_text())


def _base_cmd(use_vpn, progress=False):
    cmd = []
    vpn_ns = getattr(config, "YT_NETNS", "")
    if use_vpn and vpn_ns:
        cmd += ["ip", "netns", "exec", vpn_ns]
    cmd += [sys.executable, "-m", "yt_dlp", "--no-playlist",
            "--no-warnings", "--ignore-config"]
    if progress:
        # Without --progress, yt-dlp's --print/--quiet combination suppresses
        # the progress template entirely (this was why the bar never moved).
        cmd += ["--newline", "--no-colors", "--progress",
                "--progress-template", PROGRESS_TEMPLATE]
    if supports("--remote-components"):
        cmd += ["--remote-components", "ejs:github"]
    return cmd


def _apply_network(cmd, use_vpn, cookies_path):
    """Add proxy + cookies whenever no VPN namespace is actually used."""
    if (not use_vpn) or (not getattr(config, "YT_NETNS", "")):
        proxy = getattr(config, "YT_PROXY", "")
        if proxy:
            cmd += ["--proxy", proxy]
    cookie_file = cookies_path or getattr(config, "YT_COOKIES_FILE", "")
    if cookie_file and os.path.exists(cookie_file):
        cmd += ["--cookies", cookie_file]
    return cmd


def _to_float(value):
    if value is None:
        return None
    s = str(value).strip().replace(",", "")
    if s.endswith("%"):
        s = s[:-1].strip()
    if not s or s.upper() in ("NA", "N/A", "NONE", "UNKNOWN"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _clean_field(value):
    s = (value or "").strip()
    return "" if s.upper() in ("NA", "N/A", "NONE") else s


def _fmt_bytes(num):
    try:
        num = float(num)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024 or unit == "TB":
            return f"{num:.0f}{unit}" if unit in ("B", "KB") else f"{num:.1f}{unit}"
        num /= 1024.0
    return ""


def _fmt_speed(value):
    """yt-dlp gives speed in bytes/s when it is numeric."""
    if value is None:
        return ""
    if str(value).strip().upper() in ("", "NA", "N/A", "NONE"):
        return ""
    try:
        return _fmt_bytes(float(value)) + "/s"
    except (TypeError, ValueError):
        return str(value).strip()


def _fmt_eta(value):
    """yt-dlp gives ETA in seconds when it is numeric."""
    if value is None:
        return ""
    if str(value).strip().upper() in ("", "NA", "N/A", "NONE"):
        return ""
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return str(value).strip()
    if seconds < 0:
        return ""
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def parse_progress_line(line):
    """Parse one ``--progress-template`` line into a dict (or None).

    Real yt-dlp output is the bare template body, because the ``download:``
    prefix selects the template *type*. A line may still carry that tag (older
    custom templates) or stray ANSI colour codes, so both are tolerated.

    Kept public and dependency-free so it can be unit-tested without yt-dlp.
    """
    if not line:
        return None
    clean = _ANSI_RE.sub("", str(line)).strip()
    if "|" not in clean:
        return None
    tag = clean.rfind("download:")
    if tag >= 0:
        clean = clean[tag + len("download:"):].strip()
    parts = [p.strip() for p in clean.split("|")]
    if len(parts) < 3:
        return None
    pct = _to_float(parts[0])
    speed = _fmt_speed(_clean_field(parts[1]))
    eta = _fmt_eta(_clean_field(parts[2]))
    downloaded = _to_float(parts[3]) if len(parts) > 3 else None
    total = _to_float(parts[4]) if len(parts) > 4 else None
    estimate = _to_float(parts[5]) if len(parts) > 5 else None
    total = total or estimate
    if pct is None and downloaded is not None and total:
        pct = 100.0 * downloaded / total
    if pct is None:
        return None
    return {
        "pct": max(0.0, min(100.0, pct)),
        "speed": speed,
        "eta": eta,
        "downloaded": downloaded,
        "total": total,
    }


def _emit(progress, pct=None, speed="", eta="", message=""):
    """Call the caller's progress callback, tolerating either signature."""
    if not progress:
        return
    try:
        progress(pct=pct, speed=speed, eta=eta, message=message)
        return
    except TypeError:
        pass
    except Exception:
        return
    try:
        if message and pct is None:
            progress(message)
        elif pct is not None:
            progress(pct, speed, eta)
    except Exception:
        pass


class _Proc:
    """Small subprocess.run() look-alike (returncode/stdout/stderr)."""

    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _terminate(proc):
    try:
        proc.terminate()
        proc.wait(timeout=4)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _run_ytdlp_once(cmd, progress=None, cancel_event=None):
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL, text=True,
                                errors="replace", bufsize=1)
    except FileNotFoundError:
        raise DownloadError("yt-dlp اجرا نشد؛ بسته‌ی yt-dlp نصب نیست "
                            "(pip install -r requirements.txt).")

    out_lines, err_lines = [], []
    sink_lock = threading.Lock()

    def _reader(stream, sink):
        try:
            for raw in stream:
                if not raw:
                    continue
                info = parse_progress_line(raw)
                if info:
                    _emit(progress, info["pct"], info["speed"], info["eta"])
                    continue
                with sink_lock:
                    sink.append(raw)
                    if len(sink) > 1000:
                        del sink[:300]
        except Exception:
            pass

    readers = [
        threading.Thread(target=_reader, args=(proc.stdout, out_lines), daemon=True),
        threading.Thread(target=_reader, args=(proc.stderr, err_lines), daemon=True),
    ]
    for th in readers:
        th.start()

    while proc.poll() is None:
        if cancel_event is not None and cancel_event.is_set():
            _terminate(proc)
            raise DownloadCancelled("دانلود لغو شد.")
        time.sleep(0.12)

    rc = proc.returncode
    for th in readers:
        try:
            th.join(timeout=3)
        except Exception:
            pass
    with sink_lock:
        out_text = "".join(out_lines)
        err_text = "".join(err_lines)
    # Release the pipes; otherwise every probe/download leaked two handles.
    for stream in (proc.stdout, proc.stderr):
        try:
            if stream is not None:
                stream.close()
        except Exception:
            pass
    return _Proc(rc, out_text, err_text)


def _run_ytdlp(cmd, progress=None, cancel_event=None):
    """Run yt-dlp, retrying once after a 429 (YouTube rate limit)."""
    result = _run_ytdlp_once(cmd, progress, cancel_event)
    if result.returncode != 0:
        blob = (result.stdout or "") + (result.stderr or "")
        if "HTTP Error 429" in blob or "Too Many Requests" in blob:
            _emit(progress, message="⏳ یوتیوب محدودیت موقت داد؛ ۴۵ ثانیه صبر و تلاش دوباره…")
            for _ in range(45):
                if cancel_event is not None and cancel_event.is_set():
                    raise DownloadCancelled("دانلود لغو شد.")
                time.sleep(1)
            result = _run_ytdlp_once(cmd, progress, cancel_event)
    return result


def _last_existing_path(stdout_text):
    lines = [ln.strip().strip('"') for ln in (stdout_text or "").splitlines()]
    for line in reversed(lines):
        if line and os.path.isfile(line):
            return line
    return None


def _newest_file(work_dir, exts):
    matches = []
    for ext in exts:
        matches += glob.glob(os.path.join(work_dir, "*." + ext))
    matches = [m for m in matches if os.path.isfile(m)]
    if not matches:
        return None
    return max(matches, key=os.path.getmtime)


def _explain_failure(msg):
    if "Sign in to confirm" in msg or "not a bot" in msg:
        return ("\n\n💡 یوتیوب این IP را بلاک کرده. یک فایل cookies.txt از تب دانلود "
                "معرفی کن یا پروکسی بگذار.")
    if "No supported JavaScript runtime" in msg or "JS runtime" in msg:
        return "\n\n💡 yt-dlp به یک JS runtime (Node/Deno) نیاز دارد؛ نصبش کن یا نسخه‌ی yt-dlp را به‌روز کن."
    if "Requested format is not available" in msg:
        return "\n\n💡 این کیفیت برای این ویدیو موجود نیست؛ گزینه‌ی دیگری انتخاب کن."
    if "HTTP Error 403" in msg:
        return "\n\n💡 دسترسی به این ویدیو محدود است (403)؛ کوکی یا پروکسی لازم است."
    if "Private video" in msg or "Video unavailable" in msg:
        return "\n\n💡 ویدیو خصوصی/حذف‌شده است."
    return ""


# ------------------------------------------------------------------- formats

DL_VIDEO_FORMATS = {
    "144": "bestvideo[height<=144]+bestaudio/best[height<=144]/best",
    "240": "bestvideo[height<=240]+bestaudio/best[height<=240]/best",
    "360": "bestvideo[height<=360]+bestaudio/best[height<=360]/best",
    "480": "bestvideo[height<=480]+bestaudio/best[height<=480]/best",
    "720": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
    "1080": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
    "1440": "bestvideo[height<=1440]+bestaudio/best[height<=1440]/best",
    "2160": "bestvideo[height<=2160]+bestaudio/best[height<=2160]/best",
    "best": "bestvideo+bestaudio/best",
}

AUDIO_HEIGHTS = (144, 240, 360, 480, 720, 1080, 1440, 2160)

# Audio-only qualities (download flow): source format preselection + extraction target.
DL_AUDIO_SOURCE = {
    "m4a": "bestaudio[ext=m4a]/bestaudio",
    "opus": "bestaudio[ext=webm]/bestaudio",
    "flac": "bestaudio",
}
DL_AUDIO_TARGET = {"audio": "mp3", "m4a": "m4a", "opus": "opus", "flac": "flac"}
DL_AUDIO_EXTS = ("mp3", "m4a", "opus", "ogg", "flac", "webm", "aac", "wav")
DL_VIDEO_EXTS = ("mp4", "mkv", "webm")


def video_format(quality):
    """yt-dlp format string for a quality key ("best", "1080", ...)."""
    q = str(quality or "best").strip().lower()
    if q in ("best", "", "none"):
        return DL_VIDEO_FORMATS["best"]
    q = re.sub(r"[^0-9]", "", q)
    if not q:
        return DL_VIDEO_FORMATS["best"]
    h = min(int(q), 4320)
    return (f"bestvideo[height<={h}]+bestaudio"
            f"/best[height<={h}]/bestvideo[height<={h}]/best")


# ----------------------------------------------------------------- downloads

def download_youtube_audio(url, work_dir, cookies_path=None, use_vpn=False,
                           progress=None, cancel_event=None):
    """Download the audio track of a YouTube URL as mono 16 kHz mp3."""
    os.makedirs(work_dir, exist_ok=True)
    out_tmpl = os.path.join(work_dir, "%(title).150B.%(ext)s")
    _emit(progress, message="🔎 خواندن اطلاعات ویدیو…")

    cmd = _base_cmd(use_vpn, progress=bool(progress))
    cmd += SPEED_FLAGS + [
        "--no-simulate",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "5",
        "--postprocessor-args", "ExtractAudio:-ac 1 -ar 16000",
        "--output", out_tmpl,
        "--print", "after_move:filepath",
    ]
    cmd = _apply_network(cmd, use_vpn, cookies_path)
    cmd.append(url)

    result = _run_ytdlp(cmd, progress, cancel_event)
    if result.returncode != 0:
        msg = ((result.stderr or "").strip() or (result.stdout or "").strip())[-900:]
        raise DownloadError((msg or "yt-dlp failed") + _explain_failure(msg))

    path = _last_existing_path(result.stdout) or _newest_file(work_dir, ("mp3",))
    if not path:
        raise DownloadError("فایل صوتی دانلودشده پیدا نشد.")
    _emit(progress, 100, "", "", "✅ دانلود صدا تمام شد")
    return path


def download_youtube_video(url, work_dir, quality="best", cookies_path=None,
                           use_vpn=False, progress=None, cancel_event=None):
    """Download a YouTube video (or an audio-only format) at a given quality.

    ``quality`` accepts "best", a height ("1080"), or an audio key
    ("audio" -> mp3, "m4a", "opus", "flac").
    """
    os.makedirs(work_dir, exist_ok=True)
    out_tmpl = os.path.join(work_dir, "%(title).150B.%(ext)s")
    _emit(progress, message="🔎 خواندن اطلاعات ویدیو…")

    cmd = _base_cmd(use_vpn, progress=bool(progress)) + SPEED_FLAGS
    audio_target = DL_AUDIO_TARGET.get(str(quality or "").lower())
    if audio_target:
        if quality in DL_AUDIO_SOURCE:
            cmd += ["--format", DL_AUDIO_SOURCE[quality]]
        cmd += ["--extract-audio", "--audio-format", audio_target,
                "--audio-quality", "0"]
        exts = DL_AUDIO_EXTS
    else:
        cmd += ["--format", video_format(quality), "--merge-output-format", "mp4"]
        exts = DL_VIDEO_EXTS

    cmd += [
        "--no-simulate",
        "--output", out_tmpl,
        "--print", "after_move:filepath",
    ]
    cmd = _apply_network(cmd, use_vpn, cookies_path)
    cmd.append(url)

    result = _run_ytdlp(cmd, progress, cancel_event)
    if result.returncode != 0:
        msg = ((result.stderr or "").strip() or (result.stdout or "").strip())[-900:]
        raise DownloadError((msg or "yt-dlp failed") + _explain_failure(msg))

    path = _last_existing_path(result.stdout) or _newest_file(work_dir, exts)
    if not path:
        raise DownloadError("فایل دانلودشده پیدا نشد.")
    _emit(progress, 100, "", "", "✅ دانلود تمام شد")
    return path


def list_playlist(url, cookies_path=None, use_vpn=False, max_items=25):
    """Return up to max_items video URLs from a YouTube playlist (no download)."""
    cmd = _base_cmd(use_vpn)
    cmd += ["--flat-playlist", "--skip-download",
            "--socket-timeout", "20", "--retries", "2",
            "--playlist-end", str(max_items),
            "--print", "%(url)s"]
    cmd = _apply_network(cmd, use_vpn, cookies_path)
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise DownloadError((result.stderr or "").strip()[-800:]
                            or "yt-dlp playlist listing failed")
    urls = [ln.strip() for ln in (result.stdout or "").splitlines()
            if ln.strip().startswith("http")]
    return urls


# ------------------------------------------------------------- metadata/info

def get_youtube_info(url, cookies_path=None, use_vpn=False, timeout=60,
                     progress=None):
    _emit(progress, message="🔎 خواندن اطلاعات ویدیو…")
    cmd = _base_cmd(use_vpn)
    cmd += ["--skip-download", "--socket-timeout", "15", "--retries", "1",
            "--dump-single-json"]
    cmd = _apply_network(cmd, use_vpn, cookies_path)
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise DownloadError("خواندن اطلاعات ویدیو زمان‌بر شد (timeout).")

    blob = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        if "HTTP Error 429" in blob or "Too Many Requests" in blob:
            raise DownloadError("یوتیوب موقتاً درخواست‌های این سیستم را محدود کرده (429). "
                                "چند دقیقه بعد دوباره امتحان کن.")
        raise DownloadError(((r.stderr or "").strip()[-500:]
                             or "خواندن اطلاعات ویدیو ناموفق بود.")
                            + _explain_failure(blob))
    try:
        info = json.loads(r.stdout)
    except Exception:
        raise DownloadError("پاسخ اطلاعات ویدیو قابل خواندن نبود.")
    _cache_store(url, cookies_path, use_vpn, info)
    return info


_INFO_CACHE = {}
_INFO_TTL = 1800
_INFO_LOCK = threading.Lock()
_INFO_INFLIGHT = {}


def _cache_key(url, cookies_path, use_vpn):
    return (url, bool(cookies_path), bool(use_vpn),
            getattr(config, "YT_PROXY", ""))


def _cache_store(url, cookies_path, use_vpn, info):
    try:
        _INFO_CACHE[_cache_key(url, cookies_path, use_vpn)] = (time.time(), info)
        if len(_INFO_CACHE) > 40:
            for k in sorted(_INFO_CACHE, key=lambda k: _INFO_CACHE[k][0])[:10]:
                _INFO_CACHE.pop(k, None)
    except Exception:
        pass


def _cached_info(url, cookies_path, use_vpn, timeout=150, progress=None):
    key = _cache_key(url, cookies_path, use_vpn)
    now = time.time()
    hit = _INFO_CACHE.get(key)
    if hit and now - hit[0] < _INFO_TTL:
        return hit[1]
    # In-flight dedup: parallel callers wait for the same single extraction.
    with _INFO_LOCK:
        ev = _INFO_INFLIGHT.get(key)
        owner = ev is None
        if owner:
            ev = threading.Event()
            _INFO_INFLIGHT[key] = ev
    if not owner:
        ev.wait(timeout=min(timeout, 90))
        hit = _INFO_CACHE.get(key)
        return hit[1] if hit else None
    try:
        info = get_youtube_info(url, cookies_path, use_vpn, timeout=timeout,
                                progress=progress)
        _INFO_CACHE[key] = (time.time(), info)
        return info
    finally:
        _INFO_INFLIGHT.pop(key, None)
        ev.set()


def _estimate_bytes(fmt, duration):
    size = fmt.get("filesize") or fmt.get("filesize_approx")
    if size:
        return float(size)
    tbr = fmt.get("tbr") or 0
    if tbr and duration:
        return float(tbr) * 1000.0 / 8.0 * float(duration)
    return None


def probe_sizes(url, cookies_path=None, use_vpn=False, progress=None):
    """Estimate download sizes (MB) per quality for the GUI's size menu.

    Returns a dict::

        {"title": str, "duration": float, "uploader": str, "max_height": int,
         "video": {"144": mb, ..., "best": mb},
         "audio": {"mp3": mb, "m4a": mb, "opus": mb, "flac": mb}}
    """
    _emit(progress, message="⚖️ تخمین حجم: خواندن اطلاعات ویدیو…")
    info = _cached_info(url, cookies_path, use_vpn, progress=progress)
    if not info:
        raise DownloadError("اطلاعات این ویدیو خوانده نشد (لینک یا اتصال را بررسی کن).")
    _emit(progress, message="⚖️ تخمین حجم: محاسبه‌ی کیفیت‌ها…")

    duration = float(info.get("duration") or 0)
    fmts = info.get("formats") or []
    video_formats = [f for f in fmts
                     if f.get("vcodec") not in (None, "none") and (f.get("height") or 0)]
    audio_formats = [f for f in fmts
                     if f.get("vcodec") in (None, "none")
                     and f.get("acodec") not in (None, "none")]

    def mb(value):
        return max(1, int(round(value / 1048576.0))) if value else None

    best_audio = None
    if audio_formats:
        best_audio = max(audio_formats,
                         key=lambda f: (f.get("abr") or f.get("tbr") or 0))
    audio_size = _estimate_bytes(best_audio, duration) if best_audio else None

    video = {}
    max_height = 0
    for h in AUDIO_HEIGHTS:
        cands = [f for f in video_formats if (f.get("height") or 0) <= h]
        if not cands:
            continue
        best = max(cands, key=lambda f: ((f.get("height") or 0),
                                         (f.get("tbr") or 0)))
        max_height = max(max_height, int(best.get("height") or 0))
        # Do not offer "4K" for a 1080p upload.
        if int(best.get("height") or 0) < h * 0.9:
            continue
        total = (_estimate_bytes(best, duration) or 0) + (audio_size or 0)
        if total:
            video[str(h)] = mb(total)
    if video_formats:
        best = max(video_formats, key=lambda f: ((f.get("height") or 0),
                                                (f.get("tbr") or 0)))
        total = (_estimate_bytes(best, duration) or 0) + (audio_size or 0)
        if total:
            video["best"] = mb(total)

    audio = {}
    if duration:
        # Our MP3 output is always 64 kbps mono, so this estimate is exact.
        audio["mp3"] = max(1, int(round(duration * 64000 / 8 / 1048576.0)))
        audio["m4a"] = mb(audio_size) if audio_size else None
        audio["opus"] = mb(audio_size * 0.85) if audio_size else None
        # FLAC of 16 kHz mono speech lands around 300 kbps.
        audio["flac"] = max(1, int(round(duration * 300000 / 8 / 1048576.0)))
    _emit(progress, 100, "", "", "✅ تخمین حجم آماده شد")
    return {
        "title": info.get("title") or "",
        "uploader": info.get("uploader") or info.get("channel") or "",
        "duration": duration,
        "max_height": max_height,
        "video": video,
        "audio": {k: v for k, v in audio.items() if v},
    }


def download_youtube_info_txt(url, work_dir, cookies_path=None, use_vpn=False,
                              progress=None):
    """Write the video's title, metadata and full description to a .txt file.

    Returns (path, title). No media is downloaded.
    """
    info = get_youtube_info(url, cookies_path, use_vpn, timeout=150,
                            progress=progress)
    title = (info.get("title") or "youtube_info").strip()
    lines_out = [f"\U0001f3ac {title}", "",
                 f"\U0001f517 {info.get('webpage_url') or url}"]
    meta = [
        ("\U0001f4fa channel", info.get("uploader") or info.get("channel")),
        ("\U0001f194 id", info.get("id")),
        ("\U0001f4c5 upload_date", info.get("upload_date")),
        ("\u23f1 duration", info.get("duration_string")),
        ("\U0001f441 views", info.get("view_count")),
        ("\U0001f44d likes", info.get("like_count")),
    ]
    for label, value in meta:
        if value not in (None, "", 0):
            lines_out.append(f"{label}: {value}")
    tags = info.get("tags") or []
    if tags:
        lines_out.append("\U0001f3f7 tags: " + ", ".join(str(t) for t in tags))
    cats = info.get("categories") or []
    if cats:
        lines_out.append("\U0001f4c2 categories: " + ", ".join(str(c) for c in cats))
    chapters = info.get("chapters") or []
    if chapters:
        lines_out.append("")
        lines_out.append("\u23f1 chapters:")
        for ch in chapters:
            st = ch.get("start_time")
            stamp = (f"{int(st) // 60:02}:{int(st) % 60:02}"
                     if st is not None else "?")
            lines_out.append(f"  \u2022 {stamp} \u2014 {ch.get('title') or ''}")
    lines_out += ["", "\u2500" * 30, "\U0001f4dd description:", "",
                  (info.get("description") or "").strip() or "(none)"]
    os.makedirs(work_dir, exist_ok=True)
    path = os.path.join(work_dir, sanitize_filename(title) + "_info.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines_out).rstrip() + "\n")
    _emit(progress, 100, "", "", "✅ فایل مشخصات نوشته شد")
    return path, title


def download_youtube_subtitle(url, work_dir, lang=None, cookies_path=None,
                              use_vpn=False, progress=None):
    """Download YouTube's ready subtitle as SRT. lang=None -> original track.

    Returns (path, lang_used, kind, title).
    """
    os.makedirs(work_dir, exist_ok=True)
    _emit(progress, message="🔎 خواندن اطلاعات و زیرنویس‌ها…")
    info = get_youtube_info(url, cookies_path, use_vpn, progress=progress)
    manual = list((info.get("subtitles") or {}).keys())
    auto = list((info.get("automatic_captions") or {}).keys())
    orig = info.get("language")
    title = info.get("title") or "subtitle"
    original_wanted = not lang or lang in ("original", "")

    if original_wanted:
        # Prefer the video's own-language track. yt-dlp marks the untranslated
        # original with a "-orig" suffix (e.g. "en-orig").
        target, kind = None, None
        orig_candidates = [f"{orig}-orig", orig] if orig else []
        for lst, k in ((manual, "manual"), (auto, "auto")):
            for cand in orig_candidates:
                if cand and cand in lst:
                    target, kind = cand, k
                    break
            if target:
                break
        if not target and manual:
            target = next((k for k in manual if k.endswith("-orig")), manual[0])
            kind = "manual"
        if not target and auto:
            target = next((k for k in auto if k.endswith("-orig")),
                          orig if (orig and orig in auto) else auto[0])
            kind = "auto"
        if not target:
            raise DownloadError("این ویدیو هیچ زیرنویس/کپشنی ندارد.")
    else:
        target = lang
        if target in manual:
            kind = "manual"
        elif target in auto:
            kind = "auto"
        elif auto:
            kind = "auto-translate"
        elif manual:
            kind = "manual"
        else:
            raise DownloadError("این ویدیو هیچ زیرنویس/کپشنی ندارد.")

    _emit(progress, 5, "", "", f"⬇️ دریافت زیرنویس «{target}» ({kind})…")
    out_tmpl = os.path.join(work_dir, "sub.%(ext)s")
    cmd = _base_cmd(use_vpn)
    cmd += ["--skip-download", "--socket-timeout", "20", "--retries", "2"]
    cmd += ["--write-subs" if kind == "manual" else "--write-auto-subs"]
    cmd += ["--sub-langs", target, "--sub-format", "srt/best",
            "--convert-subs", "srt", "--sleep-subtitles", "5",
            "--output", out_tmpl]
    cmd = _apply_network(cmd, use_vpn, cookies_path)
    cmd.append(url)

    files, blob = [], ""
    for attempt in (1, 2):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            r = None
        blob = ((r.stdout or "") + (r.stderr or "")) if r else ""
        files = glob.glob(os.path.join(work_dir, "sub*.srt"))
        if files:
            break
        if attempt == 1 and ("HTTP Error 429" in blob or "Too Many Requests" in blob):
            _emit(progress, 15, "", "", "⏳ محدودیت موقت یوتیوب؛ ۴۵ ثانیه صبر…")
            time.sleep(45)
            continue
        break

    if not files:
        if not original_wanted and ("HTTP Error 429" in blob
                                    or "Too Many Requests" in blob):
            # Auto-TRANSLATED captions are rate limited hardest; fall back to the
            # original track so the user still gets a usable SRT.
            try:
                path, tgt, kd, ttl = download_youtube_subtitle(
                    url, work_dir, None, cookies_path, use_vpn, progress)
                return (path, tgt,
                        kd + " (ترجمهٔ خودکار یوتیوب محدود بود؛ نسخهٔ اصلی)", ttl)
            except Exception:
                pass
        if "HTTP Error 429" in blob or "Too Many Requests" in blob:
            raise DownloadError("یوتیوب موقتاً درخواست‌های این سیستم را محدود کرده (429). "
                                "چند دقیقه بعد دوباره امتحان کن.")
        if original_wanted:
            raise DownloadError("این ویدیو زیرنویس آماده ندارد.")
        raise DownloadError(f"این ویدیو زیرنویس به زبان «{target}» ندارد "
                            "(و ترجمهٔ خودکار هم موجود نیست).")
    path = max(files, key=os.path.getmtime)
    _emit(progress, 100, "", "", "✅ زیرنویس دریافت شد")
    return path, target, kind, title