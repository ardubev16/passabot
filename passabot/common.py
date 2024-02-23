#!/usr/bin/env python3

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import NoReturn

from telegram import Bot

PASSAPORTOONLINE_URL = "https://passaportonline.poliziadistato.it/cittadino/{}"


@dataclass
class AvailabilityEntry:
    first_available_date: str | None
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


class IScraper(ABC):
    @abstractmethod
    async def login(self) -> None:
        pass

    @abstractmethod
    async def check_availability(self, bot: Bot, chat_id: str) -> NoReturn:
        pass
