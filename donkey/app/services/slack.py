"""Slack Webhook 알림. SLACK_WEBHOOK_URL 설정 시에만 발송."""

import logging

import httpx

logger = logging.getLogger(__name__)


def notify_slack(webhook_url: str, text: str, blocks: list | None = None) -> None:
    """
    Slack Incoming Webhook으로 메시지 전송.
    webhook_url이 비어있으면 무시. 실패 시 로그만 남기고 예외 전파하지 않음.
    """
    if not webhook_url or not webhook_url.strip():
        return
    payload: dict = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    try:
        resp = httpx.post(webhook_url, json=payload, timeout=10.0)
        if resp.status_code != 200:
            logger.warning("Slack webhook failed: status=%s body=%s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.warning("Slack webhook error: %s", e)
