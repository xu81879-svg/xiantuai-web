from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import quote


class EmailDeliveryError(RuntimeError):
    pass


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def verification_url(token: str) -> str:
    public_url = _env("PUBLIC_APP_URL", "http://localhost:5173").rstrip("/")
    return f"{public_url}/api/auth/verify-email?token={quote(token, safe='')}"


def smtp_configured() -> bool:
    configured = bool(_env("SMTP_HOST") and _env("SMTP_FROM"))
    if _env("ENVIRONMENT", "development").lower() == "production":
        return (
            configured
            and _env("PUBLIC_APP_URL").startswith("https://")
            and _env("SMTP_STARTTLS", "true").lower() == "true"
        )
    return configured


def send_verification_email(recipient: str, token: str) -> str | None:
    """Send a one-time verification link; return a debug link only outside production."""
    host = _env("SMTP_HOST")
    sender = _env("SMTP_FROM")
    if not smtp_configured():
        if _env("ENVIRONMENT", "development").lower() == "production":
            raise EmailDeliveryError("邮箱验证服务尚未配置")
        return verification_url(token)

    try:
        port = int(_env("SMTP_PORT", "587"))
        timeout = max(3.0, float(_env("SMTP_TIMEOUT_SECONDS", "10")))
    except ValueError as exc:
        raise EmailDeliveryError("SMTP 配置无效") from exc

    url = verification_url(token)
    message = EmailMessage()
    message["Subject"] = "验证你的鲜图 AI 邮箱"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        "你好，\n\n请在 30 分钟内打开以下链接验证邮箱：\n"
        f"{url}\n\n如果你没有注册鲜图 AI，请忽略这封邮件。"
    )

    try:
        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            if _env("SMTP_STARTTLS", "true").lower() == "true":
                smtp.starttls(context=ssl.create_default_context())
            username = _env("SMTP_USERNAME")
            password = os.getenv("SMTP_PASSWORD", "")
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailDeliveryError("验证邮件发送失败，请稍后重试") from exc
    return None
