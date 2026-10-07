import json
import os
import urllib.error
import urllib.request

# Importing football_api loads .env and provides the OS trust store SSL context
from football_api import SSL_CONTEXT

BASE_URL = "https://api.telegram.org"


def _channel_id():
    """TELEGRAM_CHANNEL_ID as the Bot API expects it: "@username" or a numeric "-100..." id."""
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()
    if not channel_id:
        raise RuntimeError("Set the TELEGRAM_CHANNEL_ID environment variable")
    if channel_id.startswith(("@", "-")) or channel_id.isdigit():
        return channel_id
    return f"@{channel_id}"


def send_message(text):
    """Post a text message to the channel; returns the sent message."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Set the TELEGRAM_BOT_TOKEN environment variable")

    body = json.dumps({"chat_id": _channel_id(), "text": text}).encode()
    request = urllib.request.Request(
        f"{BASE_URL}/bot{token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, context=SSL_CONTEXT) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        # The Bot API explains failures (bad token, bot not admin, ...) in the response body
        data = json.load(error)
    if not data.get("ok"):
        raise RuntimeError(f"Telegram error: {data.get('description')}")
    return data["result"]
