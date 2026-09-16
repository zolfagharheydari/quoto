"""Pull the quotable text out of a replied-to message."""
from __future__ import annotations

from telegram import Message

import textkit

MAX_QUOTE_CHARS = 700


def quote_text(message: Message) -> str | None:
    """The text to put on the card, or None when there is nothing to quote."""
    raw = message.text or message.caption
    if not raw:
        return None
    # Only the first MAX_QUOTE_CHARS are ever looked at. A Telegram message runs
    # to 4096 characters and the tail of a long one cannot reach the card under
    # any font size, so reshaping and folding it would be work done to throw the
    # result away. The cut comes first, and nothing past it is touched.
    head = raw[:MAX_QUOTE_CHARS]
    # Emoji are dropped before rendering, so a message made only of them has
    # nothing left to put on a card.
    text = textkit.normalize_display(head)
    if not text:
        return None
    if len(raw) > MAX_QUOTE_CHARS:
        text = text.rstrip() + "…"
    return text
