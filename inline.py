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
    InlineQueryResultCachedMpeg4Gif,
    InlineQueryResultCachedPhoto,
    InlineQueryResultCachedSticker,
    InlineQueryResultsButton,
    Update,
)
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ContextTypes

import animate
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


async def _discard(messages) -> None:
    """Delete the uploads we do not want to keep.

    A file_id outlives the message that carried it - the file stays on
    Telegram's servers - so the results handed back still work. This runs after
    the query has been answered, off the path the user waits on.
    """
    for msg in messages:
        try:
            await msg.delete()
        except TelegramError:
            log.debug("could not delete upload %s", msg.message_id)


def _later(context: ContextTypes.DEFAULT_TYPE, coro) -> None:
    """Run something without making the caller wait for it."""
    app = getattr(context, "application", None)
    if app is not None:
        # Application tracks it, so a shutdown waits for it instead of cancelling.
        app.create_task(coro)
    else:
        asyncio.get_running_loop().create_task(coro)


async def _upload(context: ContextTypes.DEFAULT_TYPE, storage_chat: str | int | None,
                  user_id: int, png, webp, animation) -> tuple[str, str, str | None]:
    """Send the card somewhere Telegram will keep it, and return its file_ids.

    The three go up together. They are independent uploads over the same
    connection pool, and doing them one after another would add the animation's
    whole round trip to how long the user waits with their keyboard open.

    What is left behind afterwards differs. With a storage channel the animation
    stays, because it is the one worth having a record of, and the photo and the
    sticker are cleared away. With no channel configured the user's own chat was
    the scratch space, so all three go. Either way the deleting happens after
    this returns and costs the user nothing.
    """
    bot = context.bot
    target = storage_chat or user_id
    buf, ext = animation
    photo_msg, sticker_msg, anim_msg = await asyncio.gather(
        bot.send_photo(target, png, disable_notification=True),
        bot.send_sticker(target, webp, disable_notification=True),
        bot.send_animation(target, buf, filename=f"quote.{ext}",
                           disable_notification=True),
    )
    throwaway = [photo_msg, sticker_msg]
    if not storage_chat:
        throwaway.append(anim_msg)
    _later(context, _discard(throwaway))
    # Telegram stores every animation as MP4, whichever way it arrived, but it
    # can still come back as a plain document if it declined to convert one.
    animation_id = anim_msg.animation.file_id if anim_msg.animation else None
    return photo_msg.photo[-1].file_id, sticker_msg.sticker.file_id, animation_id


def build_results(lang: str, photo_id: str, sticker_id: str,
                  animation_id: str | None) -> list:
    """What the user sees in the inline list, in the order they see it.

    The photo first because it is what most people are after, then the sticker,
    then the animation - which is absent rather than broken when Telegram would
    not store it as one.
    """
    results = [
        InlineQueryResultCachedPhoto(
            id=str(uuid.uuid4()), photo_file_id=photo_id,
            title=i18n.t("inline_photo", lang),
        ),
        InlineQueryResultCachedSticker(
            id=str(uuid.uuid4()), sticker_file_id=sticker_id,
        ),
    ]
    if animation_id:
        results.append(InlineQueryResultCachedMpeg4Gif(
            id=str(uuid.uuid4()), mpeg4_file_id=animation_id,
            title=i18n.t("inline_gif", lang),
        ))
    return results


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

        # A channel the owner handed the bot wins over the one in .env: it was
        # chosen later, and it is the one they can see.
        store = context.bot_data.get("storage_chat") or storage_chat

        chosen = context.bot_data.get("avatars", {}).get(query.from_user.id)
        try:
            avatar = await authors.fetch_avatar(context.bot, author, chosen)
            scene = await asyncio.to_thread(
                render.build_scene, avatar, text, author.name, watermark
            )
            image = await asyncio.to_thread(scene.render)
            png = await asyncio.to_thread(render.to_png, image)
            webp = await asyncio.to_thread(render.to_sticker_webp, image)
            # The long pole: a couple of hundred frames through ffmpeg. It is
            # still worth doing here rather than on demand, because an inline
            # result can only point at a file Telegram already holds.
            animation = await asyncio.to_thread(animate.to_animation, scene)
            photo_id, sticker_id, animation_id = await _upload(
                context, store, query.from_user.id, png, webp, animation
            )
        except (Forbidden, BadRequest) as exc:
            # The user never pressed Start, so the bot cannot use their chat as
            # storage. Telegram says this two different ways: Forbidden once it
            # knows the user, and "chat not found" when it has never seen them
            # at all. Anything else that is merely a BadRequest is a real fault
            # and belongs in the log below.
            if isinstance(exc, BadRequest) and "chat not found" not in str(exc).lower():
                log.exception("inline upload failed")
                await query.answer([], cache_time=1, is_personal=True)
                return
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
            build_results(lang, photo_id, sticker_id, animation_id),
            cache_time=30, is_personal=True,
        )

    return on_inline
