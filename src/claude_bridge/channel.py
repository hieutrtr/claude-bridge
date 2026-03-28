"""Channel abstraction layer for multi-channel support."""

from __future__ import annotations

import re

CHANNELS = {"cli", "telegram", "discord", "slack"}


def format_message(channel: str, text: str) -> str:
    """Format a message for a specific channel."""
    if not text:
        return text
    match channel:
        case "telegram":
            return _format_telegram(text)
        case "slack":
            return _format_slack(text)
        case "discord":
            return text  # Discord uses standard markdown, no conversion needed
        case _:
            return text  # CLI and unknown: plain text


def _format_telegram(text: str) -> str:
    """Escape special chars for Telegram MarkdownV2."""
    # MarkdownV2 requires escaping: _ * [ ] ( ) ~ ` > # + - = | { } . !
    special = r"_*[]()~`>#+-=|{}.!"
    result = []
    for ch in text:
        if ch in special:
            result.append(f"\\{ch}")
        else:
            result.append(ch)
    return "".join(result)


def _format_slack(text: str) -> str:
    """Convert standard markdown to Slack mrkdwn."""
    # **bold** → *bold*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    # __italic__ → _italic_ (already same)
    # ~~strike~~ → ~strike~
    text = re.sub(r"~~(.+?)~~", r"~\1~", text)
    return text


def parse_channel_context(
    channel: str,
    chat_id: str | None,
    message_id: str | None = None,
) -> dict:
    """Parse channel info into a dict suitable for task storage."""
    return {
        "channel": channel,
        "channel_chat_id": chat_id,
        "channel_message_id": message_id,
    }
