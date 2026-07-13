import os
import json
import time
import urllib.request

# Секрет для JWT (в продакшене брать из переменной окружения)
SECRET_KEY = os.environ.get("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 дней

# Email (SMTP) — для подтверждения регистрации
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "noreply@example.com")
# Если пусто — ссылки выводятся в консоль (режим разработки)

# Google OAuth
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")

# Базовый URL приложения (для ссылок в письмах и OAuth callback).
# Если указан явный HTTPS (например ngrok) — используется он.
# Если localhost — при запросе подставляется URL из ngrok (127.0.0.1:4040/api/tunnels), если ngrok запущен.
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8000")

# Кэш для автоопределения ngrok URL (значение, время получения)
_ngrok_base_url_cache = None
_ngrok_cache_ttl = 60  # секунд


def get_app_base_url() -> str:
    """
    Возвращает текущий базовый URL приложения.
    Если APP_BASE_URL уже HTTPS (не localhost) — возвращает его.
    Иначе пробует взять URL из запущенного ngrok (localhost:4040), с кэшем 60 сек.
    Так не нужен перезапуск сервера при запуске ngrok.
    """
    base = (APP_BASE_URL or "").strip().rstrip("/")
    if base and base.lower().startswith("https://"):
        return base
    if base and "localhost" not in base.lower() and "127.0.0.1" not in base:
        return base

    global _ngrok_base_url_cache
    now = time.time()
    if _ngrok_base_url_cache is not None:
        url, cached_at = _ngrok_base_url_cache
        if now - cached_at < _ngrok_cache_ttl and url:
            return url

    try:
        req = urllib.request.Request(
            "http://127.0.0.1:4040/api/tunnels",
            headers={"User-Agent": "WebAppCreateBots/1.0"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        _ngrok_base_url_cache = (None, now)
        return base or "http://localhost:8000"

    tunnels = data.get("tunnels") or []
    for t in tunnels:
        pub = (t.get("public_url") or "").strip()
        if pub.lower().startswith("https://"):
            _ngrok_base_url_cache = (pub.rstrip("/"), now)
            return pub.rstrip("/")

    _ngrok_base_url_cache = (None, now)
    return base or "http://localhost:8000"
