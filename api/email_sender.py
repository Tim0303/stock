"""email_sender.py — 可插拔寄信（dev=console / prod=smtp）。

dev：把連結印到 stdout（docker logs stock-api 可見），零設定。
prod：stdlib smtplib（SendGrid/SES 走 SMTP relay→純設定切換，無第三方 SDK）。
"""
from __future__ import annotations

import os
import smtplib
import ssl
import sys
from email.message import EmailMessage

EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "console").lower()
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "no-reply@localhost")
SMTP_TLS = os.environ.get("SMTP_TLS", "true").lower() == "true"


def send_email(to: str, subject: str, text: str) -> None:
    if EMAIL_BACKEND == "console":
        print(
            f"\n===== [EMAIL → {to}] {subject} =====\n{text}\n"
            f"===== [/EMAIL] =====\n",
            file=sys.stderr,
            flush=True,
        )
        return

    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if SMTP_TLS:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
            s.starttls(context=ctx)
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
