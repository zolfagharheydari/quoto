"""Inline mode: `@bot some text` builds a quote card in any chat, member or not.

Telegram never tells an inline query what message the user is replying to, so
the text has to be typed or pasted, and the card is always credited to whoever
typed it. In exchange the bot works in groups it was never added to.

Inline results can only reference files Telegram already stores, so each card is
uploaded once to a storage chat to obtain a file_id, then handed back as a
cached result. STORAGE_CHAT_ID is the tidy way to do that; without it we bounce
the upload through the user's own chat with the bot and delete it immediately.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid

from telegram import (
    InlineQueryResultCachedPhoto,
    InlineQueryResultCachedSticker,
    InlineQueryResultsButton,
    Update,
)
from telegram.error import Forbidden, TelegramError
from telegram.ext import ContextTypes

import authors
import i18n
import render

log = logging.getLogger("quotebot.inline")

# Inline queries arrive on every keystroke; wait for a pause before rendering.
DEBOUNCE_SECONDS = 0.45
MAX_INLINE_CHARS = 700

# Inline mode has no commands, but people reach for them anyway. A leading /quote
# is dropped, and a query that is nothing but a command gets a hint instead of a
# card reading "/quote".
_VERBS = (
    "quote|sticker|gif|screenshot"
    # the same misspellings the command handlers accept
    "|qoute|quto|qute|quot|quoet|stiker|stickr|sticekr|stcker|gfi"
    "|screenshoot|screanshot|screnshot|sceenshot"
)
LEADING_COMMAND_RE = re.compile(f"^/({_VERBS})(@[A-Za-z0-9_]+)?[ ]+", re.IGNORECASE)
COMMAND_ONLY_RE = re.compile(
    f"^/?({_VERBS}|کوت|نقل[ ]*قول)(@[A-Za-z0-9_]+)?$", re.IGNORECASE
)


async def _upload(context: ContextTypes.DEFAULT_TYPE, storage_chat: str | int | None,
                  user_id: int, png, webp) -> tuple[str, str]:
    """Send the card somewhere Telegram will keep it, and return its file_ids."""
    bot = context.bot
    target = storage_chat or user_id
    photo_msg = await bot.send_photo(target, png, disable_notification=True)
    sticker_msg = await bot.send_sticker(target, webp, disable_notification=True)
    if not storage_chat:
        # Nothing configured, so the user's own chat was the scratch space: clean it up.
        for msg in (photo_msg, sticker_msg):
            try:
                await msg.delete()
            except TelegramError:
                log.debug("could not delete scratch message %s", msg.message_id)
    return photo_msg.photo[-1].file_id, sticker_msg.sticker.file_id


def make_handler(watermark: str, storage_chat: str | int | None):
    async def on_inline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.inline_query
        lang = i18n.resolve(update, context.user_data)
        raw = query.query.strip()

        raw = LEADING_COMMAND_RE.sub("", raw).strip()
        if not raw or COMMAND_ONLY_RE.match(raw):
            # Empty query, or someone typing "@bot /quote" expecting the reply flow.
            hint = "inline_command" if raw else "inline_empty"
            await query.answer(
                [], cache_time=5, is_personal=True,
                button=InlineQueryResultsButton(
                    text=i18n.t(hint, lang), start_parameter="inline"
                ),
            )
            return

        # Only the most recent keystroke should reach the renderer.
        context.user_data["inline_seq"] = query.id
        await asyncio.sleep(DEBOUNCE_SECONDS)
        if context.user_data.get("inline_seq") != query.id:
            return

        # The quote is always the sender's own words, under their own name.
        text = raw[:MAX_INLINE_CHARS]
        author = authors.Author(
            name=" ".join(
                filter(None, [query.from_user.first_name, query.from_user.last_name])
            ),
            handle=query.from_user.username or "",
            avatar_key=query.from_user.id,
            kind="user",
            seed=str(query.from_user.id),
        )

        try:
            avatar = await authors.fetch_avatar(context.bot, author)
            scene = await asyncio.to_thread(
                render.build_scene, avatar, text, author.name, watermark
            )
            image = await asyncio.to_thread(scene.render)
            png = await asyncio.to_thread(render.to_png, image)
            webp = await asyncio.to_thread(render.to_sticker_webp, image)
            photo_id, sticker_id = await _upload(
                context, storage_chat, query.from_user.id, png, webp
            )
        except Forbidden:
            # The user never pressed Start, so the bot cannot use their chat as storage.
            await query.answer(
                [], cache_time=5, is_personal=True,
                button=InlineQueryResultsButton(
                    text=i18n.t("inline_need_start", lang), start_parameter="inline"
                ),
            )
            return
        except Exception:  # noqa: BLE001 - one bad query must not kill the handler
            log.exception("inline render failed")
            await query.answer([], cache_time=1, is_personal=True)
            return

        await query.answer(
            [
                InlineQueryResultCachedPhoto(
                    id=str(uuid.uuid4()), photo_file_id=photo_id,
                    title=i18n.t("inline_photo", lang),
                ),
                InlineQueryResultCachedSticker(
                    id=str(uuid.uuid4()), sticker_file_id=sticker_id,
                ),
            ],
            cache_time=30,
            is_personal=True,
        )

    return on_inline
