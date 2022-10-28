"""hooks, filters and commands definitions."""

import asyncio
import logging
import os
from tempfile import NamedTemporaryFile, TemporaryDirectory
from threading import Thread
from typing import Any

import simplebot
from cachelib import FileSystemCache
from deltachat import Chat, Contact, Message
from pydub import AudioSegment
from simplebot import DeltaBot
from simplebot.bot import Replies
from telethon import TelegramClient, events, functions, types
from telethon.errors.rpcerrorlist import ChannelPrivateError, ChatIdInvalidError

from .orm import Link, init, session_scope
from .subcommands import telegram
from .util import AsyncQueue, get_session_path, getdefault, shorten_text, sync

logging.basicConfig(
    format="[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s", level=logging.WARNING
)

msgs_queue: AsyncQueue = AsyncQueue()


class TelegramBot(TelegramClient):  # noqa
    def __init__(self, dcbot: DeltaBot) -> None:
        super().__init__(
            get_session_path(dcbot),
            api_id=getdefault(dcbot, "api_id"),
            api_hash=getdefault(dcbot, "api_hash"),
        )
        self.dcbot = dcbot

        plugin_dir = os.path.join(os.path.dirname(self.dcbot.account.db_path), __name__)
        if not os.path.exists(plugin_dir):
            os.makedirs(plugin_dir)
        cache_dir = os.path.join(plugin_dir, "cache")
        self.cache = FileSystemCache(
            cache_dir, threshold=0, default_timeout=60 * 60 * 24 * 60
        )

        self.add_event_handler(
            self.start_cmd, events.NewMessage(pattern="/start", incoming=True)
        )
        self.add_event_handler(
            self.id_cmd, events.NewMessage(pattern="/id", incoming=True)
        )
        self.add_event_handler(self.tg2dc, events.NewMessage(incoming=True))

    async def set_commands(self) -> None:
        await self(
            functions.bots.SetBotCommandsRequest(
                scope=types.BotCommandScopeDefault(),
                lang_code="en",
                commands=[
                    types.BotCommand(
                        command="/id", description="gets the ID of the current chat"
                    )
                ],
            )
        )

    def _acc2mp3(self, filename: str) -> Any:
        try:
            file_ = NamedTemporaryFile(suffix=".mp3")  # noqa
            audio = AudioSegment.from_file(filename, "aac")
            audio.export(file_.name, format="mp3")
            return file_
        except Exception as err:
            self.dcbot.logger.exception(err)
            return filename

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
                file_: Any = ""
                tgchat, dcmsg = await msgs_queue.aget()
                self.dcbot.logger.debug(f"Sending message (id={dcmsg.id}) to Telegram")
                if dcmsg.filename:
                    if dcmsg.filename.endswith(".aac"):
                        file_ = self._acc2mp3(dcmsg.filename)
                    else:
                        file_ = dcmsg.filename
                elif dcmsg.html:
                    tmpfile = NamedTemporaryFile(suffix=".html")  # noqa
                    tmpfile.write(dcmsg.html.encode(errors="replace"))
                    tmpfile.seek(0)
                    file_ = tmpfile
                if not dcmsg.text and not file_:
                    self.dcbot.logger.debug(
                        f"Ignoring unsupported message (id={dcmsg.id})"
                    )
                    return
                reply_to = None
                if dcmsg.quote:
                    reply_to = self.cache.get(f"d{tgchat}/{dcmsg.quote.id}")
                name = (
                    dcmsg.override_sender_name
                    or dcmsg.get_sender_contact().display_name
                )
                text = f"**{shorten_text(name, 30)}:** {dcmsg.text}"
                tgmsg = await self.send_message(
                    tgchat, text, file=file_ or None, reply_to=reply_to
                )
                self.cache.set(f"d{tgchat}/{dcmsg.id}", tgmsg.id)
                self.cache.set(f"t{tgchat}/{tgmsg.id}", dcmsg.id)
            except (ChannelPrivateError, ChatIdInvalidError, ValueError) as ex:
                self.dcbot.logger.exception(ex)
                try:
                    unbridged_chats = []
                    with session_scope() as session:
                        for link in session.query(Link).filter_by(tgchat=tgchat):
                            self.dcbot.logger.debug(
                                f"Removing bridge between {link.tgchat}) and {link.dcchat}"
                            )
                            unbridged_chats.append(link.dcchat)
                            session.delete(link)
                    replies = Replies(dcmsg, self.dcbot.logger)
                    for chat_id in unbridged_chats:
                        replies.add(
                            text=(
                                "❌ Chat unbridged from Telegram chat, make sure the chat ID is correct"
                                " or that the bot was not removed from the Telegram chat"
                            ),
                            chat=self.dcbot.get_chat(chat_id),
                        )
                        replies.send_reply_messages()
                except Exception as err:
                    self.dcbot.logger.exception(err)
            except Exception as ex:
                self.dcbot.logger.exception(ex)
            finally:
                if not isinstance(file_, str):
                    try:
                        file_.close()
                    except Exception as ex:
                        self.dcbot.logger.exception(ex)

    async def tg2dc(self, event: events.NewMessage) -> None:
        self.dcbot.logger.debug(
            f"Got message (id={event.message.id}) from Telegram chat (id={event.chat_id})"
        )
        tgmsg = event.message
        if tgmsg.text is None:
            return
        with session_scope() as session:
            dcchats = [
                link.dcchat
                for link in session.query(Link).filter_by(tgchat=event.chat_id)
            ]
        if not dcchats:
            self.dcbot.logger.debug(
                f"Ignoring message from Telegram chat (id={event.chat_id})"
            )
            return

        replies = Replies(self.dcbot, self.dcbot.logger)
        args = dict(
            text=tgmsg.text,
            sender=" ".join(
                (tgmsg.sender.first_name or "", tgmsg.sender.last_name or "")
            ).strip(),
        )
        with TemporaryDirectory() as tempdir:
            if tgmsg.file and tgmsg.file.size <= int(
                getdefault(self.dcbot, "max_size")
            ):
                args["filename"] = await tgmsg.download_media(tempdir)
                if args["filename"] and tgmsg.sticker:
                    args["viewtype"] = "sticker"
            if not args.get("text") and not args.get("filename"):
                return
            if tgmsg.reply_to and tgmsg.reply_to.reply_to_msg_id:
                quote_id = self.cache.get(
                    f"t{event.chat_id}/{tgmsg.reply_to.reply_to_msg_id}"
                )
                if quote_id:
                    try:
                        args["quote"] = self.dcbot.account.get_message_by_id(quote_id)
                    except Exception as ex:
                        self.dcbot.logger.exception(ex)
            for chat_id in dcchats:
                try:
                    replies.add(**args, chat=self.dcbot.get_chat(chat_id))
                    dcmsg = replies.send_reply_messages()[0]
                    self.cache.set(f"d{event.chat_id}/{dcmsg.id}", tgmsg.id)
                    self.cache.set(f"t{event.chat_id}/{tgmsg.id}", dcmsg.id)
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
            bot.logger.debug(f"Removing bridge with Telegram chat (id={link.tgchat})")
            session.delete(link)


def filter_messages(bot: DeltaBot, message: Message) -> None:
    if not message.chat.is_multiuser():
        return

    with session_scope() as session:
        for link in session.query(Link).filter_by(dcchat=message.chat.id):
            bot.logger.debug(f"Queuing message (id={message.id}) to Telegram")
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
async def listen_to_telegram(dcbot: DeltaBot) -> None:
    if not all(
        (
            getdefault(dcbot, "api_id"),
            getdefault(dcbot, "api_hash"),
            getdefault(dcbot, "token"),
        )
    ):
        dcbot.logger.warning("Telegram session not configured")
        return

    tgbot = await TelegramBot(dcbot).start(bot_token=getdefault(dcbot, "token"))
    dcbot.logger.debug("Connected to Telegram")
    await tgbot.set_commands()
    dcbot.logger.debug("Registered commands on Telegram")
    asyncio.create_task(tgbot.dc2tg())
    await tgbot.run_until_disconnected()
