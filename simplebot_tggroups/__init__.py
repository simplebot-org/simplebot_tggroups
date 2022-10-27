"""hooks, filters and commands definitions."""

import asyncio
import os
from tempfile import NamedTemporaryFile, TemporaryDirectory
from threading import Thread

import simplebot
from deltachat import Chat, Contact, Message
from simplebot import DeltaBot
from simplebot.bot import Replies
from telethon import TelegramClient, events

from .orm import Link, init, session_scope
from .subcommands import telegram
from .util import AsyncQueue, get_session_path, getdefault, sync

msgs_queue: AsyncQueue = AsyncQueue()


class TelegramBot(TelegramClient):  # noqa
    def __init__(self, dcbot: DeltaBot) -> None:
        super().__init__(
            get_session_path(dcbot),
            api_id=getdefault(dcbot, "api_id"),
            api_hash=getdefault(dcbot, "api_hash"),
        )
        self.dcbot = dcbot
        self.add_event_handler(self.start_cmd, events.NewMessage(pattern="/start"))
        self.add_event_handler(self.id_cmd, events.NewMessage(pattern="/id"))
        self.add_event_handler(self.tg2dc, events.NewMessage)

    async def start_cmd(self, event: events.NewMessage) -> None:
        await event.reply(
            "This is a Delta Chat bridge relaybot and does not support direct chats"
        )
        raise events.StopPropagation

    async def id_cmd(self, event: events.NewMessage) -> None:
        await event.reply(str(event.chat_id))
        raise events.StopPropagation

    async def dc2tg(self) -> None:
        while True:
            try:
                tgchat, msg = await msgs_queue.aget()
                if msg.filename:
                    filename = msg.filename
                elif msg.html:
                    filename = msg.html.encode(errors="replace")
                elif msg.text:
                    filename = None
                else:
                    self.dcbot.logger.debug(
                        f"ignoring unsupported message (id={msg.id})"
                    )
                    return
                name = msg.override_sender_name or msg.get_sender_contact().display_name
                text = f"**{name}:** {msg.text}"
                if filename:
                    if isinstance(filename, bytes):
                        with NamedTemporaryFile(suffix=".html") as tmpfile:
                            tmpfile.write(filename)
                            tmpfile.seek(0)
                            await self.send_message(tgchat, text, file=tmpfile)
                            return
                await self.send_message(tgchat, text, file=filename)
            except Exception as ex:
                self.dcbot.logger.exception(ex)

    async def tg2dc(self, event: events.NewMessage) -> None:
        msg = event.message
        if msg.text is None:
            return
        with session_scope() as session:
            dcchats = [
                link.dcchat
                for link in session.query(Link).filter_by(tgchat=event.chat_id)
            ]
        if not dcchats:
            return

        replies = Replies(self.dcbot, self.dcbot.logger)
        args = dict(
            text=msg.text,
            sender=" ".join(
                (msg.sender.first_name or "", msg.sender.last_name or "")
            ).strip(),
        )
        with TemporaryDirectory() as tempdir:
            if msg.file and msg.file.size <= int(getdefault(self.dcbot, "max_size")):
                args["filename"] = await msg.download_media(tempdir)
                if args["filename"] and msg.sticker:
                    args["viewtype"] = "sticker"
            if not args.get("text") and not args.get("filename"):
                return
            for chat_id in dcchats:
                try:
                    replies.add(**args, chat=self.dcbot.get_chat(chat_id))
                    replies.send_reply_messages()
                except Exception as ex:
                    self.dcbot.logger.exception(ex)


@simplebot.hookimpl
def deltabot_init_parser(parser) -> None:
    parser.add_subcommand(telegram)


@simplebot.hookimpl
def deltabot_init(bot: DeltaBot) -> None:
    getdefault(bot, "max_size", str(1024**2 * 5))
    tgbot = getdefault(bot, "telegram_bot")
    tgbot = f" @{tgbot}" if tgbot else ""
    desc = f"""To bridge a Telegram group to a Delta Chat group:

    1. Add the bot{tgbot} to your group in Telegram.
    2. Send /id command in the Telegram group, copy the ID returned by the bot.
    3. Add me to your Delta Chat group.
    4. Send me /bridge command with the group ID obtained in the Telegram group, example: /bridge -1234
    5. Then all messages sent in both groups will be relayed to the other side.
    """
    bot.filters.register(filter_messages, help=desc)


@simplebot.hookimpl
def deltabot_start(bot: DeltaBot) -> None:
    path = os.path.join(os.path.dirname(bot.account.db_path), __name__)
    if not os.path.exists(path):
        os.makedirs(path)
    path = os.path.join(path, "sqlite.db")
    init(f"sqlite:///{path}")
    Thread(target=listen_to_telegram, args=(bot,), daemon=True).start()


@simplebot.hookimpl
def deltabot_member_removed(bot: DeltaBot, chat: Chat, contact: Contact) -> None:
    if bot.self_contact != contact and len(chat.get_contacts()) > 1:
        return

    with session_scope() as session:
        for link in session.query(Link).filter_by(dcchat=chat.id):
            session.delete(link)


def filter_messages(message: Message) -> None:
    if not message.chat.is_multiuser():
        return

    with session_scope() as session:
        for link in session.query(Link).filter_by(dcchat=message.chat.id):
            msgs_queue.put((link.tgchat, message))


@simplebot.command
def bridge(bot: DeltaBot, payload: str, message: Message, replies: Replies) -> None:
    """Bridge this chat with the given Telegram chat."""
    try:
        tgchat = int(payload)
    except ValueError:
        replies.add(
            text="❌ You must provide the ID of the Telegram chat", quote=message
        )
        return

    if not message.chat.is_multiuser():
        replies.add(text="❌ Bridging is supported in group chats only", quote=message)
        return

    try:
        with session_scope() as session:
            session.add(Link(dcchat=message.chat.id, tgchat=tgchat))
        replies.add(text="✔️Bridged", quote=message)
    except Exception as ex:
        bot.logger.exception(ex)
        replies.add(text="❌ This chat is already bridged", quote=message)


@simplebot.command
def unbridge(message: Message, replies: Replies) -> None:
    """Remove the bridge between this chat and Telegram."""
    with session_scope() as session:
        link = session.query(Link).filter_by(dcchat=message.chat.id).first()
        if link:
            session.delete(link)
            replies.add(text="✔️Bridge removed", quote=message)
        else:
            replies.add(text="❌ This chat is not bridged", quote=message)


@sync
async def listen_to_telegram(bot: DeltaBot) -> None:
    if not all(
        (
            getdefault(bot, "api_id"),
            getdefault(bot, "api_hash"),
            getdefault(bot, "token"),
        )
    ):
        bot.logger.warning("Telegram session not configured")
        return

    tgbot = await TelegramBot(bot).start(bot_token=getdefault(bot, "token"))
    asyncio.create_task(tgbot.dc2tg())
    await tgbot.run_until_disconnected()
