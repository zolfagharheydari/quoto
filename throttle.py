"""How much rendering runs at once, and how much may wait for it.

Every card, sticker, GIF and screenshot is seconds of CPU on a two-core server.
Left to themselves they all queued on the default thread pool with no end to
the queue, so a few people sending as fast as they could - or one person in
inline mode, which no cooldown reached - could keep both cores busy for
everybody. Work goes through a Gate instead: a fixed number run, a fixed number
wait, and anything past that is told to come back rather than left in silence.
"""
from __future__ import annotations

import asyncio
import functools


class Busy(Exception):
    """Every slot is taken and the queue is full."""


class Gate:
    def __init__(self, slots: int, queue: int):
        self.slots = slots
        self.limit = slots + queue
        self.pending = 0                    # running and waiting
        self._free = asyncio.Semaphore(slots)

    @property
    def full(self) -> bool:
        return self.pending >= self.limit

    async def run(self, func, *args, **kwargs):
        """Run `func` in a thread once a slot is free. Raises Busy if none will be soon.

        The slot is given back when the thread finishes, not when the caller
        stops waiting. A thread cannot be cancelled: inline mode abandons the
        animation of every keystroke that was not the last, and releasing on
        cancellation counted that work as finished while ffmpeg was still
        running it - the limit would have limited nothing.
        """
        if self.full:
            raise Busy
        self.pending += 1
        try:
            await self._free.acquire()
        except BaseException:
            self.pending -= 1
            raise
        loop = asyncio.get_running_loop()
        work = loop.run_in_executor(None, functools.partial(func, *args, **kwargs))

        def finished(_):
            self._free.release()
            self.pending -= 1

        work.add_done_callback(finished)
        return await asyncio.shield(work)


# Cards, stickers, screenshots and the typing GIF: short jobs, two at a time.
RENDER = Gate(slots=2, queue=10)
# The fire clip takes both cores for seconds on its own: one at a time.
FIRE = Gate(slots=1, queue=3)
# Turning a video into a GIF or a sticker: ffmpeg on someone's whole video.
MEDIA = Gate(slots=1, queue=4)
