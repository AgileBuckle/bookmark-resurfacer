import random
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import aiosmtplib
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import Bookmark
from app.settings_service import get_settings


def build_email_body(bookmarks: list[Bookmark], settings: dict) -> str:
    subject = settings.get("email_subject", "Your Bookmarks to Revisit")

    lines = ["<html><body>"]
    lines.append(f"<h2>{subject}</h2>")
    lines.append("<p>Here are some bookmarks you saved — worth another look:</p>")
    lines.append("<ul>")

    for bm in bookmarks:
        title = bm.title or bm.url
        lines.append(
            f'<li><a href="{bm.url}"><strong>{title}</strong></a>'
        )
        if bm.description:
            lines.append(f"<br/><em>{bm.description}</em>")
        if bm.tags:
            lines.append(f"<br/><small>Tags: {bm.tags}</small>")
        lines.append("</li>")

    lines.append("</ul>")
    lines.append("<p><em>— Bookmark Resurfacer</em></p>")
    lines.append("</body></html>")
    return "".join(lines)


async def send_email(db: Session) -> bool:
    settings = get_settings(db)

    smtp_host = settings["smtp_host"]
    smtp_port = int(settings["smtp_port"])
    smtp_use_tls = settings["smtp_use_tls"] == "true"
    smtp_username = settings["smtp_username"]
    smtp_password = settings["smtp_password"]
    email_from = settings["email_from"]
    email_to = settings["email_to"]

    if not all([smtp_host, email_from, email_to]):
        print("Email settings incomplete — skipping send.")
        return False

    links_per_email = int(settings["links_per_email"])

    bookmarks = db.query(Bookmark).order_by(func.random()).limit(links_per_email).all()
    if not bookmarks:
        print("No bookmarks to send.")
        return False

    html_body = build_email_body(bookmarks, settings)

    msg = MIMEMultipart("alternative")
    msg["From"] = email_from
    msg["To"] = email_to
    msg["Subject"] = settings.get("email_subject", "Your Bookmarks to Revisit")
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=smtp_host,
            port=smtp_port,
            username=smtp_username or None,
            password=smtp_password or None,
            start_tls=smtp_use_tls,
        )
        print(f"Email sent to {email_to} with {len(bookmarks)} bookmarks.")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False