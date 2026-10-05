"""Explicit immutable web settings; no environment or credential-file discovery."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit
import time


@dataclass(frozen=True)
class Settings:
    web_path: Path
    market_path: Path
    origin: str = "https://dashboard.test"
    clock: Callable[[], float] = time.time
    provider_registry: object | None = field(default=None, repr=False)

    def __post_init__(self):
        if not self.web_path.is_absolute() or not self.market_path.is_absolute():
            raise ValueError("web and market paths must be absolute")
        self.validate_paths()
        origin = urlsplit(self.origin)
        if (origin.scheme != "https" or not origin.hostname or origin.username
                or origin.password or origin.path or origin.query or origin.fragment):
            raise ValueError("origin must be an HTTPS origin without path or credentials")

    def validate_paths(self) -> None:
        web, market = self.web_path.resolve(), self.market_path.resolve()
        if web == market or (web.exists() and market.exists() and web.samefile(market)):
            raise ValueError("web and market paths must identify distinct files")
