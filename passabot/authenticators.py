#!/usr/bin/env python3


import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import selenium.webdriver.support.expected_conditions as EC
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait

from passabot.common import PASSAPORTOONLINE_URL

logger = logging.getLogger(__name__)


@dataclass
class Credentials:
    username: str
    password: str


@dataclass
class AuthData:
    csrf_token: str
    session_id: str


class IAuthenticator(ABC):
    @abstractmethod
    async def login(self) -> AuthData:
        pass


class ManualAuthenticator(IAuthenticator):
    def __init__(self, auth_data: AuthData) -> None:
        self._auth_data = auth_data

    async def login(self) -> AuthData:
        return self._auth_data


class Authenticator(IAuthenticator):
    def __init__(self, credentials: Credentials, headless: bool = True) -> None:
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument("--no-sandbox")
        if headless:
            chrome_options.add_argument("--headless")

        self._credentials = credentials
        self._options = chrome_options

    def _init_driver(self) -> None:
        self.driver = webdriver.Chrome(options=self._options)
        self.driver.implicitly_wait(5)
        self.wait = WebDriverWait(self.driver, 5)

    def _fill_login_form(self) -> None:
        self.driver.find_element(By.ID, "username").send_keys(self._credentials.username)
        self.driver.find_element(By.ID, "password").send_keys(self._credentials.password)
        self.driver.find_element(By.XPATH, "//button[@type='submit']").click()
        logger.info("Submitted login credentials")

    def _get_csrf_token(self) -> str:
        csrf_token = self.driver.find_element(By.XPATH, "//meta[@name='_csrf']").get_attribute("content")
        if csrf_token is None:
            raise ValueError("Could not find CSRF token")
        logger.info(f"CSRF token: {csrf_token}")
        return csrf_token

    def _get_session_id(self) -> str:
        session_id_cookie = self.driver.get_cookie("JSESSIONID")
        if session_id_cookie is None:
            raise ValueError("Could not find JSESSIONID cookie")

        session_id: str = session_id_cookie["value"]
        logger.info(f"Session ID: {session_id}")
        return session_id

    async def login(self) -> AuthData:
        self._init_driver()
        LOGIN_URL = PASSAPORTOONLINE_URL.format("n/sc/loginCittadino/sceltaLogin")

        # Go to the login page (PosteID)
        self.driver.get(LOGIN_URL)
        self.driver.find_element(By.XPATH, "//span[contains(text(), 'Entra con SPID')]").click()
        self.wait.until(EC.url_changes(LOGIN_URL))
        self.driver.find_element(By.XPATH, "//span[contains(text(), 'Entra con SPID')]").click()
        self.driver.find_element(By.XPATH, '//li[@data-idp="https://posteid.poste.it"]').click()

        # Actual login process
        self._fill_login_form()
        self.driver.find_element(By.XPATH, "//span[contains(., 'Voglio ricevere una notifica')]").click()
        logger.info("Waiting for the user to confirm the login...")
        await asyncio.sleep(60)
        self.driver.find_element(By.XPATH, "//button[contains(text(), 'Acconsento')]").click()

        # Save the CSRF token and JSESSIONID cookie
        await asyncio.sleep(10)
        csrf_token = self._get_csrf_token()
        session_id = self._get_session_id()

        self.driver.quit()
        return AuthData(csrf_token=csrf_token, session_id=session_id)
