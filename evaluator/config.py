import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


# ── LLM ─────────────────────────────────────────────────────
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-oss:20b")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://172.20.201.87:9007/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.0"))

# ── Langfuse ─────────────────────────────────────────────────
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "")
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")

LANGFUSE_ENABLED = bool(
    LANGFUSE_HOST and LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY
)

# ── Evaluation ───────────────────────────────────────────────
CHUNK_SIZE_LIMIT = int(os.getenv("CHUNK_SIZE_LIMIT", "6000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "500"))

# ── Tree-sitter language map ─────────────────────────────────
LANGUAGE_EXTENSION_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
    ".rb": "ruby",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".cs": "c_sharp",
    ".php": "php",
    ".rs": "rust",
    ".kt": "kotlin",
    ".swift": "swift",
    ".scala": "scala",
    ".r": "r",
    ".lua": "lua",
    ".sh": "bash",
    ".bash": "bash",
}

# ── Sensitive file patterns (skip during evaluation) ─────────
SENSITIVE_FILE_PATTERNS = [
    r"\.env",
    r"package-lock\.json",
    r"yarn\.lock",
    r"go\.sum",
    r"\.pem$",
    r"\.key$",
    r"\.db$",
    r"\.sqlite$",
    r"\.jpg$",
    r"\.jpeg$",
    r"\.png$",
    r"\.gif$",
    r"\.ico$",
    r"\.svg$",
    r"\.woff",
    r"\.ttf$",
    r"node_modules/",
    r"vendor/",
    r"bin/",
    r"\.exe$",
    r"\.dll$",
    r"\.so$",
    r"__pycache__/",
    r"\.pyc$",
]

# ── Retry ────────────────────────────────────────────────────
LLM_RETRY_ATTEMPTS = 3
LLM_RETRY_MIN_WAIT = 4
LLM_RETRY_MAX_WAIT = 10
