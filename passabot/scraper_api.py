#!/usr/bin/env python3

import asyncio
import logging
from typing import NoReturn

import requests
from telegram import Bot
from telegram.constants import ParseMode
from selenium.common.exceptions import NoSuchElementException

from passabot.authenticators import IAuthenticator
from passabot.common import PASSAPORTOONLINE_URL, AvailabilityEntry, IScraper

logger = logging.getLogger(__name__)


class ResponseError(Exception):
    pass


class ApiScraper(IScraper):
    def __init__(self, authenticator: IAuthenticator, province: str) -> None:
        self.authenticator = authenticator
        self.province = province

    async def login(self) -> bool:
        try:
            auth_data = await self.authenticator.login()
        except NoSuchElementException:
            return False

        self.csrf_token = auth_data.csrf_token
        self.session_id = auth_data.session_id
        return True

    def _scrape_availability(self) -> list[AvailabilityEntry]:
        USER_AGENT = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )
        data = {
            "disponibilitaNonResidenti": True,
            "comune": {"provinciaQuestura": self.province},
            "pageInfo": {"maxResults": 5},
            "sortInfo": {"sortList": [{"sortDirection": 0, "sortProperty": "primaDisponibilitaResidente"}]},
        }

        response = requests.post(
            PASSAPORTOONLINE_URL.format("a/rc/v1/appuntamento/elenca-sede-prima-disponibilita"),
            json=data,
            headers={
                "User-Agent": USER_AGENT,
                "X-Csrf-Token": self.csrf_token,
            },
            cookies={"JSESSIONID": self.session_id},
        )
        if response.status_code != 200:
            raise ResponseError(f"Received status code {response.status_code} from the server")

        entries = []
        for entry in response.json()["list"]:
            first_available_date = None
            if entry["dataPrimaDisponibilitaResidenti"] is not None:
                first_available_date = entry["dataPrimaDisponibilitaResidenti"].split("T")[0]
            entries.append(
                AvailabilityEntry(
                    first_available_date=first_available_date,
                    location=entry["descrizione"].split(" - ")[1],
                    address=entry["indirizzo"],
                    informations=entry["infoUtente"],
                )
            )
        logger.info(f"Found {len(entries)} possible appointments")

        available = [entry for entry in entries if entry.first_available_date is not None]
        logger.info(f"Found {len(available)} available appointments")
        return available

    async def check_availability(self, bot: Bot, data_chat_id: str, control_chat_id: str) -> NoReturn:
        logged_in = True
        notifications_counter = 0
        while True:
            if not logged_in:
                logged_in = await self.login()
                if not logged_in:
                    await bot.send_message(chat_id=control_chat_id, text="Could not login, retrying in 5 minutes...")
                    await asyncio.sleep(60 * 5)
                    continue

            try:
                available = self._scrape_availability()
            except ResponseError as e:
                await bot.send_message(chat_id=control_chat_id, text=str(e))
                logged_in = False
            except requests.exceptions.JSONDecodeError:
                await bot.send_message(
                    chat_id=control_chat_id, text="Could not decode the server response, retrying..."
                )
            else:
                if len(available) == 0:
                    notifications_counter = 0
                else:
                    notifications_counter += 1

                for entry in available:
                    await bot.send_message(
                        chat_id=data_chat_id,
                        text=str(entry),
                        parse_mode=ParseMode.HTML,
                        disable_notification=notifications_counter >= 20,
                    )

            await asyncio.sleep(60)