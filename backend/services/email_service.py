"""Сервис отправки email для подтверждения регистрации."""
import asyncio
import logging
from typing import Optional

from backend.core.config import (
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASSWORD,
    SMTP_FROM,
    get_app_base_url,
)

logger = logging.getLogger(__name__)


async def send_verification_email(to_email: str, token: str, verify_url: Optional[str] = None) -> bool:
    """Отправляет письмо с ссылкой для подтверждения email. verify_url можно не передавать — подставится из get_app_base_url()."""
    if not verify_url:
        verify_url = f"{get_app_base_url().rstrip('/')}/auth/verify-email.html?token={token}"
    subject = "Подтверждение регистрации — WebApp CreateBots"
    body = f"""Здравствуйте!

Для завершения регистрации перейдите по ссылке:
{verify_url}

Ссылка действительна 24 часа.

Если вы не регистрировались, просто проигнорируйте это письмо.
"""
    html = f"""
    <html>
    <body style="font-family: sans-serif; max-width: 500px;">
        <p>Здравствуйте!</p>
        <p>Для завершения регистрации нажмите кнопку:</p>
        <p><a href="{verify_url}" style="display: inline-block; padding: 12px 24px; background: #3b82f6; color: white; text-decoration: none; border-radius: 8px;">Подтвердить email</a></p>
        <p>Или скопируйте ссылку в браузер:</p>
        <p style="word-break: break-all; color: #666;">{verify_url}</p>
        <p style="color: #999; font-size: 12px;">Если вы не регистрировались, проигнорируйте это письмо.</p>
    </body>
    </html>
    """
    return await _send_email(to_email, subject, body, html)


async def _send_email(to: str, subject: str, text: str, html: Optional[str] = None) -> bool:
    """Отправка email через SMTP. Если SMTP не настроен — выводит в консоль."""
    if not SMTP_USER or not SMTP_PASSWORD:
        logger.warning(
            "SMTP не настроен. Вывод ссылки в консоль:\n"
            "---\nTo: %s\nSubject: %s\n\n%s\n---",
            to, subject, text
        )
        return True

    try:
        import aiosmtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = to
        msg.attach(MIMEText(text, "plain", "utf-8"))
        if html:
            msg.attach(MIMEText(html, "html", "utf-8"))

        await aiosmtplib.send(
            msg,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER,
            password=SMTP_PASSWORD,
            start_tls=True,
            timeout=10,
        )
        return True
    except Exception as e:
        logger.exception("Ошибка отправки email: %s", e)
        logger.warning(
            "Ссылка для подтверждения (скопируйте вручную):\n---\nTo: %s\nSubject: %s\n%s\n---",
            to, subject, text
        )
        return False
