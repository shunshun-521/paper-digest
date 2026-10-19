"""SMTP mail with CID-embedded figures."""

from __future__ import annotations

import smtplib
from email.message import Message
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from digest.figures import shrink_for_email
from digest.models import Paper

MAX_MESSAGE_BYTES = 8 * 1024 * 1024


def subject_for(day_label: str, headline: str) -> str:
    return f"📄 论文日报 {day_label} · {headline}"


def build_message(
    *,
    sender: str,
    recipients: list[str],
    subject: str,
    html: str,
    plain: str,
    papers: list[Paper],
) -> MIMEMultipart:
    related = MIMEMultipart("related")
    related["Subject"] = subject
    related["From"] = sender
    related["To"] = ", ".join(recipients)

    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(plain, "plain", "utf-8"))
    alternative.attach(MIMEText(html, "html", "utf-8"))
    related.attach(alternative)

    for paper in papers:
        if not paper.figure or not paper.figure.data or not paper.figure.cid:
            continue
        subtype = "jpeg" if "jpeg" in paper.figure.media_type or "jpg" in paper.figure.media_type else "png"
        image = MIMEImage(paper.figure.data, _subtype=subtype)
        image.add_header("Content-ID", f"<{paper.figure.cid}>")
        image.add_header(
            "Content-Disposition",
            "inline",
            filename=paper.figure.filename or f"{paper.figure.cid}.jpg",
        )
        related.attach(image)
    return related


def message_bytes(message: Message) -> bytes:
    return message.as_bytes()


def shrink_figures_if_needed(
    message: Message,
    papers: list[Paper],
    html: str,
    plain: str,
    sender: str,
    recipients: list[str],
    subject: str,
) -> MIMEMultipart:
    if len(message_bytes(message)) <= MAX_MESSAGE_BYTES:
        return message
    for paper in papers:
        if paper.figure and paper.figure.data:
            data, media = shrink_for_email(paper.figure.data)
            paper.figure.data = data
            paper.figure.media_type = media
    return build_message(
        sender=sender,
        recipients=recipients,
        subject=subject,
        html=html,
        plain=plain,
        papers=papers,
    )


def send_email(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    recipients: list[str],
    message: Message,
) -> None:
    if port == 465:
        smtp: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=60)
    else:
        smtp = smtplib.SMTP(host, port, timeout=60)
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
    try:
        smtp.login(user, password)
        smtp.sendmail(user, recipients, message.as_bytes())
    finally:
        smtp.quit()
