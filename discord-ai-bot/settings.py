"""Soru-cevap AI botu ayarlari."""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

OWNER_ID = int(os.environ.get("BOT_OWNER_ID", "1324038081896251415"))
DEFAULT_CHAT_MODEL = "gpt-4o-mini"
DEFAULT_POLLINATIONS_CHAT_MODEL = "openai"


def _clean(value: str) -> str:
    for ch in "\r\n\ufeff\u200b":
        value = value.replace(ch, "")
    value = value.strip().strip('"').strip("'")
    if value.lower().startswith("bot "):
        value = value[4:].strip()
    return value


def load_env_file() -> dict[str, str]:
    if not ENV_PATH.is_file():
        return {}
    for enc in ("utf-8-sig", "utf-8", "utf-16", "utf-16-le"):
        try:
            text = ENV_PATH.read_text(encoding=enc)
            break
        except UnicodeError:
            continue
    else:
        return {}

    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        out[key.strip().upper()] = _clean(val)
    return out


def get_token() -> str:
    env = load_env_file()
    return _clean(env.get("DISCORD_TOKEN", os.environ.get("DISCORD_TOKEN", "")))


def get_guild_id() -> str:
    env = load_env_file()
    return _clean(env.get("DISCORD_GUILD_ID", os.environ.get("DISCORD_GUILD_ID", "")))


def get_openai_api_key() -> str:
    env = load_env_file()
    return _clean(env.get("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", "")))


def get_chat_model() -> str:
    env = load_env_file()
    raw = _clean(env.get("CHAT_MODEL", os.environ.get("CHAT_MODEL", DEFAULT_CHAT_MODEL)))
    return raw or DEFAULT_CHAT_MODEL


def get_system_prompt() -> str:
    env = load_env_file()
    default = (
        "Sen yardimsever bir Discord asistanisin. "
        "Turkce sorulara Turkce, Ingilizce sorulara Ingilizce cevap ver. "
        "Kisa ve net ol; gereksiz uzatma. "
        "Bilmedigin konularda tahmin etme, acikca belirt."
    )
    return env.get("SYSTEM_PROMPT", os.environ.get("SYSTEM_PROMPT", default)) or default


def get_chat_cooldown_sec() -> int:
    env = load_env_file()
    raw = _clean(env.get("CHAT_COOLDOWN_SEC", os.environ.get("CHAT_COOLDOWN_SEC", "10")))
    try:
        return max(0, int(raw))
    except ValueError:
        return 10


def get_max_reply_chars() -> int:
    env = load_env_file()
    raw = _clean(env.get("MAX_REPLY_CHARS", os.environ.get("MAX_REPLY_CHARS", "1900")))
    try:
        return min(2000, max(200, int(raw)))
    except ValueError:
        return 1900


def get_chat_provider() -> str:
    """openai | pollinations | auto (OpenAI duserse ucretsiz yedek)."""
    env = load_env_file()
    raw = _clean(env.get("CHAT_PROVIDER", os.environ.get("CHAT_PROVIDER", "auto")))
    if raw in ("openai", "pollinations", "auto"):
        return raw
    return "auto"


def get_pollinations_api_key() -> str:
    env = load_env_file()
    return _clean(env.get("POLLINATIONS_API_KEY", os.environ.get("POLLINATIONS_API_KEY", "")))


def get_pollinations_chat_model() -> str:
    env = load_env_file()
    raw = _clean(
        env.get("POLLINATIONS_CHAT_MODEL", os.environ.get("POLLINATIONS_CHAT_MODEL", DEFAULT_POLLINATIONS_CHAT_MODEL))
    )
    return raw or DEFAULT_POLLINATIONS_CHAT_MODEL


def get_enable_mentions() -> bool:
    """Portalda Message Content Intent aciksa .env'de ENABLE_MENTIONS=1 yap."""
    env = load_env_file()
    raw = _clean(env.get("ENABLE_MENTIONS", os.environ.get("ENABLE_MENTIONS", "0")))
    return raw.lower() in ("1", "true", "yes", "evet")


def check_token(token: str) -> tuple[bool, str]:
    if not token:
        return False, "Token bos — .env dosyasinda DISCORD_TOKEN=... olmali"
    req = urllib.request.Request(
        "https://discord.com/api/v10/users/@me",
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": "DiscordBot (https://github.com/discord/discord-api-docs)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return True, f"Token gecerli (@{data.get('username', '?')})"
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "Token gecersiz (401). Bot -> Reset Token, .env guncelle."
        return False, f"Discord API hata: {e.code}"
    except Exception as e:
        return False, f"Baglanti hatasi: {e}"
