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

# Inline queries arrive on every keystroke, and rendering one costs three files
# uploaded to the storage channel. Half a second was short enough that an
# ordinary pause between words counted as "done typing", so a sentence became a
# channel full of half-sentences. This is long enough to mean a real stop.
DEBOUNCE_SECONDS = 1.3
MAX_INLINE_CHARS = 700

# Telegram closes an inline query a few seconds after it opens it, and answering
# a closed one fails with "query is too old". Nothing here waits on the
# animation any more: it is rendered and uploaded alongside the other two, and
# it joins the answer only if it happens to be finished by the time the photo
# and the sticker are up. Otherwise it finishes into the cache, and the next
# keystroke - the same text again - is answered from there with all three.
#
# Waiting even a little for it was the difference between an answer and no
# answer on a slow link, and no answer is much worse than no animation. So the
# wait is not a fixed share of anything: it is whatever is left of this budget
# once the photo and the sticker are up. A quick link has seconds to spare and
# gets the animation; a slow one has none left and is answered without it.
# Five seconds proved safe - the query was still open - but left the
# animation about three, and it needs closer to four on a slow link. Telegram
# allows something near ten; this keeps a wide margin under that and is still
# only ever spent on the animation, never on the answer itself.
SAFE_TOTAL = 8.5
MIN_WAIT = 0.3      # below this it is not worth the round trip of trying

# The same text typed twice should not be rendered twice. Inline queries repeat
# constantly - every backspace and retype is the same string again - and a
# file_id outlives the message it came from, so it can be handed back directly.
CACHE_LIMIT = 200

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


def _abandon(context) -> None:
    """Drop the animation the previous keystroke started.

    It is halfway through ffmpeg or halfway up to the channel, and nobody will
    ever ask for it: the text it was drawing no longer exists. Left alone it
    would finish and file a picture of half a sentence in the storage channel,
    and every keystroke would leave one behind.
    """
    running = context.user_data.pop("inline_gif", None)
    if running is not None and not running.done():
        running.cancel()


def _cached(context, key: str):
    return context.bot_data.get("inline_cache", {}).get(key)


def _remember(context, key: str, ids: tuple) -> None:
    cache = context.bot_data.setdefault("inline_cache", {})
    cache[key] = ids
    # Dictionaries keep insertion order, so the front of it is the oldest.
    while len(cache) > CACHE_LIMIT:
        cache.pop(next(iter(cache)))


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
                  user_id: int, png, webp) -> tuple[str, str]:
    """Put the photo and the sticker up, and return their file_ids.

    These two are what the answer cannot go out without, so they go up together
    rather than one after the other, and the animation is not waited on here at
    all - it has a deadline of its own.

    Neither is kept: they exist to be given a file_id, which outlives the
    message that carried it. The deleting happens after this returns and costs
    the user nothing.
    """
    bot = context.bot
    target = storage_chat or user_id
    photo_msg, sticker_msg = await asyncio.gather(
        bot.send_photo(target, png, disable_notification=True),
        bot.send_sticker(target, webp, disable_notification=True),
    )
    _later(context, _discard([photo_msg, sticker_msg]))
    return photo_msg.photo[-1].file_id, sticker_msg.sticker.file_id


async def _upload_animation(context: ContextTypes.DEFAULT_TYPE,
                            storage_chat: str | int | None,
                            user_id: int, animation) -> str | None:
    """Put the animation up and hand back its file_id."""
    buf, ext = animation
    target = storage_chat or user_id
    message = await context.bot.send_animation(
        target, buf, filename=f"quote.{ext}", disable_notification=True)
    if not storage_chat:
        _later(context, _discard([message]))
    # Telegram stores every animation as MP4, whichever way it arrived, but it
    # can still come back as a plain document if it declined to convert one.
    return message.animation.file_id if message.animation else None


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


def make_handler(watermark: str, storage_chat: str | int | None, gate=None):
    """`gate` says what stands between this person and a result, or None.

    Inline mode asked for nothing at all, which made it the way round every
    rule the rest of the bot applies. The check itself lives in bot.py, since
    it is the same one the commands use, and is handed in rather than imported
    so this module still knows nothing about that one.
    """
    async def on_inline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.inline_query
        arrived = asyncio.get_running_loop().time()
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

        if gate is not None:
            refused = await gate(context, query.from_user)
            if refused:
                await query.answer(
                    [], cache_time=5, is_personal=True,
                    button=InlineQueryResultsButton(
                        text=i18n.t(refused, lang), start_parameter="inline"
                    ),
                )
                return

        # The quote is always the sender's own words, under their own name.
        text = raw[:MAX_INLINE_CHARS]
        chosen = context.bot_data.get("avatars", {}).get(query.from_user.id)
        # The picture depends on the words, who is credited and which avatar
        # stands for them, so all three go into the key.
        key = f"{query.from_user.id}:{chosen or ''}:{text}"

        # Before anything else, including the wait for typing to stop. A repeat
        # of a text already rendered costs one dictionary lookup, and the whole
        # point of the cache is that the answer beats the query being closed.
        remembered = _cached(context, key)
        if remembered:
            await _answer(query, build_results(lang, *remembered), arrived)
            log.info("inline answered from cache in %.1fs",
                     asyncio.get_running_loop().time() - arrived)
            return

        # Only the most recent keystroke should reach the renderer.
        context.user_data["inline_seq"] = query.id
        _abandon(context)
        await asyncio.sleep(DEBOUNCE_SECONDS)
        if context.user_data.get("inline_seq") != query.id:
            return

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

        clock = asyncio.get_running_loop().time
        started = clock()
        try:
            avatar = await authors.fetch_avatar(context.bot, author, chosen)
            got_avatar = clock()
            scene = await asyncio.to_thread(
                render.build_scene, avatar, text, author.name, watermark
            )
            # The animation is a couple of hundred frames through ffmpeg and
            # then an upload of its own - the longest job here by far, so it is
            # started the moment there is a scene to render, before the two
            # stills are even encoded. Nothing waits for it.
            gif = asyncio.ensure_future(_make_animation(
                context, store, query.from_user.id, scene))
            context.user_data["inline_gif"] = gif

            image = await asyncio.to_thread(scene.render)
            png = await asyncio.to_thread(render.to_png, image)
            webp = await asyncio.to_thread(render.to_sticker_webp, image)
            drawn = clock()
            try:
                photo_id, sticker_id = await _upload(
                    context, store, query.from_user.id, png, webp
                )
            except BaseException:
                gif.cancel()
                raise
            uploaded = clock()

            # Whatever is left of the budget goes to the animation, and if
            # that is nothing, the answer goes out without it.
            animation_id = None
            spare = SAFE_TOTAL - (uploaded - arrived)
            if spare >= MIN_WAIT or gif.done():
                try:
                    animation_id = await asyncio.wait_for(
                        asyncio.shield(gif), max(0.01, spare))
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass  # it carries on, or was replaced; either way, answer
                except Exception:  # noqa: BLE001 - the other two are still good
                    log.exception("inline animation failed")
            if context.user_data.get("inline_seq") != query.id:
                # Somebody kept typing while this was uploading. What is already
                # up cannot be unsent, but the animation can still be stopped.
                _abandon(context)
            else:
                _later(context, _finish(context, key,
                                        (photo_id, sticker_id), gif))
            log.info(
                "inline ready in %.1fs (avatar %.1f, draw %.1f, upload %.1f, "
                "animation %.1f)%s",
                clock() - arrived, got_avatar - started, drawn - got_avatar,
                uploaded - drawn, clock() - uploaded,
                "" if animation_id else " - without the animation",
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
            await _answer(query, [])
            return

        await _answer(query, build_results(lang, photo_id, sticker_id,
                                           animation_id), arrived)

    return on_inline


async def _make_animation(context, storage_chat, user_id, scene):
    """Render the animation and put it up, off the answer's critical path."""
    animation = await asyncio.to_thread(animate.to_animation, scene)
    return await _upload_animation(context, storage_chat, user_id, animation)


async def _finish(context, key: str, ids: tuple, gif) -> None:
    """Wait for the animation, whenever it lands, and remember all three."""
    animation_id = None
    try:
        animation_id = await gif
    except asyncio.CancelledError:
        return  # a newer keystroke replaced it; there is nothing to remember
    except Exception:  # noqa: BLE001 - nothing to answer any more either way
        log.debug("inline animation never arrived for %s", key)
    _remember(context, key, (*ids, animation_id))


async def _answer(query, results, opened: float = 0.0) -> None:
    """Answer the query, unless Telegram has already closed it.

    A query that took too long is not a fault worth a traceback: the work is
    done and cached, and the next keystroke will be answered from it.
    """
    try:
        await query.answer(results, cache_time=30, is_personal=True)
    except BadRequest as exc:
        if "too old" in str(exc).lower() or "query id is invalid" in str(exc).lower():
            log.info("inline query was closed %.1fs after it arrived, before the "
                     "answer went out", asyncio.get_running_loop().time() - opened)
            return
        raise
