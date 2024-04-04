from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import NoReturn

from telegram import Bot

PASSAPORTOONLINE_URL = "https://passaportonline.poliziadistato.it/cittadino/{}"


@dataclass
class AvailabilityEntry:
    first_available_date: str | None
    slots: list[tuple[datetime, int]]
    location: str
    address: str

    def __repr__(self) -> str:
        slots = "\n".join(f"- <code>{d:%d/%m/%Y, %k:%M}</code>: <b>{s}</b>" for d, s in self.slots)

        return f"""\
<b>Sede:</b> {self.location}
<b>Slot disponibili:</b>
{slots}

<b>Indirizzo:</b> {self.address}
        """


class IScraper(ABC):
    @abstractmethod
    async def login(self) -> bool:
        pass

    @abstractmethod
    async def check_availability(self, bot: Bot, data_chat_id: str, control_chat_id: str) -> NoReturn:
        pass


def save_to_file(data: str) -> Path:
    filename = f"passabot_{datetime.now():%Y-%m-%d_%H-%M-%S}.html"
    path = Path("/tmp", filename)  # noqa: S108
    with path.open("w") as f:
        f.write(data)

    return path
