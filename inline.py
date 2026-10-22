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
import time
import uuid

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
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
import fire
import gallery
import i18n
import render
import throttle

log = logging.getLogger("quotebot.inline")

# Inline queries arrive on every keystroke, and rendering one costs three files
# uploaded to the storage channel. Half a second was short enough that an
# ordinary pause between words counted as "done typing", so a sentence became a
# channel full of half-sentences. This is long enough to mean a real stop.
DEBOUNCE_SECONDS = 1.3
MAX_INLINE_CHARS = 700

# The debounce only stops one keystroke from being rendered twice; it does not
# stop someone typing a new sentence every second and a half, each one a card,
# a sticker and an ffmpeg run. Between two renders for the same person there
# must be at least this long. A repeat of something already drawn is answered
# from the cache and does not count.
INLINE_COOLDOWN = 4.0

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


# The gif each person currently has in flight. Deliberately NOT in user_data:
# that dictionary is pickled to disk, an asyncio task cannot be pickled, and
# the persistence loop died the first time it tried - silently, taking every
# later save with it. This is process state anyway; it has no meaning after a
# restart, which is exactly when a persisted copy would be read back.
_running: dict[int, asyncio.Task] = {}


def _remember_task(user_id: int, task: asyncio.Task) -> None:
    _running[user_id] = task
    # Let go of it the moment it finishes, so this does not become a list of
    # every person who has ever used inline mode.
    task.add_done_callback(
        lambda done, uid=user_id: _running.pop(uid, None)
        if _running.get(uid) is done else None)


def _abandon(user_id: int) -> None:
    """Drop the animation the previous keystroke started.

    It is halfway through ffmpeg or halfway up to the channel, and nobody will
    ever ask for it: the text it was drawing no longer exists. Left alone it
    would finish and file a picture of half a sentence in the storage channel,
    and every keystroke would leave one behind.
    """
    running = _running.pop(user_id, None)
    if running is not None and not running.done():
        running.cancel()


def cache_key(user_id: int, avatar: str | None, template: str, text: str) -> str:
    """What makes two inline queries the same picture.

    The words, who is credited, which avatar stands for them and which card they
    picked. Leaving the template out would answer a switched template with the
    picture drawn before the switch.
    """
    return f"{user_id}:{avatar or ''}:{template}:{text}"


# The cache key holds the words someone typed. They are kept only as long as
# they are useful for answering a retype, not for as long as the bot runs.
CACHE_TTL = 24 * 60 * 60


def _cached(context, key: str):
    hit = context.bot_data.get("inline_cache", {}).get(key)
    # Entries from before they carried a time are treated as gone.
    if isinstance(hit, dict) and 0 <= time.time() - hit.get("at", 0) < CACHE_TTL:
        return hit["ids"]
    return None


def _remember(context, key: str, ids: tuple) -> None:
    cache = context.bot_data.setdefault("inline_cache", {})
    now = time.time()
    for stale in [k for k, v in cache.items()
                  if not isinstance(v, dict) or not 0 <= now - v.get("at", 0) < CACHE_TTL]:
        del cache[stale]
    cache[key] = {"ids": ids, "at": now}
    # Dictionaries keep insertion order, so the front of it is the oldest.
    while len(cache) > CACHE_LIMIT:
        cache.pop(next(iter(cache)))


def forget_user(bot_data: dict, user_id: int) -> None:
    """Drop everything this person typed in inline mode."""
    for name in ("inline_cache", "fire_inline"):
        cache = bot_data.get(name) or {}
        for key in [k for k in cache if k.startswith(f"{user_id}:")]:
            del cache[key]


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
    # Not kept, in the storage channel or anywhere: the file_id outlives the
    # message, and a channel of every half-typed sentence's GIF is clutter.
    _later(context, _discard([message]))
    # Telegram stores every animation as MP4, whichever way it arrived, but it
    # can still come back as a plain document if it declined to convert one.
    return message.animation.file_id if message.animation else None


# What was offered, so that what gets sent can be recognised later. Telegram
# reports a chosen result by its id and nothing else, so the id has to have been
# written down beside the sticker it stands for.
OFFERED_LIMIT = 40


def remember_offer(context, results, sticker_id: str) -> None:
    """Note which sticker each offered result stands for, and which one is a GIF."""
    offered = context.user_data.setdefault("inline_offered", {})
    gifs = context.user_data.setdefault("inline_offered_gif", {})
    for result in results:
        offered[result.id] = sticker_id
        if isinstance(result, InlineQueryResultCachedMpeg4Gif):
            gifs[result.id] = result.mpeg4_file_id
    for store in (offered, gifs):
        while len(store) > OFFERED_LIMIT:
            store.pop(next(iter(store)))


def sticker_for(context, result_id: str) -> str | None:
    return context.user_data.get("inline_offered", {}).get(result_id)


def gif_for(context, result_id: str) -> str | None:
    """The GIF this offered result was, if it was the GIF."""
    return context.user_data.get("inline_offered_gif", {}).get(result_id)


# A query that starts with this searches the person's own GIFs instead of
# making a new quote: "#ali" finds every GIF they have made of Ali.
GALLERY_PREFIX = "#"


async def answer_gallery(query, context, term: str, lang: str,
                         hint: str | None = None) -> None:
    """Answer with this person's own GIFs whose subject matches `term`.

    Results are ids into the archive, never the archive itself, and are sent by
    Telegram's file_id, so nothing is rendered or uploaded. Their ids start with
    "g", which no quote result uses, so picking one is never mistaken for
    sending a new quote and filed a second time.
    """
    found = gallery.search(context.user_data, term)
    try:
        start = max(0, int(query.offset or 0))
    except ValueError:
        start = 0
    page = found[start:start + gallery.PAGE]
    results = [
        InlineQueryResultCachedMpeg4Gif(
            id=f"g{start + i}", mpeg4_file_id=g["f"],
            title=g.get("n") or "GIF",
        )
        for i, g in enumerate(page)
    ]
    more = start + gallery.PAGE < len(found)

    button = None
    if not found:
        shown = term.strip()[:20]
        text = (i18n.t("gallery_none", lang).format(term=shown) if shown
                else i18n.t(hint or "inline_empty", lang))
        button = InlineQueryResultsButton(text=text, start_parameter="mygifs")
    elif hint:
        button = InlineQueryResultsButton(text=i18n.t(hint, lang),
                                          start_parameter="inline")
    await query.answer(results, cache_time=5, is_personal=True,
                       next_offset=str(start + gallery.PAGE) if more else "",
                       button=button)


# ------------------------------------------------------------------ fire
# "@bot 🔥 text" or "@bot /fire text": the text written in fire. A render takes
# about twelve seconds and an inline answer has a few, so what is offered is a
# placeholder clip with a button on it. Choosing it sends the placeholder; the
# button is what makes Telegram hand back the sent message's id, and bot.py
# renders and swaps the finished clip into that message in place.
FIRE_PREFIX_RE = re.compile(r"^(?:(?:\U0001F525️?)+|/fire(?:@[A-Za-z0-9_]+)?)(?:\s+|$)",
                            re.IGNORECASE)
FIRE_RESULT = "fire:"            # result ids of placeholders start with this
FIRE_CACHE_LIMIT = 100


def fire_text(query_text: str) -> str | None:
    """What to write in fire, if this query asks for it; None if it does not."""
    raw = (query_text or "").strip()
    match = FIRE_PREFIX_RE.match(raw)
    return None if match is None else raw[match.end():].strip()


def fire_key(user_id: int, text: str) -> str:
    return f"{user_id}:{fire.clean(text)}"


def fire_cached(bot_data: dict, key: str) -> str | None:
    hit = (bot_data.get("fire_inline") or {}).get(key)
    if isinstance(hit, dict) and 0 <= time.time() - hit.get("at", 0) < CACHE_TTL:
        return hit["id"]
    return None


def fire_remember(bot_data: dict, key: str, file_id: str) -> None:
    cache = bot_data.setdefault("fire_inline", {})
    now = time.time()
    for stale in [k for k, v in cache.items() if not 0 <= now - v.get("at", 0) < CACHE_TTL]:
        del cache[stale]
    cache[key] = {"id": file_id, "at": now}
    while len(cache) > FIRE_CACHE_LIMIT:
        cache.pop(next(iter(cache)))


def fire_again_markup(lang: str, bot_username: str) -> InlineKeyboardMarkup:
    """Under a finished clip: the way to the bot, for whoever wants one too.

    A link rather than a switch into inline mode: inline is switched off, and
    a guest message is answered in a chat the reader may have nothing to do
    with - the bot itself is where they can make their own.
    """
    return InlineKeyboardMarkup([[InlineKeyboardButton(
        i18n.t("btn_fire_again", lang), url=f"https://t.me/{bot_username}?start=fire")]])


async def _fire_placeholder(context, store, user_id: int) -> str:
    """The waiting clip's file_id, uploaded once and kept until the clip changes."""
    stat = fire.BASE.stat()
    stamp = f"{stat.st_size}:{int(stat.st_mtime)}"
    kept = context.bot_data.get("fire_placeholder") or {}
    if kept.get("stamp") == stamp and kept.get("id"):
        return kept["id"]
    data = await asyncio.to_thread(fire.placeholder)
    message = await context.bot.send_animation(
        store or user_id, data, filename="fire.mp4", disable_notification=True)
    if not store:
        _later(context, _discard([message]))
    file_id = (message.animation or message.document).file_id
    context.bot_data["fire_placeholder"] = {"id": file_id, "stamp": stamp}
    return file_id


async def answer_fire(query, context, text: str, lang: str, store) -> None:
    """Offer the text in fire: finished if it was made before, else the placeholder."""
    def refuse(key: str, **fields):
        return query.answer([], cache_time=1, is_personal=True,
                            button=InlineQueryResultsButton(
                                text=i18n.t(key, lang).format(**fields),
                                start_parameter="inline"))

    if not fire.available():
        await refuse("fire_unavailable")
        return
    quote = fire.clean(text)
    if not quote:
        await refuse("inline_fire_hint")
        return
    if len(quote) > fire.MAX_CHARS:
        await refuse("inline_fire_long", max=fire.MAX_CHARS)
        return

    user_id = query.from_user.id
    done = fire_cached(context.bot_data, fire_key(user_id, quote))
    if done:
        result = InlineQueryResultCachedMpeg4Gif(
            id=f"fd{uuid.uuid4().hex[:16]}", mpeg4_file_id=done,
            title=i18n.t("inline_fire_title", lang),
            reply_markup=fire_again_markup(lang, context.bot.username))
        # Filed in their archive when sent, like any other inline GIF.
        gifs = context.user_data.setdefault("inline_offered_gif", {})
        gifs[result.id] = done
        while len(gifs) > OFFERED_LIMIT:
            gifs.pop(next(iter(gifs)))
        await query.answer([result], cache_time=5, is_personal=True)
        return

    if throttle.FIRE.full:
        await refuse("inline_fire_busy")
        return
    try:
        waiting = await _fire_placeholder(context, store, user_id)
    except TelegramError as exc:
        log.info("could not put up the fire placeholder: %s", exc)
        await refuse("inline_need_start")
        return
    result = InlineQueryResultCachedMpeg4Gif(
        id=f"{FIRE_RESULT}{uuid.uuid4().hex[:16]}", mpeg4_file_id=waiting,
        title=i18n.t("inline_fire_title", lang),
        caption=i18n.t("inline_fire_caption", lang),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
            i18n.t("btn_fire_wait", lang), callback_data="fire:wait")]]))
    await query.answer([result], cache_time=0, is_personal=True)


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
    async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.inline_query
        arrived = asyncio.get_running_loop().time()
        lang = i18n.resolve(update, context.user_data)
        raw = query.query.strip()
        burning = fire_text(raw)

        raw = LEADING_COMMAND_RE.sub("", raw).strip()
        if raw.startswith(GALLERY_PREFIX):
            await answer_gallery(query, context, raw[len(GALLERY_PREFIX):], lang)
            return
        if not raw and context.user_data.get(gallery.KEY):
            # Nothing typed yet: their own GIFs, with the way to make a new
            # quote still on the button above them.
            await answer_gallery(query, context, "", lang, hint="inline_empty")
            return
        if burning is None and (not raw or COMMAND_ONLY_RE.match(raw)):
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

        if burning is not None:
            await answer_fire(query, context, burning, lang,
                              storage_chat or context.bot_data.get("storage_chat"))
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
        # The same rule the commands use. Passing the uploaded file without the
        # source is what made inline ignore a picture somebody had chosen.
        chosen, avatar_source = authors.choice_for(context.bot_data, author)
        template = context.user_data.get("template")
        if template not in render.TEMPLATES:
            template = render.DEFAULT_TEMPLATE
        key = cache_key(query.from_user.id, f"{avatar_source}:{chosen or ''}",
                        template, text)

        # Before anything else, including the wait for typing to stop. A repeat
        # of a text already rendered costs one dictionary lookup, and the whole
        # point of the cache is that the answer beats the query being closed.
        remembered = _cached(context, key)
        if remembered:
            results = build_results(lang, *remembered)
            remember_offer(context, results, remembered[1])
            await _answer(query, results, arrived)
            log.info("inline answered from cache in %.1fs",
                     asyncio.get_running_loop().time() - arrived)
            return

        # Only the most recent keystroke should reach the renderer.
        context.user_data["inline_seq"] = query.id
        _abandon(query.from_user.id)
        await asyncio.sleep(DEBOUNCE_SECONDS)
        if context.user_data.get("inline_seq") != query.id:
            return

        now = time.time()
        last = context.user_data.get("inline_render", 0.0)
        if 0 <= now - last < INLINE_COOLDOWN or throttle.RENDER.full:
            await query.answer(
                [], cache_time=1, is_personal=True,
                button=InlineQueryResultsButton(
                    text=i18n.t("inline_wait", lang), start_parameter="inline"),
            )
            return
        context.user_data["inline_render"] = now

        # .env wins. A channel the bot adopted by being made an admin of it is
        # a convenience for when nothing is configured; it must not quietly
        # replace a store that was chosen deliberately.
        store = storage_chat or context.bot_data.get("storage_chat")

        clock = asyncio.get_running_loop().time
        started = clock()
        try:
            avatar = await authors.fetch_avatar(
                context.bot, author, chosen, avatar_source)
            got_avatar = clock()
            scene = await throttle.RENDER.run(
                render.build_scene, avatar, text, author.name, watermark,
                template,
            )
            # The animation is a couple of hundred frames through ffmpeg and
            # then an upload of its own - the longest job here by far, so it is
            # started the moment there is a scene to render, before the two
            # stills are even encoded. Nothing waits for it.
            gif = asyncio.ensure_future(_make_animation(
                context, store, query.from_user.id, scene))
            _remember_task(query.from_user.id, gif)

            try:
                png, webp = await throttle.RENDER.run(_stills, scene)
            except BaseException:
                gif.cancel()
                raise
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
                _abandon(query.from_user.id)
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
        except throttle.Busy:
            await query.answer(
                [], cache_time=1, is_personal=True,
                button=InlineQueryResultsButton(
                    text=i18n.t("inline_wait", lang), start_parameter="inline"),
            )
            return
        except Exception:  # noqa: BLE001 - one bad query must not kill the handler
            log.exception("inline render failed")
            await _answer(query, [])
            return

        results = build_results(lang, photo_id, sticker_id, animation_id)
        # Offering something is not sending it. The pack is filled when one of
        # these is actually chosen, which arrives as a separate update.
        remember_offer(context, results, sticker_id)
        await _answer(query, results, arrived)

    async def on_inline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Telegram closes a query a few seconds after opening it, and every
        # way of answering one - a hint, the archive, a refusal, the fire
        # placeholder - can arrive after that on a slow link. That is not a
        # fault; the next keystroke is answered. Only the main path knew it.
        try:
            await answer(update, context)
        except BadRequest as exc:
            if not _closed(exc):
                raise
            log.info("an inline query closed before it was answered")

    return on_inline


def _closed(exc: Exception) -> bool:
    """Whether Telegram refused an answer because the query had already closed."""
    text = str(exc).lower()
    return "too old" in text or "query id is invalid" in text


def _stills(scene):
    """The card and the sticker, from one render: one job for the gate."""
    image = scene.render()
    return render.to_png(image), render.to_sticker_webp(image)


async def _make_animation(context, storage_chat, user_id, scene):
    """Render the animation and put it up, off the answer's critical path.

    When the renderer is full, there is simply no animation this time: the
    card and the sticker are what the answer cannot go out without.
    """
    try:
        animation = await throttle.RENDER.run(animate.to_animation, scene)
    except throttle.Busy:
        return None
    return await _upload_animation(context, storage_chat, user_id, animation)


async def _finish(context, key: str, ids: tuple, gif) -> None:
    """Wait for the animation, whenever it lands, and remember all three."""
    animation_id = None
    try:
        animation_id = await gif
    except asyncio.CancelledError:
        return  # a newer keystroke replaced it; there is nothing to remember
    except Exception:  # noqa: BLE001 - nothing to answer any more either way
        log.debug("inline animation never arrived for %s", key.split(":", 1)[0])
    _remember(context, key, (*ids, animation_id))


async def _answer(query, results, opened: float = 0.0) -> None:
    """Answer the query, unless Telegram has already closed it.

    A query that took too long is not a fault worth a traceback: the work is
    done and cached, and the next keystroke will be answered from it.
    """
    try:
        await query.answer(results, cache_time=30, is_personal=True)
    except BadRequest as exc:
        if _closed(exc):
            log.info("inline query was closed %.1fs after it arrived, before the "
                     "answer went out", asyncio.get_running_loop().time() - opened)
            return
        raise
