#!/usr/bin/env python3

import asyncio
import logging
from typing import Any, NoReturn

import requests
from selenium.common.exceptions import NoSuchElementException
from telegram import Bot
from telegram.constants import ParseMode
from datetime import datetime

from passabot.authenticators import IAuthenticator
from passabot.common import PASSAPORTOONLINE_URL, AvailabilityEntry, IScraper

logger = logging.getLogger(__name__)


class ResponseError(Exception):
    def __init__(self, response: requests.Response) -> None:
        super().__init__(f"Received status code {response.status_code} from the endpoint {response.url}")
        self.response = response


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

    def _post(self, endpoint: str, json: dict[str, Any]) -> requests.Response:
        USER_AGENT = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )

        return requests.post(
            endpoint,
            json=json,
            headers={
                "User-Agent": USER_AGENT,
                "X-Csrf-Token": self.csrf_token,
            },
            cookies={"JSESSIONID": self.session_id},
        )

    def _get_slots(self, id: int) -> list[tuple[datetime, int]]:
        response = self._post(
            PASSAPORTOONLINE_URL.format("n/rc/v1/utility/elenca-agenda-appuntamenti-sede-mese"),
            json={"sede": {"id": id}},
        )
        if response.status_code != 200:
            raise ResponseError(response)

        entries = []
        for obj in response.json()["elenco"]:
            dt_str = obj["objectKey"].split("||_||", 1)[1]
            dt = datetime.strptime(dt_str, "%d/%m/%Y||_||%H.%M")
            entries.append((dt, obj["totAppuntamenti"]))
        entries.sort(key=lambda x: x[0])

        return entries

    def _scrape_availability(self) -> list[AvailabilityEntry]:
        response = self._post(
            PASSAPORTOONLINE_URL.format("a/rc/v1/appuntamento/elenca-sede-prima-disponibilita"),
            json={"comune": {"provinciaQuestura": self.province}},
        )
        if response.status_code != 200:
            raise ResponseError(response)

        entries = []
        possible_appointments = response.json()["list"]
        logger.info(f"Found {len(possible_appointments)} possible appointments")
        for entry in possible_appointments:
            if entry["dataPrimaDisponibilitaResidenti"] is None:
                continue
            first_available_date = entry["dataPrimaDisponibilitaResidenti"].split("T")[0]
            slots = self._get_slots(entry["id"])
            entries.append(
                AvailabilityEntry(
                    first_available_date=first_available_date,
                    slots=slots,
                    location=entry["descrizione"].split(" - ")[1],
                    address=entry["indirizzo"],
                )
            )

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
                message = f"{e}\n\n<pre language='json'>{e.response.headers}</pre>"
                await bot.send_message(chat_id=control_chat_id, text=message, parse_mode=ParseMode.HTML)
                await bot.send_message(chat_id=control_chat_id, text=e.response.text)
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
