#!/usr/bin/env python3

import asyncio
import contextlib
import logging

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings
from telegram import Bot
from telegram.constants import ParseMode

from passabot.authenticators import AuthData, Authenticator, Credentials
from passabot.scraper_api import ApiScraper

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] {%(filename)s:%(lineno)d} %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("passabot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class Secrets(BaseSettings):
    SPID_SESSION_ID: str = Field(default=...)
    CSRF_TOKEN: str = Field(default=...)
    SPID_USERNAME: str = Field(default=...)
    SPID_PASSWORD: str = Field(default=...)
    TARGET_PROVINCE: str = Field(default=...)

    TELEGRAM_BOT_TOKEN: str = Field(default=...)
    TELEGRAM_DATA_CHAT_ID: str = Field(default=...)
    TELEGRAM_CONTROL_CHAT_ID: str = Field(default=...)

    def get_credentials(self) -> Credentials:
        return Credentials(
            username=self.SPID_USERNAME,
            password=self.SPID_PASSWORD,
        )

    def get_auth_data(self) -> AuthData:
        return AuthData(
            csrf_token=self.CSRF_TOKEN,
            session_id=self.SPID_SESSION_ID,
        )


async def main() -> None:
    load_dotenv()
    secrets = Secrets()

    # authenticator = ManualAuthenticator(secrets.get_auth_data())
    authenticator = Authenticator(secrets.get_credentials())
    scraper = ApiScraper(authenticator, secrets.TARGET_PROVINCE)
    await scraper.login()

    async with Bot(secrets.TELEGRAM_BOT_TOKEN) as bot:
        await bot.send_message(chat_id=secrets.TELEGRAM_CONTROL_CHAT_ID, text="Bot started")
        try:
            await asyncio.create_task(
                scraper.check_availability(bot, secrets.TELEGRAM_DATA_CHAT_ID, secrets.TELEGRAM_CONTROL_CHAT_ID)
            )
        except Exception as e:
            message = f"An error occurred:\n\n<code>{e}</code>"
            await bot.send_message(chat_id=secrets.TELEGRAM_CONTROL_CHAT_ID, text=message, parse_mode=ParseMode.HTML)
            raise


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
