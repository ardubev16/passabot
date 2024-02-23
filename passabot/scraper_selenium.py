#!/usr/bin/env python3

import asyncio
import logging
from typing import NoReturn

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.wait import WebDriverWait
from telegram import Bot
from telegram.constants import ParseMode

from passabot.authenticators import IAuthenticator
from passabot.common import PASSAPORTOONLINE_URL, AvailabilityEntry, IScraper

logger = logging.getLogger(__name__)


def _serialize_availability_table(table: WebElement) -> list[AvailabilityEntry]:
    entries = []
    for row in table.find_elements(By.TAG_NAME, "tr"):
        cells = row.find_elements(By.TAG_NAME, "td")
        first_available_date = None
        if cells[1].text != "La sede non offre al momento disponibilità di appuntamenti.":
            first_available_date = cells[1].text
        entries.append(
            AvailabilityEntry(
                first_available_date=first_available_date,
                location=cells[2].text,
                address=cells[3].text.replace("\n", " "),
                informations=str(cells[4].get_property("title")),
            )
        )
    return entries


class SeleniumScraper(IScraper):
    def __init__(self, authenticator: IAuthenticator, headless: bool = True) -> None:
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument("--no-sandbox")
        if headless:
            chrome_options.add_argument("--headless")

        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.implicitly_wait(5)
        self.wait = WebDriverWait(self.driver, 5)
        self.authenticator = authenticator

    def _refresh(self) -> None:
        self.driver.refresh()

    def _is_logged_in(self) -> bool:
        return "login" not in self.driver.current_url

    async def login(self) -> bool:
        try:
            auth_data = await self.authenticator.login()
        except NoSuchElementException:
            return False
        self.driver.add_cookie(
            {
                "name": "JSESSIONID",
                "value": auth_data.session_id,
            }
        )
        logger.info("Logged in with JSESSIONID cookie")
        return True

    def _view_locations(self) -> None:
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
            raise NoSuchElementException("Could not find selectRichiedente")

        Select(self.driver.find_element(By.ID, "selectRichiedente")).select_by_visible_text("Me stesso")
        self.driver.find_element(By.XPATH, "//button[contains(text(), 'Continua')]").click()

    async def _refresh_session(self) -> bool:
        self._refresh()
        if self._is_logged_in():
            return True

        login_result = await self.login()
        if not login_result:
            logger.error("Could not login, retrying in 5 minutes...")
            return False

        return True

    def _scrape_availability(self) -> list[AvailabilityEntry]:
        table = self.driver.find_element(
            By.XPATH,
            '//*[@id="tabComuneScelto"]/section/section/section/table/tbody',
        )
        serialized = _serialize_availability_table(table)
        logger.info(f"Found {len(serialized)} possible appointments")

        available = [entry for entry in serialized if entry.first_available_date is not None]
        logger.info(f"Found {len(available)} available appointments")

        return available

    async def check_availability(self, bot: Bot, data_chat_id: str, control_chat_id: str) -> NoReturn:
        self._view_locations()
        try:
            while True:
                logged_in = await self._refresh_session()
                if logged_in:
                    try:
                        available = self._scrape_availability()
                    except NoSuchElementException:
                        logger.error("Could not find the availability table, retrying...")
                        await bot.send_message(
                            chat_id=control_chat_id, text="Could not find the availability table, retrying..."
                        )
                    else:
                        for entry in available:
                            await bot.send_message(chat_id=data_chat_id, text=str(entry), parse_mode=ParseMode.HTML)
                    await asyncio.sleep(60)
                else:
                    await bot.send_message(chat_id=control_chat_id, text="Could not login, retrying in 5 minutes...")
                    await asyncio.sleep(60 * 5)
        except NoSuchElementException:
            self.driver.save_screenshot("error.png")
            raise
