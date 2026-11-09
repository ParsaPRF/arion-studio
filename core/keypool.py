"""Pools of server-side API keys (one per line), per provider."""

import os

from . import config


def _path(provider="groq"):
    if provider == "gemini":
        return config.GEMINI_KEYS_FILE
    if provider == "openrouter":
        return config.OPENROUTER_KEYS_FILE
    return config.SERVER_KEYS_FILE


def load_keys(provider="groq"):
    path = _path(provider)
    if not path or not os.path.exists(path):
        return []
    out, seen = [], set()
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                k = line.strip()
                if not k or k.startswith("#"):
                    continue
                if k not in seen:
                    seen.add(k)
                    out.append(k)
    except OSError:
        return []
    return out


def count(provider="groq"):
    return len(load_keys(provider))


def add_key(key, provider="groq"):
    """Append a key to the provider pool. Returns (added, total)."""
    key = (key or "").strip()
    if not key:
        return False, count(provider)
    keys = load_keys(provider)
    if key in keys:
        return False, len(keys)
    path = _path(provider)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(key + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return True, len(keys) + 1