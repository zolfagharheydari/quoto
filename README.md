# Quoto

A Telegram bot that turns messages into quote cards, stickers, animated GIFs and
message screenshots.

Reply to any message with a command and Quoto draws it: the text, the sender's
name and their profile picture, on a card you can keep or share. Every sticker
it makes is collected into a sticker pack, one per group and one per person.

Try it on Telegram: [@getquoto_bot](https://t.me/getquoto_bot)

## What it does

| Command | Result |
|---|---|
| `/quote` | A quote card of the replied-to message |
| `/sticker` | The same card as a sticker |
| `/gif` | The same card, animated: the text types itself out |
| `/screenshot` | The message drawn the way Telegram shows it, with name, badges, time and reactions |
| `/template` | Choose one of four card designs |
| `/avatar`, `/settings` | Choose which picture stands for you on your cards |
| `/mygifs` | Every GIF you have made, searchable by who is in it |
| `/pack`, `/mypack` | The group's sticker pack, or your own |
| `/unpack`, `/delpack` | Remove one sticker, or a whole pack (group admins, or the pack's owner) |

**Inline mode** works in any chat, including ones the bot is not a member of:
type `@getquoto_bot` followed by some text and pick a card, sticker or GIF from
the menu. Type `@getquoto_bot #name` instead to search the GIFs you have made
of someone, by name, username or numeric id, and send one straight from the
results.

## Text rendering

Most of the work is in getting text right, whatever it is written in:

- **Right-to-left and complex scripts.** Arabic-script letters are shaped into
  their joined forms, lines are laid out right to left, and zero-width
  non-joiners are preserved.
- **Per-character font fallback.** Each run of text is drawn with a font that
  actually contains its glyphs, read from the font's own character table rather
  than guessed. Chinese, Korean, Devanagari, mathematical "fancy" letters and
  colour emoji render on the same card, on a shared baseline.
- **Layout that fits.** Font size is chosen to fit the card, and text that still
  will not fit is trimmed cleanly rather than shrunk until it cannot be read.

## Running it

Requires Python 3.13 or newer and ffmpeg (the `imageio-ffmpeg` package provides
one if the system has none).

```bash
pip install -r requirements.txt
python download_fonts.py
cp .env.example .env      # set BOT_TOKEN, and OWNER_ID for sticker packs and the admin panel
python bot.py
```

`.env.example` documents every setting. For running it permanently on a Linux
server under systemd, see [`deploy/`](deploy/).

To see the cards without Telegram:

```bash
python preview.py preview_out
```

## Tests

```bash
python selftest.py          # offline: about 500 checks
python selftest.py --api    # also creates and deletes a sticker pack on the real API
```

The suite covers text shaping and font fallback, rendering of every card type
and template, the inline cache, sticker-pack permissions, the admin panel,
access boundaries between users, and state that is persisted to disk. It runs
before every deployment.

## Layout

| Path | |
|---|---|
| `bot.py` | Telegram handlers and startup |
| `render.py`, `animate.py` | Quote cards, the four templates, and the typing animation |
| `screenshot.py`, `reactions.py` | Message screenshots and the reaction counts under them |
| `textkit.py`, `fonts.py` | Shaping, bidirectional layout, line breaking, font fallback |
| `inline.py` | Inline mode |
| `authors.py`, `extract.py` | Who said it, their picture, and the text to quote |
| `stickerpack.py` | Group and personal sticker packs |
| `admin.py` | The owner's panel: statistics, broadcast, blocking, quotas |
| `i18n.py` | Every user-facing string |
| `selftest.py` | The test suite |
| `deploy/` | systemd unit and server setup |
| `docs/notes.md` | Detailed design notes |
