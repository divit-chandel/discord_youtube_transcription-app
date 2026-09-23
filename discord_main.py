"""Discord bot that transcribes YouTube links posted in one configured channel.

Set these environment variables before running this file:

    DISCORD_BOT_TOKEN=<your bot token>
    DISCORD_CHANNEL_ID=<the numeric channel id the bot should watch>

The bot must have the Message Content Intent enabled in the Discord Developer
Portal, as well as permission to View Channel, Read Message History, and Send
Messages in the configured channel.
"""

import asyncio
import logging
import os
import re
from collections.abc import Iterable
from pathlib import Path

import discord

from main import main as get_transcript


YOUTUBE_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:youtube\.com|youtu\.be)/\S+", re.IGNORECASE
)
DISCORD_MESSAGE_LIMIT = 2_000


def load_project_env() -> None:
    """Load simple KEY=VALUE settings from the .env next to this script.

    Environment variables already supplied by the operating system take
    precedence, which keeps this suitable for deployment as well as local use.
    """
    env_path = Path(__file__).with_name(".env")
    if not env_path.is_file():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key.isidentifier():
            logging.warning("Ignoring invalid .env variable name: %s", key)
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def get_channel_id() -> int:
    """Read and validate the single channel this bot is allowed to process."""
    value = os.getenv("DISCORD_CHANNEL_ID", "").strip()
    if not value.isdigit():
        raise RuntimeError(
            "DISCORD_CHANNEL_ID must be set to the numeric ID of the channel to watch."
        )
    return int(value)


def split_message(text: str, limit: int = DISCORD_MESSAGE_LIMIT) -> Iterable[str]:
    """Split text into Discord-safe chunks, preferring word boundaries."""
    text = text.strip()
    while text:
        if len(text) <= limit:
            yield text
            return

        split_at = text.rfind(" ", 0, limit)
        if split_at <= 0:
            split_at = limit
        yield text[:split_at]
        text = text[split_at:].lstrip()


class TranscriptionBot(discord.Client):
    def __init__(self, watched_channel_id: int) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.watched_channel_id = watched_channel_id

    async def on_ready(self) -> None:
        logging.info("Logged in as %s; watching channel %s", self.user, self.watched_channel_id)

    async def on_message(self, message: discord.Message) -> None:
        # Ignore other channels, bots (including this bot), and non-YouTube messages.
        if message.author.bot or message.channel.id != self.watched_channel_id:
            return

        match = YOUTUBE_URL_RE.search(message.content)
        if not match:
            return

        video_url = match.group(0).rstrip(">.,!?)]")
        async with message.channel.typing():
            # yt-dlp is blocking, so run it outside Discord's event loop.
            transcript = await asyncio.to_thread(get_transcript, video_url)

        if not transcript:
            await message.reply(
                "I couldn't retrieve a transcript for that video. It may not have captions.",
                mention_author=False,
            )
            return

        chunks = list(split_message(transcript))
        await message.reply("**Transcript:**", mention_author=False)
        for chunk in chunks:
            await message.channel.send(chunk)


def run() -> None:
    load_project_env()
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is not set.")

    bot = TranscriptionBot(get_channel_id())
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run()
