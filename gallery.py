"""Everyone's own archive of the GIFs they have made, searchable by who is in them.

Kept in the maker's user_data: the archive belongs to whoever made the GIFs, not
to the people in them, and user_data is already persisted with everything else.
Only Telegram's file_id is stored, never the file - a GIF Telegram holds can be
sent again by its id, so an entry is a couple of hundred bytes.
"""
from __future__ import annotations

import time
import unicodedata

KEY = "gifs"
LIMIT = 300          # per person; the oldest go first
PAGE = 50            # the most Telegram takes in one inline answer
QUOTE_CHARS = 80     # enough of the quote to tell two GIFs apart

# Letters that look the same but are different code points, depending on which
# keyboard typed them. Someone searching on one keyboard for a name typed on
# another should still find it.
_FOLD = str.maketrans({
    "ي": "ی",   # Arabic yeh -> Persian yeh
    "ى": "ی",   # alef maksura -> Persian yeh
    "ك": "ک",   # Arabic kaf -> keheh
    "ة": "ه",   # teh marbuta -> heh
    "ـ": None,       # tatweel
    "‌": None,       # zero-width non-joiner
    "‍": None,       # zero-width joiner
})


def fold(text: str | None) -> str:
    """The form names are compared in: case, width, keyboard and spacing set aside."""
    text = unicodedata.normalize("NFKC", text or "").casefold()
    return " ".join(text.translate(_FOLD).split())


def record(user_data: dict, file_id: str, author, quote: str = "") -> None:
    """File one GIF in its maker's archive.

    `author` is whoever the GIF quotes. A person keeps their numeric id, so they
    can be found by it even after changing their name; a channel or an anonymous
    admin is filed under its title alone.
    """
    if not file_id:
        return
    gifs = user_data.setdefault(KEY, [])
    # The same file sent twice is one GIF, not two; the newer copy wins.
    gifs[:] = [g for g in gifs if g.get("f") != file_id]
    gifs.append({
        "f": file_id,
        "u": author.avatar_key if getattr(author, "kind", "") == "user" else None,
        "n": (getattr(author, "name", "") or "")[:64],
        "h": (getattr(author, "handle", "") or "")[:32],
        "q": " ".join((quote or "").split())[:QUOTE_CHARS],
        "t": int(time.time()),
    })
    del gifs[:-LIMIT]


def search(user_data: dict, term: str = "") -> list[dict]:
    """This person's GIFs whose subject matches `term`, newest first.

    A term matches part of the name or the username, with or without the @, or
    the whole numeric id. An empty term is everything.
    """
    gifs = list(reversed(user_data.get(KEY) or []))
    needle = fold(term).lstrip("@")
    if not needle:
        return gifs
    if needle.lstrip("-").isdigit():
        return [g for g in gifs if str(g.get("u")) == needle]
    return [g for g in gifs
            if needle in fold(g.get("n")) or needle in fold(g.get("h"))]


def people(user_data: dict) -> int:
    """How many different people this person has made GIFs of."""
    return len({g.get("u") or fold(g.get("n")) for g in user_data.get(KEY) or []})
