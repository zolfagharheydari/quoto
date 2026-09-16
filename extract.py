"""Pull the quotable text out of a replied-to message."""
from __future__ import annotations

from telegram import Message

import textkit

MAX_QUOTE_CHARS = 700


def quote_text(message: Message) -> str | None:
    """The text to put on the card, or None when there is nothing to quote."""
    text = message.text or message.caption
    # Emoji are dropped before rendering, so a message made only of them has
    # nothing left to put on a card.
    text = textkit.normalize_display(text) if text else ""
    if not text:
        return None
    if len(text) > MAX_QUOTE_CHARS:
        text = text[:MAX_QUOTE_CHARS].rstrip() + "…"
    return text
