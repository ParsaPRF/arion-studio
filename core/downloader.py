import glob
import json
import os
import re
import threading
import subprocess
import time
import sys

from . import config


class DownloadError(Exception):
    pass


# Networking flags shared by the media download commands. YouTube throttles a
# single connection, so pulling several fragments at once (and in bigger HTTP
# chunks) is what actually makes "no cookie (VPN)" downloads fast.
SPEED_FLAGS = [
    "--concurrent-fragments", "8",
    "--http-chunk-size", "10M",
    "--socket-timeout", "20",
    "--retries", "10",
    "--sleep-requests", "1",
    "--extractor-retries", "3",
    "--fragment-retries", "10",
]


def sanitize_filename(name):
    """Make a title safe to use as a file name, with underscores between words."""
    name = (name or "").strip()
    name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", " ", name)
    name = re.sub(r"\s+", "_", name)
    name = name.strip("_.")
    return name[:120] or "file"


PROGRESS_TEMPLATE = "download:%(progress._percent_str)s|%(progress.speed)s|%(progress.eta)s"


class _Proc:
    """Small subprocess.run() look-alike (returncode/stdout/stderr)."""

    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _run_ytdlp(cmd, progress=None):
    """Run a yt-dlp command, streaming live progress through `progress`.

    progress(percent, speed, eta) is called from the downloading thread; the
    caller is responsible for throttling the actual Telegram edits.
    On HTTP 429 (YouTube rate limit on our egress IP) wait briefly and retry
    once; repeated requests for the same video otherwise fail the whole job.
    """
    result = _run_ytdlp_once(cmd, progress)
    if result.returncode != 0:
        blob = (result.stdout or "") + (result.stderr or "")
        if "HTTP Error 429" in blob or "Too Many Requests" in blob:
            time.sleep(45)
            result = _run_ytdlp_once(cmd, progress)
    return result


def _run_ytdlp_once(cmd, progress=None):
    if not progress:
        r = subprocess.run(cmd, capture_output=True, text=True)
        return _Proc(r.returncode, r.stdout or "", r.stderr or "")

    out_chunks = []

    def _drain_stdout():
        try:
            for line in proc.stdout:
                out_chunks.append(line)
        except Exception:
            pass

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1)
    threading.Thread(target=_drain_stdout, daemon=True).start()

    err_chunks = []
    for line in proc.stderr:
        err_chunks.append(line)
        if len(err_chunks) > 400:
            del err_chunks[:100]
        if "|" in line and "%" in line:
            try:
                body = line.split("download:", 1)[-1]
                parts = body.split("|")
                pct = float(parts[0].replace("%", "").strip())
                speed = parts[1].strip() if len(parts) > 1 else ""
                eta = parts[2].strip() if len(parts) > 2 else ""
                progress(pct, speed, eta)
            except Exception:
                pass
    rc = proc.wait()
    return _Proc(rc, "".join(out_chunks), "".join(err_chunks))


def download_youtube_audio(url, work_dir, cookies_path=None, use_vpn=False,
                         progress=None):
    """Download the audio track of a YouTube URL as mono mp3.

    - use_vpn=True  -> run yt-dlp inside the configured network namespace (YT_NETNS),
                       i.e. through the free VPN. No cookie needed.
    - cookies_path  -> use this user's cookies.txt for the download.
    """
    os.makedirs(work_dir, exist_ok=True)
    out_tmpl = os.path.join(work_dir, "%(title).150B.%(ext)s")

    cmd = []
    vpn_ns = getattr(config, "YT_NETNS", "")
    if use_vpn and vpn_ns:
        cmd += ["ip", "netns", "exec", vpn_ns]

    cmd += [
        sys.executable, "-m", "yt_dlp",
        "--no-playlist",
    ] + SPEED_FLAGS + [
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "5",
        "--postprocessor-args", "ExtractAudio:-ac 1",
        "--output", out_tmpl,
        "--print", "after_move:filepath",
        "--remote-components", "ejs:github",
    ]

    if progress:
        cmd += ["--newline", "--progress-template", PROGRESS_TEMPLATE]

    # Proxy applies whenever no VPN namespace is actually used: either the user
    # picked the cookie method, or the VPN method is selected but this host has no
    # netns configured (fallback tunnel/proxy setup).
    if (not use_vpn) or (not getattr(config, "YT_NETNS", "")):
        proxy = getattr(config, "YT_PROXY", "")
        if proxy:
            cmd += ["--proxy", proxy]

    cookie_file = cookies_path or getattr(config, "YT_COOKIES_FILE", "")
    if cookie_file and os.path.exists(cookie_file):
        cmd += ["--cookies", cookie_file]

    cmd.append(url)

    result = _run_ytdlp(cmd, progress)
    if result.returncode != 0:
        msg = (result.stderr or "").strip()
        if "Sign in to confirm" in msg or "not a bot" in msg:
            msg += "\n\n💡 یوتیوب این IP را بلاک کرده. یا از روش «بدون کوکی» استفاده کن، یا کوکی خودت را دوباره بفرست."
        elif "No supported JavaScript runtime" in msg:
            msg += "\n\n💡 روی سرور یک JS runtime (Deno/Node) نصب نیست."
        elif "could not find" in msg.lower() or "not found" in msg.lower():
            msg += "\n\n💡 ممکن است VPN/namespace فعال نباشد."
        raise DownloadError(msg[-800:] or "yt-dlp failed")

    path = result.stdout.strip().splitlines()[-1].strip() if result.stdout.strip() else ""
    if not path or not os.path.exists(path):
        matches = glob.glob(os.path.join(work_dir, "*.mp3"))
        if matches:
            path = max(matches, key=os.path.getmtime)
    if not path or not os.path.exists(path):
        raise DownloadError("فایل دانلودشده از یوتیوب پیدا نشد.")
    return path

DL_VIDEO_FORMATS = {
    "360": "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]/best",
    "480": "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]/best",
    "720": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]/best",
    "1080": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best",
    "best": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
}


# Audio-only qualities (download flow): source format preselection + extraction target.
DL_AUDIO_SOURCE = {
    "m4a": "bestaudio[ext=m4a]/bestaudio",
    "opus": "bestaudio[ext=webm]/bestaudio",
    "flac": "bestaudio",
}
DL_AUDIO_TARGET = {"audio": "mp3", "m4a": "m4a", "opus": "opus", "flac": "flac"}


def download_youtube_video(url, work_dir, quality="best", cookies_path=None, use_vpn=False,
                         progress=None):
    """Download a YouTube video (or audio) at the requested quality.

    Returns the local file path of the downloaded media.
    """
    os.makedirs(work_dir, exist_ok=True)
    out_tmpl = os.path.join(work_dir, "%(title).150B.%(ext)s")

    cmd = []
    vpn_ns = getattr(config, "YT_NETNS", "")
    if use_vpn and vpn_ns:
        cmd += ["ip", "netns", "exec", vpn_ns]

    cmd += [sys.executable, "-m", "yt_dlp", "--no-playlist"] + SPEED_FLAGS

    audio_fmt = DL_AUDIO_TARGET.get(quality)
    if audio_fmt:
        if quality in DL_AUDIO_SOURCE:
            cmd += ["--format", DL_AUDIO_SOURCE[quality]]
        cmd += ["--extract-audio", "--audio-format", audio_fmt, "--audio-quality", "0"]
    else:
        fmt = DL_VIDEO_FORMATS.get(quality, DL_VIDEO_FORMATS["best"])
        cmd += ["--format", fmt, "--merge-output-format", "mp4"]

    cmd += [
        "--output", out_tmpl,
        "--print", "after_move:filepath",
        "--remote-components", "ejs:github",
    ]

    if progress:
        cmd += ["--newline", "--progress-template", PROGRESS_TEMPLATE]

    # Proxy applies whenever no VPN namespace is actually used: either the user
    # picked the cookie method, or the VPN method is selected but this host has no
    # netns configured (fallback tunnel/proxy setup).
    if (not use_vpn) or (not getattr(config, "YT_NETNS", "")):
        proxy = getattr(config, "YT_PROXY", "")
        if proxy:
            cmd += ["--proxy", proxy]

    cookie_file = cookies_path or getattr(config, "YT_COOKIES_FILE", "")
    if cookie_file and os.path.exists(cookie_file):
        cmd += ["--cookies", cookie_file]

    cmd.append(url)

    result = _run_ytdlp(cmd, progress)
    if result.returncode != 0:
        msg = (result.stderr or "").strip()
        if "Sign in to confirm" in msg or "not a bot" in msg:
            msg += "\n\n💡 یوتیوب این IP را بلاک کرده. یا «بدون کوکی» را امتحان کن، یا کوکی خودت را دوباره بفرست."
        elif "max-filesize" in msg.lower() or "larger than" in msg.lower():
            msg += "\n\n💡 فایل بزرگ‌تر از حد مجاز است؛ کیفیت پایین‌تر را انتخاب کن."
        elif "Requested format is not available" in msg:
            msg += "\n\n💡 این کیفیت برای این ویدیو موجود نیست؛ گزینه‌ی دیگری انتخاب کن."
        elif "No supported JavaScript runtime" in msg:
            msg += "\n\n💡 روی سرور یک JS runtime (Deno/Node) نصب نیست."
        raise DownloadError(msg[-900:] or "yt-dlp failed")

    path = result.stdout.strip().splitlines()[-1].strip() if result.stdout.strip() else ""
    if not path or not os.path.exists(path):
        matches = []
        for ext in ("mp4", "mkv", "webm", "mp3", "m4a", "opus", "ogg"):
            matches += glob.glob(os.path.join(work_dir, "*." + ext))
        if matches:
            path = max(matches, key=os.path.getmtime)
    if not path or not os.path.exists(path):
        raise DownloadError("فایل دانلودشده پیدا نشد.")
    return path


def list_playlist(url, cookies_path=None, use_vpn=False, max_items=25):
    """Return up to max_items video URLs from a YouTube playlist (no download)."""
    cmd = []
    vpn_ns = getattr(config, "YT_NETNS", "")
    if use_vpn and vpn_ns:
        cmd += ["ip", "netns", "exec", vpn_ns]

    cmd += [
        sys.executable, "-m", "yt_dlp",
        "--flat-playlist", "--skip-download",
        "--socket-timeout", "20", "--retries", "2",
        "--playlist-end", str(max_items),
        "--no-warnings",
        "--print", "%(url)s",
        "--remote-components", "ejs:github",
    ]

    # Proxy applies whenever no VPN namespace is actually used: either the user
    # picked the cookie method, or the VPN method is selected but this host has no
    # netns configured (fallback tunnel/proxy setup).
    if (not use_vpn) or (not getattr(config, "YT_NETNS", "")):
        proxy = getattr(config, "YT_PROXY", "")
        if proxy:
            cmd += ["--proxy", proxy]

    cookie_file = cookies_path or getattr(config, "YT_COOKIES_FILE", "")
    if cookie_file and os.path.exists(cookie_file):
        cmd += ["--cookies", cookie_file]

    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise DownloadError((result.stderr or "").strip()[-800:] or "yt-dlp playlist listing failed")
    urls = [ln.strip() for ln in (result.stdout or "").splitlines() if ln.strip().startswith("http")]
    return urls


def _net_prefix(use_vpn):
    cmd = []
    vpn_ns = getattr(config, "YT_NETNS", "")
    if use_vpn and vpn_ns:
        cmd += ["ip", "netns", "exec", vpn_ns]
    return cmd


def _add_proxy_cookies(cmd, use_vpn, cookies_path):
    # Proxy applies whenever no VPN namespace is actually used: either the user
    # picked the cookie method, or the VPN method is selected but this host has no
    # netns configured (fallback tunnel/proxy setup).
    if (not use_vpn) or (not getattr(config, "YT_NETNS", "")):
        proxy = getattr(config, "YT_PROXY", "")
        if proxy:
            cmd += ["--proxy", proxy]
    cookie_file = cookies_path or getattr(config, "YT_COOKIES_FILE", "")
    if cookie_file and os.path.exists(cookie_file):
        cmd += ["--cookies", cookie_file]
    return cmd


def get_youtube_info(url, cookies_path=None, use_vpn=False, timeout=45):
    cmd = _net_prefix(use_vpn)
    cmd += [sys.executable, "-m", "yt_dlp", "--no-playlist", "--skip-download",
            "--socket-timeout", "15", "--retries", "1",
            "--dump-single-json", "--remote-components", "ejs:github"]
    cmd = _add_proxy_cookies(cmd, use_vpn, cookies_path)
    cmd.append(url)
    # Single fast attempt (the caller animates the wait); only a hard 429 gets
    # one 20s backoff retry. Keeps the "checking video" step short.
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise DownloadError("خواندن اطلاعات ویدیو زمان‌بر شد (timeout).")
    blob = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        if "HTTP Error 429" in blob or "Too Many Requests" in blob:
            time.sleep(20)
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                raise DownloadError("خواندن اطلاعات ویدیو زمان‌بر شد (timeout).")
            blob = (r.stdout or "") + (r.stderr or "")
            if r.returncode != 0:
                raise DownloadError(
                    "یوتیوب موقتاً درخواست‌های این سرور را محدود کرده (429). "
                    "چند دقیقه بعد دوباره امتحان کن.")
        else:
            raise DownloadError((r.stderr or "").strip()[-500:] or "خواندن اطلاعات ویدیو ناموفق بود.")
    try:
        info = json.loads(r.stdout)
    except Exception:
        raise DownloadError("پاسخ اطلاعات ویدیو قابل خواندن نبود.")
    # Populate the shared cache so follow-up calls (size probe, quality menu)
    # don't re-run the full extraction.
    try:
        _INFO_CACHE[(url, bool(cookies_path), bool(use_vpn))] = (time.time(), info)
    except Exception:
        pass
    return info


def download_youtube_thumbnail(url, work_dir, cookies_path=None, use_vpn=False):
    """Download the video thumbnail (jpg). Returns (path, title)."""
    os.makedirs(work_dir, exist_ok=True)
    out_tmpl = os.path.join(work_dir, "thumb.%(ext)s")
    cmd = _net_prefix(use_vpn)
    cmd += [sys.executable, "-m", "yt_dlp", "--no-playlist", "--skip-download",
            "--write-thumbnail", "--convert-thumbnails", "jpg",
            "--socket-timeout", "20", "--retries", "2", "--no-simulate",
            "--print", "%(title)s",
            "--output", out_tmpl, "--remote-components", "ejs:github"]
    cmd = _add_proxy_cookies(cmd, use_vpn, cookies_path)
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=150)
    except subprocess.TimeoutExpired:
        raise DownloadError("دانلود تامنیل زمان‌بر شد (timeout).")
    title = ""
    for ln in (r.stdout or "").splitlines():
        if ln.strip():
            title = ln.strip()
    files = (glob.glob(os.path.join(work_dir, "thumb*.jpg"))
             + glob.glob(os.path.join(work_dir, "thumb*.webp"))
             + glob.glob(os.path.join(work_dir, "thumb*.png")))
    if not files:
        raise DownloadError("تامنیل این ویدیو پیدا نشد.")
    return max(files, key=os.path.getmtime), title


# Metadata for size estimates, cached so the background menu probe does not pay
# the (slow VPN) extraction cost again.
_INFO_CACHE = {}
_INFO_TTL = 1800
_INFO_LOCK = threading.Lock()
_INFO_INFLIGHT = {}


def _cached_info(url, cookies_path, use_vpn, timeout=150):
    key = (url, bool(cookies_path), bool(use_vpn))
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
        info = get_youtube_info(url, cookies_path, use_vpn, timeout=timeout)
        _INFO_CACHE[key] = (time.time(), info)
        if len(_INFO_CACHE) > 40:
            for k in sorted(_INFO_CACHE, key=lambda k: _INFO_CACHE[k][0])[:10]:
                _INFO_CACHE.pop(k, None)
        return info
    except Exception:
        return None
    finally:
        _INFO_INFLIGHT.pop(key, None)
        ev.set()


def probe_sizes(url, cookies_path=None, use_vpn=False):
    """Best-effort estimate (MB) of the download size per quality key."""
    info = _cached_info(url, cookies_path, use_vpn)
    if not info and not use_vpn:
        info = _cached_info(url, cookies_path, True)
    if not info:
        return {}
    dur = info.get("duration") or 0
    fmts = info.get("formats") or []

    def est(f):
        s = f.get("filesize") or f.get("filesize_approx")
        if s:
            return s
        tbr = f.get("tbr") or 0
        if tbr and dur:
            return tbr * 1000 / 8 * dur
        return None

    def mb(x):
        return int(round(x / 1048576)) if x else None

    audios = [f for f in fmts if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")]
    a = max(audios, key=lambda f: (f.get("abr") or f.get("tbr") or 0)) if audios else None
    a_size = est(a) if a else None

    result = {}
    for h in (360, 480, 720, 1080):
        cands = [f for f in fmts
                 if f.get("vcodec") not in (None, "none") and (f.get("height") or 0) and f.get("height") <= h]
        if not cands:
            continue
        v = max(cands, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))
        total = (est(v) or 0) + (a_size or 0)
        result[str(h)] = mb(total) if total else None

    allv = [f for f in fmts if f.get("vcodec") not in (None, "none")]
    if allv:
        b = max(allv, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))
        total = (est(b) or 0) + (a_size or 0)
        result["best"] = mb(total) if total else None
    result["audio"] = mb(a_size) if a_size else None
    result["m4a"] = result["audio"]
    return result

def download_youtube_info_txt(url, work_dir, cookies_path=None, use_vpn=False):
    """Write the video's title, metadata and full description to a .txt file.

    Returns (path, title). No media is downloaded.
    """
    info = get_youtube_info(url, cookies_path, use_vpn, timeout=150)
    title = (info.get("title") or "youtube_info").strip()
    lines_out = [f"\U0001f3ac {title}", "", f"\U0001f517 {info.get('webpage_url') or url}"]
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
            stamp = f"{int(st) // 60:02}:{int(st) % 60:02}" if st is not None else "?"
            lines_out.append(f"  \u2022 {stamp} \u2014 {ch.get('title') or ''}")
    lines_out += ["", "\u2500" * 30, "\U0001f4dd description:", "",
                  (info.get("description") or "").strip() or "(none)"]
    os.makedirs(work_dir, exist_ok=True)
    path = os.path.join(work_dir, sanitize_filename(title) + "_info.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines_out).rstrip() + "\n")
    return path, title


def download_youtube_subtitle(url, work_dir, lang=None, cookies_path=None, use_vpn=False):
    """Download YouTube's ready subtitle as SRT. lang=None -> the original track.

    Returns (path, lang_used, kind, title).
    """
    os.makedirs(work_dir, exist_ok=True)
    info = get_youtube_info(url, cookies_path, use_vpn)
    manual = list((info.get("subtitles") or {}).keys())
    auto = list((info.get("automatic_captions") or {}).keys())
    orig = info.get("language")
    title = info.get("title") or "subtitle"
    original_wanted = not lang or lang in ("original", "")

    if original_wanted:
        # Prefer the video's own-language track. yt-dlp marks the untranslated
        # original with a "-orig" suffix (e.g. "en-orig"); plain "<lang>" is the
        # original ASR track in automatic_captions. Google-translated tracks are
        # only a last resort.
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

    out_tmpl = os.path.join(work_dir, "sub.%(ext)s")
    cmd = _net_prefix(use_vpn)
    cmd += [sys.executable, "-m", "yt_dlp", "--no-playlist", "--skip-download",
            "--socket-timeout", "20", "--retries", "2"]
    if kind == "manual":
        cmd += ["--write-subs"]
    else:
        cmd += ["--write-auto-subs"]
    cmd += ["--sub-langs", target, "--sub-format", "srt/best", "--convert-subs", "srt",
            "--sleep-subtitles", "5",
            "--output", out_tmpl, "--remote-components", "ejs:github"]
    cmd = _add_proxy_cookies(cmd, use_vpn, cookies_path)
    cmd.append(url)
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
            time.sleep(45)
            continue
        break
    if not files:
        if not original_wanted and "HTTP Error 429" in blob:
            # YouTube clamps auto-TRANSLATED caption downloads hardest. Fall back
            # to the original track so the user still gets an SRT; they can use
            # the bot's own subtitle-translation feature for the target language.
            try:
                path, tgt, kd, ttl = download_youtube_subtitle(
                    url, work_dir, None, cookies_path, use_vpn)
                return path, tgt, kd + " (ترجمهٔ خودکار یوتیوب محدود بود؛ نسخهٔ اصلی)", ttl
            except Exception:
                pass
        if "HTTP Error 429" in blob or "Too Many Requests" in blob:
            raise DownloadError(
                "یوتیوب موقتاً درخواست‌های این سرور را محدود کرده (429). "
                "چند دقیقه بعد دوباره امتحان کن.")
        if original_wanted:
            raise DownloadError("این ویدیو زیرنویس آماده ندارد.")
        raise DownloadError(
            f"این ویدیو زیرنویس به زبان «{target}» ندارد (و ترجمهٔ خودکار هم موجود نیست).")
    path = max(files, key=os.path.getmtime)
    return path, target, kind, title
