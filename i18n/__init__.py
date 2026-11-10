"""Internationalisation for Arion Studio.

English is the default language: a first-time user gets an English interface,
and Persian is one dropdown away. Every user-visible string in the app goes
through :func:`t`, so nothing is hard-coded to one language any more.

Catalogs live next to this file as ``cat_<area>.py`` modules, each exposing a
single ``CATALOG`` dict::

    CATALOG = {
        "ui.btn.start": {"en": "Start", "fa": "شروع"},
    }

Keeping one module per area means two people (or two agents) can translate
separate parts of the app without touching the same file. Missing keys fall
back to English and then to the key itself, so a half-translated catalog can
never crash the UI.

Usage::

    from i18n import t

    button = ctk.CTkButton(text=t("ui.btn.start"))
    log(t("dl.log.finished", path=path))
"""

from __future__ import annotations

import pkgutil
import threading

DEFAULT_LANGUAGE = "en"

#: Selectable languages, each written in its own script.
LANGUAGES = [
    ("en", "English"),
    ("fa", "فارسی"),
]

_lock = threading.RLock()
_current = DEFAULT_LANGUAGE
_catalog = None
_entries_by_module = {}


def language_codes():
    return [code for code, _ in LANGUAGES]


def language_label(code):
    for candidate, label in LANGUAGES:
        if candidate == code:
            return label
    return str(code)


def _load():
    """Merge every ``cat_*.py`` module in this package into one catalog."""
    global _catalog
    if _catalog is not None:
        return _catalog

    catalog = {}
    for info in pkgutil.iter_modules(__path__):
        if not info.name.startswith("cat_"):
            continue
        module = __import__(f"{__name__}.{info.name}", fromlist=["CATALOG"])
        entries = getattr(module, "CATALOG", None)
        if not isinstance(entries, dict):
            continue
        _entries_by_module[info.name] = entries
        for key, langs in entries.items():
            catalog.setdefault(key, {}).update(langs or {})
    _catalog = catalog
    return catalog


def reload_catalogs():
    """Drop the merged cache (used by tests)."""
    global _catalog
    with _lock:
        _catalog = None
        _entries_by_module.clear()


def catalog():
    return _load()


def entries_by_module():
    _load()
    return dict(_entries_by_module)


def missing_keys():
    """Keys referenced anywhere but absent from the catalog."""
    return sorted(k for k, v in _load().items() if not v.get(DEFAULT_LANGUAGE))


def set_language(code):
    """Select the active language; unknown codes fall back to English."""
    global _current
    code = str(code or "").strip().lower()
    if code not in language_codes():
        code = DEFAULT_LANGUAGE
    with _lock:
        _current = code
    return _current


def get_language():
    return _current


def is_rtl(code=None):
    """True for right-to-left languages (used for text anchors)."""
    return (code or _current) in ("fa", "ar", "he", "ur")


def t(key, **kwargs):
    """Translate ``key`` into the active language.

    ``kwargs`` are interpolated into ``{placeholders}``. Unknown keys and
    failed interpolations return the best text available instead of raising,
    because a missing translation must never break a job.
    """
    entries = _load()
    langs = entries.get(key)
    if not langs:
        return key
    text = langs.get(_current) or langs.get(DEFAULT_LANGUAGE) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text
