import re
from datetime import timedelta

# Subtitle styles
STYLE_SENTENCE = "sentence"   # standard sentence/paragraph cue
STYLE_SHORT = "short"         # short, readable lines (best for translation)
STYLE_WORD = "word"           # word by word


def parse_srt_time(t):
    """Parse ``HH:MM:SS,mmm`` (also accepts '.' and ``MM:SS,mmm``)."""
    t = (t or "").strip().replace(".", ",")
    parts = t.split(":")
    if len(parts) == 3:
        h, m, s_ms = parts
    elif len(parts) == 2:
        h, m, s_ms = "0", parts[0], parts[1]
    else:
        raise ValueError(f"bad timestamp: {t!r}")
    if "," in s_ms:
        s, ms = s_ms.split(",", 1)
    else:
        s, ms = s_ms, "0"
    ms = (ms + "000")[:3]
    return timedelta(hours=int(h or 0), minutes=int(m or 0),
                     seconds=int(s or 0), milliseconds=int(ms or 0))


def format_srt_time(td):
    total_ms = int(td.total_seconds() * 1000)
    h, rem = divmod(total_ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def seconds_to_srt_time(seconds):
    return format_srt_time(timedelta(seconds=float(seconds)))


def _items_to_srt(items):
    """items: iterable of (start, end, text). Returns SRT string."""
    blocks = []
    for start, end, text in items:
        text = (text or "").strip()
        if start is None or end is None or not text:
            continue
        try:
            start, end = float(start), float(end)
        except (TypeError, ValueError):
            continue
        if end <= start:
            if end <= 0:
                continue
            start = max(0.0, end - 0.4)
        blocks.append(
            f"{len(blocks) + 1}\n"
            f"{seconds_to_srt_time(start)} --> {seconds_to_srt_time(end)}\n"
            f"{text}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def segments_to_srt(segments):
    """Sentence/paragraph style from OpenAI-style verbose_json segments."""
    return _items_to_srt(
        (s.get("start"), s.get("end"), s.get("text")) for s in (segments or [])
    )


def words_to_srt(words):
    """Word-by-word style: one subtitle block per word."""
    return _items_to_srt(
        (w.get("start"), w.get("end"), w.get("word")) for w in (words or [])
    )


def group_words(words, max_chars=42, max_words=7):
    """Group words into short readable lines using word-level timestamps."""
    groups = []
    cur = []
    cur_len = 0
    for w in words or []:
        text = (w.get("word") or "").strip()
        if not text:
            continue
        add_len = len(text) + (1 if cur else 0)
        if cur and (cur_len + add_len > max_chars or len(cur) >= max_words):
            groups.append(cur)
            cur, cur_len = [], 0
            add_len = len(text)
        cur.append(w)
        cur_len += add_len
    if cur:
        groups.append(cur)

    result = []
    for g in groups:
        result.append((g[0].get("start"), g[-1].get("end"),
                       " ".join((x.get("word") or "").strip() for x in g)))
    return result


def short_lines_to_srt(words, max_chars=42, max_words=7):
    return _items_to_srt(group_words(words, max_chars, max_words))


def build_srt(segments, words, style=STYLE_SENTENCE, max_chars=42, max_words=7):
    """Build SRT text in the requested style, with graceful fallbacks."""
    if style == STYLE_WORD and words:
        return words_to_srt(words)
    if style == STYLE_SHORT and words:
        return short_lines_to_srt(words, max_chars, max_words)
    if segments:
        return segments_to_srt(segments)
    if words:  # fallback: no segments returned, use grouped words
        return short_lines_to_srt(words, max_chars, max_words)
    return ""


def merge_srt_chunks(chunk_paths, offsets, windows=None):
    """Merge per-chunk SRT files into one, sorted and overlap-free.

    Each block is shifted by its chunk offset. If `windows` (list of
    (start, end) seconds) is given, blocks are clamped to their chunk window so
    small drift at chunk boundaries cannot produce overlaps. Blocks are then
    sorted by start time and trimmed so the final file never contains
    overlapping cues (players render those badly).
    """
    entries = []
    for i, (path, offset) in enumerate(zip(chunk_paths, offsets)):
        win = windows[i] if windows else None
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            continue
        for block in re.split(r"\r?\n\s*\r?\n", (content or "").strip()):
            lines = block.split("\n")
            timing_idx = next((k for k, ln in enumerate(lines) if "-->" in ln), None)
            if timing_idx is None:
                continue
            try:
                start_s, end_s = [p.strip() for p in
                                  lines[timing_idx].split("-->", 1)]
                start_t = parse_srt_time(start_s) + timedelta(seconds=offset)
                end_t = parse_srt_time(end_s) + timedelta(seconds=offset)
            except ValueError:
                continue
            text = "\n".join(lines[timing_idx + 1:]).strip()
            if not text:
                continue
            if win is not None:
                w_start = timedelta(seconds=win[0])
                w_end = timedelta(seconds=win[1])
                if start_t > w_end or end_t < w_start:
                    continue
                if start_t < w_start:
                    start_t = w_start
                if end_t > w_end:
                    end_t = w_end
            if end_t <= start_t:
                continue
            entries.append([start_t, end_t, text])

    entries.sort(key=lambda e: (e[0], e[1]))
    out, prev_end = [], None
    for start_t, end_t, text in entries:
        if prev_end is not None and start_t < prev_end:
            if out and text == out[-1][2]:
                continue  # exact duplicate from two neighbouring chunks
            start_t = prev_end  # keep order, kill overlap
            if end_t <= start_t:
                continue
        out.append([start_t, end_t, text])
        prev_end = end_t

    blocks = []
    for idx, (start_t, end_t, text) in enumerate(out, 1):
        blocks.append(f"{idx}\n{format_srt_time(start_t)} --> "
                      f"{format_srt_time(end_t)}\n{text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def srt_to_plain_text(srt_content):
    lines = []
    for block in re.split(r"\r?\n\s*\r?\n", (srt_content or "").strip()):
        parts = block.split("\n")
        timing_idx = next((k for k, ln in enumerate(parts) if "-->" in ln), None)
        if timing_idx is None:
            continue
        text = " ".join(ln.strip() for ln in parts[timing_idx + 1:] if ln.strip())
        if text.strip():
            lines.append(text.strip())
    return "\n".join(lines)
