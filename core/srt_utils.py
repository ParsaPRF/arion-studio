from datetime import timedelta

# Subtitle styles
STYLE_SENTENCE = "sentence"   # جمله/پاراگراف استاندارد
STYLE_SHORT = "short"         # خطوط کوتاه و خوانا (خوب برای ترجمه)
STYLE_WORD = "word"           # کلمه به کلمه


def parse_srt_time(t):
    h, m, s_ms = t.strip().split(":")
    s, ms = s_ms.split(",")
    return timedelta(hours=int(h), minutes=int(m), seconds=int(s), milliseconds=int(ms))


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
    """Merge per-chunk SRT files into one.

    Each block is shifted by its chunk offset. If `windows` (list of
    (start, end) seconds) is given, blocks are clamped to their chunk window so
    small drift at chunk boundaries cannot produce overlaps.
    """
    all_blocks = []
    for i, (path, offset) in enumerate(zip(chunk_paths, offsets)):
        win = windows[i] if windows else None
        with open(path, encoding="utf-8") as f:
            blocks = f.read().strip().split("\n\n")
        for b in blocks:
            lines = b.split("\n")
            if len(lines) < 2:
                continue
            try:
                start, end = lines[1].split(" --> ")
                start_t = parse_srt_time(start) + timedelta(seconds=offset)
                end_t = parse_srt_time(end) + timedelta(seconds=offset)
            except ValueError:
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
            lines[1] = f"{format_srt_time(start_t)} --> {format_srt_time(end_t)}"
            all_blocks.append("\n".join(lines))

    final = []
    for idx, block in enumerate(all_blocks, 1):
        lines = block.split("\n")
        lines[0] = str(idx)
        final.append("\n".join(lines))
    return "\n\n".join(final) + "\n"


def srt_to_plain_text(srt_content):
    lines = []
    for block in srt_content.strip().split("\n\n"):
        parts = block.split("\n")
        if len(parts) >= 3:
            lines.append(" ".join(parts[2:]).strip())
    return "\n".join(lines)
