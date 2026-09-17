"""Counting the reactions on a message, as they happen.

Telegram never tells a bot what reactions a message already carries. Nothing on
`reply_to_message` mentions them, and there is no way to ask. The only reactions
a bot can know about are the ones it watched arrive, so they are counted here as
the updates come in and kept alongside the rest of the bot's state.

Two kinds of update bring them, and they are not equally good:

  message_reaction        one person changed their mind: what they had before,
                          and what they have now. A running total, and only sent
                          while the bot is an administrator of the group.
  message_reaction_count  the totals themselves, for chats where reactions are
                          anonymous. Authoritative, so it replaces the count
                          rather than adjusting it.

A message the bot never saw reacted to has no reactions here, and that is not a
failure - it is the honest answer to a question Telegram will not answer.
"""
from __future__ import annotations

import logging

log = logging.getLogger("quotebot.reactions")

# Reactions are remembered per chat, and a busy group would otherwise grow this
# without end. Only the most recent messages keep theirs; a screenshot of a
# message old enough to have fallen off is a screenshot without reactions,
# which is what it would have been anyway.
MAX_MESSAGES_PER_CHAT = 400

# What fits across a bubble before it looks like a toolbar.
MAX_SHOWN = 4


def _store(bot_data: dict) -> dict:
    return bot_data.setdefault("reactions", {})


def _chat(bot_data: dict, chat_id: int) -> dict:
    return _store(bot_data).setdefault(chat_id, {})


def _trim(chat: dict) -> None:
    """Drop the oldest messages once a chat has too many.

    Dictionaries keep insertion order, so the front of it is the oldest.
    """
    while len(chat) > MAX_MESSAGES_PER_CHAT:
        chat.pop(next(iter(chat)))


def _emoji_of(reaction) -> str | None:
    """The character to draw, or None for a reaction that cannot be drawn.

    A custom emoji is a file, not a character: there is no glyph to put in a
    pill, so it is left out of the count rather than drawn as something it
    is not.
    """
    return getattr(reaction, "emoji", None)


def record_change(bot_data: dict, update) -> None:
    """Apply one person's change of reaction to the running totals."""
    event = update.message_reaction
    if event is None:
        return
    chat = _chat(bot_data, event.chat.id)
    counts = dict(chat.get(event.message_id, {}))

    before = [e for e in (_emoji_of(r) for r in event.old_reaction) if e]
    after = [e for e in (_emoji_of(r) for r in event.new_reaction) if e]
    for emoji in before:
        if emoji not in after:
            counts[emoji] = counts.get(emoji, 0) - 1
    for emoji in after:
        if emoji not in before:
            counts[emoji] = counts.get(emoji, 0) + 1

    # A count can only reach zero by everyone taking it back, and a zero is not
    # worth a pill or the memory to hold it.
    counts = {e: n for e, n in counts.items() if n > 0}
    if counts:
        chat[event.message_id] = counts
    else:
        chat.pop(event.message_id, None)
    _trim(chat)
    log.debug("reactions on %s/%s: %s", event.chat.id, event.message_id, counts)


def record_totals(bot_data: dict, update) -> None:
    """Take the totals Telegram sends for chats where reactions are anonymous."""
    event = update.message_reaction_count
    if event is None:
        return
    counts = {}
    for entry in event.reactions:
        emoji = _emoji_of(entry.type)
        if emoji and entry.total_count > 0:
            counts[emoji] = entry.total_count
    chat = _chat(bot_data, event.chat.id)
    if counts:
        chat[event.message_id] = counts
    else:
        chat.pop(event.message_id, None)
    _trim(chat)


def for_message(bot_data: dict, chat_id: int, message_id: int) -> list[tuple[str, int]]:
    """What to draw under this message: (emoji, count), most reacted first."""
    counts = _store(bot_data).get(chat_id, {}).get(message_id, {})
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ordered[:MAX_SHOWN]


def total_tracked(bot_data: dict) -> int:
    """How many messages have reactions on record. For the admin panel."""
    return sum(len(chat) for chat in _store(bot_data).values())
