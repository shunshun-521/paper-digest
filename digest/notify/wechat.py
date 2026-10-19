"""Server酱 and PushPlus reminders. Missing tokens skip the channel."""

from __future__ import annotations

import logging

import httpx

from digest.config import env

logger = logging.getLogger(__name__)


def send_wechat(provider: str, title: str, content: str) -> str:
    """Send a short reminder. Returns ``sent`` or ``skipped``."""
    title = title[:80]
    if provider == "pushplus":
        token = env("PUSHPLUS_TOKEN")
        if not token:
            logger.warning("PUSHPLUS_TOKEN missing, skip wechat")
            return "skipped"
        response = httpx.post(
            "http://www.pushplus.plus/send",
            json={"token": token, "title": title, "content": content, "template": "markdown"},
            timeout=30.0,
        )
        response.raise_for_status()
        return "sent"
    sendkey = env("SERVERCHAN_SENDKEY")
    if not sendkey:
        logger.warning("SERVERCHAN_SENDKEY missing, skip wechat")
        return "skipped"
    response = httpx.post(
        f"https://sctapi.ftqq.com/{sendkey}.send",
        data={"title": title, "desp": content},
        timeout=30.0,
    )
    response.raise_for_status()
    return "sent"


def failure_notice(provider: str) -> str:
    try:
        return send_wechat(provider, "论文日报失败", "今日推送失败，请查看 Actions 日志")
    except Exception as exc:  # noqa: BLE001
        logger.warning("failure wechat was not sent: %s", exc)
        return "error"
