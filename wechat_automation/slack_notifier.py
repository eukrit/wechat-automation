"""
slack_notifier.py — Slack notification client for wechat-automation.

Gets bot token from SLACK_BOT_TOKEN env var or Secret Manager (slack-bot-token).
"""

from __future__ import annotations

import logging
import os

from google.cloud import secretmanager
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)

GCP_PROJECT = os.environ.get("GCP_PROJECT", os.environ.get("GCP_PROJECT_ID", "ai-agents-go"))
SOURCE_TAG = "WeChat"

_slack_client = None


def _get_slack_token() -> str:
    """Get Slack bot token from env var or Secret Manager."""
    token = os.environ.get("SLACK_BOT_TOKEN")
    if token:
        return token
    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{GCP_PROJECT}/secrets/slack-bot-token/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("utf-8").strip()
    except Exception as e:
        logger.error("Failed to get Slack token: %s", e)
        raise


def get_slack_client() -> WebClient:
    """Get or create a Slack WebClient."""
    global _slack_client
    if _slack_client is None:
        _slack_client = WebClient(token=_get_slack_token())
    return _slack_client


def post_message(
    text: str,
    channel: str,
    blocks: list[dict] | None = None,
) -> dict | None:
    """Post a message to Slack. Returns response or None on error."""
    try:
        response = get_slack_client().chat_postMessage(
            channel=channel,
            text=f"[{SOURCE_TAG}] {text}",
            blocks=blocks,
        )
        return response.data
    except SlackApiError as e:
        logger.error("Slack error: %s", e.response["error"])
        return None
    except Exception as e:
        logger.error("Slack send failed: %s", e)
        return None
