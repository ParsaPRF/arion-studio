"""Local (desktop) configuration for ArionStudio.

Same variable names as the arion-bot config so the copied modules run unmodified,
but tuned for a Windows PC: no network namespaces / VPN flags by default and
temp/output folders created inside the project.
"""

import os

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)

# --- Keys -------------------------------------------------------------------
# Optional server-style defaults; the GUI settings are the primary source.
DEFAULT_GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
DEFAULT_OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()

# --- Folders ----------------------------------------------------------------
_work = os.getenv("WORK_DIR", "") or os.path.join(PROJECT_DIR, "work")
WORK_DIR = os.path.normpath(_work)
LOG_DIR = os.getenv("LOG_DIR") or os.path.join(PROJECT_DIR, "logs")
COOKIES_DIR = os.getenv("COOKIES_DIR") or os.path.join(PROJECT_DIR, "cookies")
KEYS_DIR = os.getenv("KEYS_DIR") or os.path.join(PROJECT_DIR, "keys")

# --- Queues / limits (kept for module compatibility) ------------------------
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "200"))
WORKERS = int(os.getenv("WORKERS", "1"))
CLEANUP_DELAY_SECONDS = int(os.getenv("CLEANUP_DELAY_SECONDS", "0"))
QUEUE_LARGE_MB = int(os.getenv("QUEUE_LARGE_MB", "200"))
PLAYLIST_MAX = int(os.getenv("PLAYLIST_MAX", "25"))
STALE_MAX_AGE = int(os.getenv("STALE_MAX_AGE", "999999999"))
CLEANUP_ENABLED = os.getenv("CLEANUP_ENABLED", "0").strip() not in ("0", "false", "False")
DB_PATH = os.getenv("DB_PATH") or os.path.join(PROJECT_DIR, "data", "arion.db")

# Telegram-only values; the desktop app never uses them.
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_BOT_API_URL = ""
ADMIN_IDS = set()

# --- Key pools (GUI can append keys; same file format as arion-bot) ---------
SERVER_KEYS_FILE = os.getenv("SERVER_KEYS_FILE") or os.path.join(KEYS_DIR, "groq_keys.txt")
GEMINI_KEYS_FILE = os.getenv("GEMINI_KEYS_FILE") or os.path.join(KEYS_DIR, "gemini_keys.txt")
OPENROUTER_KEYS_FILE = os.getenv("OPENROUTER_KEYS_FILE") or os.path.join(KEYS_DIR, "openrouter_keys.txt")

# Free models only, strongest first: the deep pass reviews an existing SRT, so a
# long-context instruction model is all it needs.  Override with
# OPENROUTER_MODELS="vendor/model:free,..." (paid ids work too, they just cost).
_or_default = (
    "nvidia/nemotron-3-ultra-550b-a55b:free,"
    "nvidia/nemotron-3.5-lightning:free,"
    "google/gemma-4-31b-it:free,"
    "google/gemma-4-26b-a4b-it:free,"
    "dots-studio/dots-3-note-preview:free,"
    "xingchen-agi/xing4.0-29b-a4b:free"
)
OPENROUTER_MODELS = [m.strip() for m in os.getenv("OPENROUTER_MODELS", _or_default).split(",") if m.strip()]
OPENROUTER_BASE = (os.getenv("OPENROUTER_BASE", "https://openrouter.ai/api/v1").strip().rstrip("/"))
OPENROUTER_TIMEOUT = int(os.getenv("OPENROUTER_TIMEOUT", "600"))

_gem_default = (
    "gemini-flash-latest,gemini-3.5-flash,gemini-2.5-flash,"
    "gemini-2.0-flash,gemini-1.5-flash"
)
GEMINI_MODELS = [m.strip() for m in os.getenv("GEMINI_MODELS", _gem_default).split(",") if m.strip()]

# --- YouTube ----------------------------------------------------------------
# Desktop defaults: no netns/VPN (that is a server-only feature). The optional
# proxy can still be set from the GUI and is passed to yt-dlp.
YT_COOKIES_FILE = os.getenv("YT_COOKIES_FILE", "").strip()
YT_PROXY = os.getenv("YT_PROXY", "").strip()
YT_NETNS = ""  # network namespaces are Linux-only; the desktop app runs without.

# --- Models / chunking ------------------------------------------------------
GEMINI_USE_VPN = False  # no netns on the desktop
GEMINI_CHUNK_MINUTES = int(os.getenv("GEMINI_CHUNK_MINUTES", "5"))
CHUNK_MINUTES = int(os.getenv("CHUNK_MINUTES", "20"))

# --- Backup (kept for compatibility; unused in the GUI) ---------------------
BACKUP_REMOTES = [r.strip() for r in os.getenv("BACKUP_REMOTES", "gdrive").split(",") if r.strip()] or ["gdrive"]
BACKUP_FOLDER = os.getenv("BACKUP_FOLDER", "ArionBackups").strip() or "ArionBackups"

# --- Job timings (unused locally; kept for module compatibility) ------------
STUCK_MINUTES = int(os.getenv("STUCK_MINUTES", "999"))
RESUME_TIMEOUT_SECONDS = int(os.getenv("RESUME_TIMEOUT_SECONDS", "1200"))
DELIVERY_TIMEOUT_SECONDS = int(os.getenv("DELIVERY_TIMEOUT_SECONDS", "120"))

# --- Animations (the engine's own spinner styles; unused by the desktop GUI) -
ANIM_ENABLED = True
ANIM_CELEBRATE = True
ANIM_DELAY = 0.32
ANIM_SPINNER = "dots"
