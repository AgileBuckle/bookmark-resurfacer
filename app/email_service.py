import logging

import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import Bookmark, User, utcnow
from app.security import escape_html, is_safe_url, is_valid_email, sanitize_header
from app.settings_service import get_settings

logger = logging.getLogger(__name__)

MAX_LINKS_PER_EMAIL = 50


def build_email_body(bookmarks: list[Bookmark], settings: dict) -> str:
    """
    Render the digest as HTML.

    Every interpolated value is HTML-escaped and every link target is checked
    to be http(s). Bookmark fields are attacker-controllable (via the API), so
    unescaped interpolation here would mean HTML/script injection into the
    recipient's mailbox and `javascript:` links in the message body.
    """
    subject = escape_html(
        sanitize_header(settings.get("email_subject") or "Your Bookmarks to Revisit")
    )

    lines = ["<html><body>"]
    lines.append(f"<h2>{subject}</h2>")
    lines.append("<p>Here are some bookmarks you saved — worth another look:</p>")
    lines.append("<ul>")

    for bm in bookmarks:
        title = escape_html(bm.title or bm.url)
        lines.append("<li>")
        if is_safe_url(bm.url):
            lines.append(
                f'<a href="{escape_html(bm.url)}" rel="noopener noreferrer">'
                f"<strong>{title}</strong></a>"
            )
        else:
            # Unsafe scheme: show the text, never make it clickable.
            lines.append(f"<strong>{title}</strong>")
        if bm.description:
            lines.append(f"<br/><em>{escape_html(bm.description)}</em>")
        if bm.tags:
            lines.append(f"<br/><small>Tags: {escape_html(bm.tags)}</small>")
        lines.append("</li>")

    lines.append("</ul>")
    lines.append("<p><em>— Bookmark Resurfacer</em></p>")
    lines.append("</body></html>")
    return "".join(lines)


async def send_email_for_user(db: Session, user_id: str) -> tuple[bool, str | None]:
    """
    Send one digest. Returns (sent, user-safe error message).

    Error strings are safe to show in the UI: raw exception text from the SMTP
    library can echo back server banners and credential material, so it is
    logged server-side only.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.warning("User %s not found — skipping send.", user_id)
        return False, "User not found."

    settings = get_settings(db, user_id)

    smtp_host = sanitize_header(settings["smtp_host"], 255)
    smtp_use_tls = settings["smtp_use_tls"] == "true"
    smtp_username = settings["smtp_username"]
    smtp_password = settings["smtp_password"]
    email_from = sanitize_header(settings["email_from"], 320)
    email_to = sanitize_header(settings["email_to"], 320)

    try:
        smtp_port = int(settings["smtp_port"])
    except (TypeError, ValueError):
        return False, "SMTP port is not a valid number."
    if not 1 <= smtp_port <= 65535:
        return False, "SMTP port must be between 1 and 65535."

    if not all([smtp_host, email_from, email_to]):
        return False, "SMTP host, from address, and to address are required."
    if not is_valid_email(email_from) or not is_valid_email(email_to):
        return False, "From and To must be single valid email addresses."

    try:
        links_per_email = int(settings["links_per_email"])
    except (TypeError, ValueError):
        links_per_email = 5
    links_per_email = max(1, min(links_per_email, MAX_LINKS_PER_EMAIL))

    bookmarks = (
        db.query(Bookmark)
        .filter(Bookmark.user_id == user_id)
        .order_by(func.random())
        .limit(links_per_email)
        .all()
    )
    if not bookmarks:
        return False, "No bookmarks to send."

    html_body = build_email_body(bookmarks, settings)

    msg = MIMEMultipart("alternative")
    msg["From"] = email_from
    msg["To"] = email_to
    msg["Subject"] = sanitize_header(
        settings.get("email_subject") or "Your Bookmarks to Revisit"
    )
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=smtp_host,
            port=smtp_port,
            username=smtp_username or None,
            password=smtp_password or None,
            start_tls=smtp_use_tls,
            timeout=30,
        )
    except aiosmtplib.SMTPAuthenticationError:
        logger.warning("SMTP authentication failed for user %s", user_id)
        return False, "SMTP authentication failed. Check the username and password."
    except aiosmtplib.SMTPConnectError:
        logger.warning("SMTP connection failed for user %s", user_id)
        return False, "Could not connect to the SMTP server. Check the host and port."
    except Exception as exc:
        logger.warning(
            "Email send failed for user %s: %s: %s", user_id, type(exc).__name__, exc
        )
        return False, "Failed to send email. See the server logs for details."

    logger.info(
        "Email sent for user %s with %d bookmarks.", user_id, len(bookmarks)
    )
    user.last_email_sent_at = utcnow()
    db.commit()
    return True, None
