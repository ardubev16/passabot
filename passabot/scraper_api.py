import asyncio
import logging
from datetime import datetime
from typing import NoReturn

import requests
from selenium.common.exceptions import NoSuchElementException
from telegram import Bot
from telegram.constants import ParseMode

from passabot.authenticators import IAuthenticator
from passabot.common import PASSAPORTOONLINE_URL, AvailabilityEntry, IScraper, save_to_file

logger = logging.getLogger(__name__)

MAX_NOTIFICATIONS = 20


class ResponseError(Exception):
    def __init__(self, response: requests.Response) -> None:
        super().__init__(f"Received status code {response.status_code} from the endpoint {response.url}")
        self.response = response


class ApiScraper(IScraper):
    USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"

    def __init__(self, authenticator: IAuthenticator, province: str) -> None:
        self.authenticator = authenticator
        self.province = province
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.USER_AGENT})

    async def login(self) -> bool:
        try:
            auth_data = await self.authenticator.login()
        except NoSuchElementException:
            return False

        self.session.cookies.set("JSESSIONID", auth_data.session_id)
        self.session.headers.update({"X-Csrf-Token": auth_data.csrf_token})

        return True

    def _get_slots(self, sede_id: int) -> list[tuple[datetime, int]]:
        response = self.session.post(
            PASSAPORTOONLINE_URL.format("n/rc/v1/utility/elenca-agenda-appuntamenti-sede-mese"),
            json={"sede": {"id": sede_id}},
        )
        if response.status_code != requests.codes.ok:
            raise ResponseError(response)
        logger.info("Reveived headers: %s", response.headers)

        entries: list[tuple[datetime, int]] = []
        for obj in response.json()["elenco"]:
            dt_str = obj["objectKey"].split("||_||", 1)[1]
            dt = datetime.strptime(dt_str, "%d/%m/%Y||_||%H.%M")
            entries.append((dt, obj["totAppuntamenti"]))
        entries.sort(key=lambda x: x[0])

        return entries

    def _scrape_availability(self) -> list[AvailabilityEntry]:
        response = self.session.post(
            PASSAPORTOONLINE_URL.format("a/rc/v1/appuntamento/elenca-sede-prima-disponibilita"),
            json={"comune": {"provinciaQuestura": self.province}},
        )
        if response.status_code != requests.codes.ok:
            raise ResponseError(response)
        logger.info("Reveived headers: %s", response.headers)

        entries: list[AvailabilityEntry] = []
        possible_appointments = response.json()["list"]
        logger.info("Found %s possible appointments", len(possible_appointments))
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
                ),
            )

        available = [entry for entry in entries if entry.first_available_date is not None]
        logger.info("Found %s available appointments", len(available))
        return available

    async def check_availability(self, bot: Bot, data_chat_id: str, control_chat_id: str) -> NoReturn:
        logged_in = True
        notifications_counter = 0
        while True:
            if not logged_in:
                logged_in = await self.login()
                if not logged_in:
                    await bot.send_message(chat_id=control_chat_id, text="Could not login, retrying in 5 minutes...")  # pyright: ignore[reportCallIssue]
                    await asyncio.sleep(60 * 5)
                    continue

            try:
                available = self._scrape_availability()
            except ResponseError as e:
                filepath = save_to_file(e.response.text)
                message = f'{e}\n<code>{filepath}</code>\n\n<pre language="json">{e.response.headers}</pre>'
                await bot.send_message(chat_id=control_chat_id, text=message, parse_mode=ParseMode.HTML)  # pyright: ignore[reportCallIssue]
                logged_in = False
            except requests.exceptions.JSONDecodeError:
                await bot.send_message(  # pyright: ignore[reportCallIssue]
                    chat_id=control_chat_id,
                    text="Could not decode the server response, retrying...",
                )
            else:
                if len(available) == 0:
                    notifications_counter = 0
                else:
                    notifications_counter += 1

                for entry in available:
                    await bot.send_message(  # pyright: ignore[reportCallIssue]
                        chat_id=data_chat_id,
                        text=str(entry),
                        parse_mode=ParseMode.HTML,
                        disable_notification=notifications_counter >= MAX_NOTIFICATIONS,
                    )

            await asyncio.sleep(60)
