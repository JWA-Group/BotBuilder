from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt

from backend.core.config import ALGORITHM, SECRET_KEY, ACCESS_TOKEN_EXPIRE_MINUTES


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def create_verification_token(email: str) -> str:
    """Токен для подтверждения email (24 часа)."""
    import secrets
    from itsdangerous import URLSafeTimedSerializer
    s = URLSafeTimedSerializer(SECRET_KEY, salt="email-verify")
    return s.dumps({"email": email}, salt="email-verify")


def verify_email_token(token: str, max_age: int = 86400) -> Optional[str]:
    """Проверяет токен подтверждения, возвращает email или None. max_age в секундах (24ч)."""
    from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
    s = URLSafeTimedSerializer(SECRET_KEY, salt="email-verify")
    try:
        data = s.loads(token, salt="email-verify", max_age=max_age)
        return data.get("email")
    except (BadSignature, SignatureExpired):
        return None
