#!/usr/bin/env python3

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import List, NoReturn

import selenium.webdriver.support.expected_conditions as EC
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.wait import WebDriverWait
from telegram import Bot
from telegram.constants import ParseMode


PASSAPORTOONLINE_URL = "https://passaportonline.poliziadistato.it/cittadino/{}"
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] {%(filename)s:%(lineno)d} %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("passabot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


@dataclass
class Credentials:
    username: str
    password: str


class Secrets(BaseSettings):
    SPID_SESSION_ID: str = Field(default=...)
    SPID_USERNAME: str = Field(default=...)
    SPID_PASSWORD: str = Field(default=...)

    TELEGRAM_BOT_TOKEN: str = Field(default=...)
    TELEGRAM_CHAT_ID: str = Field(default=...)

    def get_credentials(self) -> Credentials:
        return Credentials(
            username=self.SPID_USERNAME,
            password=self.SPID_PASSWORD,
        )


@dataclass
class AvailabilityEntry:
    # NOTE: selector is saved to be able to click on the element later
    selector: WebElement
    first_available_date: str
    location: str
    address: str
    informations: str

    def __repr__(self) -> str:
        return f"""\
<b>Prima data disponibile:</b> {self.first_available_date}
<b>Sede:</b> {self.location}
<b>Indirizzo:</b> {self.address}

{self.informations}
        """


def _serialize_availability_table(table: WebElement) -> List[AvailabilityEntry]:
    entries = []
    for row in table.find_elements(By.TAG_NAME, "tr"):
        cells = row.find_elements(By.TAG_NAME, "td")
        entries.append(
            AvailabilityEntry(
                selector=cells[0],
                first_available_date=cells[1].text,
                location=cells[2].text,
                address=cells[3].text.replace("\n", " "),
                informations=str(cells[4].get_property("title")),
            )
        )
    return entries


class PassaportoOnline:
    def __init__(self, headless: bool = True) -> None:
        chrome_options = webdriver.ChromeOptions()
        if headless:
            chrome_options.add_argument("--headless")

        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.implicitly_wait(5)
        self.wait = WebDriverWait(self.driver, 5)

    def _fill_login_form(self, credentials: Credentials) -> None:
        self.driver.find_element(By.ID, "username").send_keys(credentials.username)
        self.driver.find_element(By.ID, "password").send_keys(credentials.password)
        self.driver.find_element(By.XPATH, "//button[@type='submit']").click()
        logger.info("Submitted login credentials")

    def cookie_login(self, session_id: str) -> None:
        self.driver.get("https://passaportonline.poliziadistato.it")
        self.driver.add_cookie(
            {
                "name": "JSESSIONID",
                "value": session_id,
            }
        )
        logger.info("Logged in with JSESSIONID cookie")

    def is_logged_in(self) -> bool:
        return "login" not in self.driver.current_url

    def _refresh(self) -> None:
        self.driver.refresh()

    async def login(self, credentials: Credentials) -> None:
        LOGIN_URL = PASSAPORTOONLINE_URL.format("n/sc/loginCittadino/sceltaLogin")

        # Go to the login page (PosteID)
        self.driver.get(LOGIN_URL)
        self.driver.find_element(By.XPATH, "//span[contains(text(), 'Entra con SPID')]").click()
        self.wait.until(EC.url_changes(LOGIN_URL))
        self.driver.find_element(By.XPATH, "//span[contains(text(), 'Entra con SPID')]").click()
        self.driver.find_element(By.XPATH, '//li[@data-idp="https://posteid.poste.it"]').click()

        # Actual login process
        self._fill_login_form(credentials)
        self.driver.find_element(By.XPATH, "//span[contains(., 'Voglio ricevere una notifica')]").click()
        logger.info("Waiting for the user to confirm the login...")
        await asyncio.sleep(60)
        self.driver.find_element(By.XPATH, "//button[contains(text(), 'Acconsento')]").click()
        session_id = self.driver.get_cookie("JSESSIONID")
        logger.info(f"Session ID: {session_id}")

    def view_locations(self) -> None:
        SCELTA_COMUNE_URL = PASSAPORTOONLINE_URL.format("a/sc/wizardAppuntamentoCittadino/sceltaComune")

        self.driver.get(SCELTA_COMUNE_URL)
        for _ in range(3):
            try:
                self.driver.find_element(By.ID, "selectRichiedente").click()
                break
            except NoSuchElementException:
                logger.error("Could not find selectRichiedente, refreshing...")
            self.driver.refresh()
        else:
            raise TimeoutException("Could not find selectRichiedente")

        Select(self.driver.find_element(By.ID, "selectRichiedente")).select_by_visible_text("Me stesso")
        self.driver.find_element(By.XPATH, "//button[contains(text(), 'Continua')]").click()

    def check_availability(self) -> List[AvailabilityEntry]:
        table = self.driver.find_element(
            By.XPATH,
            '//*[@id="tabComuneScelto"]/section/section/section/table/tbody',
        )
        serialized = _serialize_availability_table(table)
        logger.info(f"Found {len(serialized)} possible appointments")

        available = [
            entry
            for entry in serialized
            if entry.first_available_date != "La sede non offre al momento disponibilità di appuntamenti."
        ]
        logger.info(f"Found {len(available)} available appointments")

        return available

    async def refresh_session(self, credentials: Credentials) -> bool:
        self._refresh()
        if self.is_logged_in():
            return True

        try:
            await self.login(credentials)
            self.view_locations()
            return True
        except NoSuchElementException:
            logger.error("Could not login, retrying in 5 minutes...")
            return False


async def check_availability(po: PassaportoOnline, credentials: Credentials, bot: Bot, chat_id: str) -> NoReturn:
    while True:
        logged_in = await po.refresh_session(credentials)
        if logged_in:
            available = po.check_availability()
            for entry in available:
                await bot.send_message(chat_id=chat_id, text=str(entry), parse_mode=ParseMode.HTML)
            await asyncio.sleep(60)
        else:
            bot.send_message(chat_id=chat_id, text="Could not login, retrying in 5 minutes...")
            await asyncio.sleep(60 * 5)


async def send_heartbeat(bot: Bot, chat_id: str) -> NoReturn:
    while True:
        await bot.send_message(chat_id=chat_id, text="Heartbeat, I'm running!", disable_notification=True)
        await asyncio.sleep(60 * 60)


async def main() -> NoReturn:
    load_dotenv()
    secrets = Secrets()

    po = PassaportoOnline()
    credentials = secrets.get_credentials()
    await po.login(credentials)
    # po.cookie_login(secrets.SPID_SESSION_ID)
    po.view_locations()

    async with Bot(secrets.TELEGRAM_BOT_TOKEN) as bot:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(check_availability(po, credentials, bot, secrets.TELEGRAM_CHAT_ID))
            tg.create_task(send_heartbeat(bot, secrets.TELEGRAM_CHAT_ID))


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
