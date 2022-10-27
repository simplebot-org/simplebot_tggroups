"""Utilities"""

import asyncio
import os
import queue
from functools import wraps

from simplebot import DeltaBot

_scope = __name__.split(".", maxsplit=1)[0]


class AsyncQueue(queue.Queue):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.timeout = 0.02

    async def aget(self):
        while True:
            try:
                return self.get_nowait()
            except queue.Empty:
                await asyncio.sleep(self.timeout)

    async def aput(self, data):
        while True:
            try:
                return self.put_nowait(data)
            except queue.Full:
                await asyncio.sleep(self.timeout)


def sync(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        asyncio.new_event_loop().run_until_complete(func(*args, **kwargs))

    return wrapper


def getdefault(bot: DeltaBot, key: str, value: str = None) -> str:
    val = bot.get(key, scope=_scope)
    if val is None and value is not None:
        bot.set(key, value, scope=_scope)
        val = value
    return val


def set_config(bot: DeltaBot, key: str, value: str = None) -> None:
    bot.set(key, value, scope=_scope)


def get_session_path(bot: DeltaBot) -> str:
    path = os.path.join(os.path.dirname(bot.account.db_path), _scope)
    if not os.path.exists(path):
        os.makedirs(path)
    return os.path.join(path, "telegram.session")
