"""Playwright stealth browser management with anti-detection."""

import asyncio
import logging
import random
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from playwright_stealth import Stealth

from consensus_engine import config as cfg

_stealth = Stealth()

log = logging.getLogger("consensus_engine.browser")


def _random_user_agent() -> str:
    agents = cfg.get("browser.user_agents", [])
    if not agents:
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    return random.choice(agents)


def _random_viewport() -> dict:
    widths = [1366, 1440, 1536, 1920, 2560]
    heights = [768, 900, 864, 1080, 1440]
    idx = random.randint(0, len(widths) - 1)
    return {"width": widths[idx], "height": heights[idx]}


async def random_delay(min_override: float | None = None, max_override: float | None = None):
    """Sleep for a random duration to mimic human behavior."""
    min_s = min_override if min_override is not None else cfg.get("browser.min_delay_seconds", 2)
    max_s = max_override if max_override is not None else cfg.get("browser.max_delay_seconds", 8)
    delay = random.uniform(min_s, max_s)
    await asyncio.sleep(delay)


@asynccontextmanager
async def create_stealth_browser() -> AsyncGenerator[tuple[Browser, BrowserContext], None]:
    """Create a Playwright browser with stealth mode enabled.

    Usage:
        async with create_stealth_browser() as (browser, context):
            page = await context.new_page()
            await page.goto("https://example.com")
    """
    headless = cfg.get("browser.headless", True)
    proxy_url = cfg.get("browser.proxy")
    timeout_ms = cfg.get("browser.page_timeout_seconds", 30) * 1000

    pw = await async_playwright().start()
    browser = None
    try:
        launch_args = {
            "headless": headless,
            "args": [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        }
        if proxy_url:
            launch_args["proxy"] = {"server": proxy_url}

        browser = await pw.chromium.launch(**launch_args)

        context = await browser.new_context(
            user_agent=_random_user_agent(),
            viewport=_random_viewport(),
            locale="en-US",
            timezone_id="America/New_York",
            color_scheme="light",
            java_script_enabled=True,
        )
        context.set_default_timeout(timeout_ms)
        context.set_default_navigation_timeout(timeout_ms)

        yield browser, context
    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        await pw.stop()


async def stealth_page(context: BrowserContext) -> Page:
    """Create a new page with stealth patches applied."""
    page = await context.new_page()
    await _stealth.apply_stealth_async(page)
    return page


async def safe_goto(page: Page, url: str, wait_until: str = "domcontentloaded") -> bool:
    """Navigate to a URL with error handling. Returns True on success."""
    try:
        response = await page.goto(url, wait_until=wait_until)
        if response and response.status >= 400:
            log.warning("HTTP %d for %s", response.status, url)
            return False
        return True
    except Exception as e:
        log.warning("Navigation failed for %s: %s", url, e)
        return False
