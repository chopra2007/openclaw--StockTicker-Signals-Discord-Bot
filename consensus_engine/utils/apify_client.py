"""Async Apify client for running actors and fetching results.

Provides a generic interface to run any Apify actor, wait for results,
and return the dataset items. Handles polling, timeouts, and errors.
"""

import asyncio
import logging
from typing import Any, Optional

import aiohttp

from consensus_engine import config as cfg

log = logging.getLogger("consensus_engine.apify")


class ApifyClient:
    """Lightweight async Apify API client."""

    @property
    def _token(self) -> str:
        return cfg.get_api_key("apify_token")

    @property
    def _base(self) -> str:
        return cfg.get("apify.base_url", "https://api.apify.com/v2")

    @property
    def enabled(self) -> bool:
        return bool(cfg.get("apify.enabled", False) and self._token)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def run_actor(
        self,
        actor_id: str,
        input_data: dict,
        timeout_seconds: int | None = None,
        memory_mb: int = 256,
    ) -> list[dict]:
        """Run an Apify actor and return the dataset items.

        Args:
            actor_id: Actor ID in "username/actor-name" or "username~actor-name" format.
            input_data: Input JSON for the actor.
            timeout_seconds: Max wait time. Defaults to config value.
            memory_mb: Memory allocation for the run.

        Returns:
            List of result dicts from the actor's default dataset.
            Empty list on failure or timeout.
        """
        if not self.enabled:
            log.debug("Apify disabled or no token configured")
            return []

        timeout = timeout_seconds or cfg.get("apify.run_timeout", 120)
        # Normalize actor_id: "username/name" → "username~name" for API
        api_actor_id = actor_id.replace("/", "~")

        try:
            async with aiohttp.ClientSession() as session:
                # Start the run with waitForFinish
                url = f"{self._base}/acts/{api_actor_id}/runs"
                params = {"waitForFinish": timeout}
                body = input_data

                log.info("Apify: starting %s (timeout=%ds)", actor_id, timeout)

                async with session.post(
                    url, headers=self._headers(), json=body, params=params,
                    timeout=aiohttp.ClientTimeout(total=timeout + 30),
                ) as resp:
                    if resp.status not in (200, 201):
                        error = await resp.text()
                        log.warning("Apify run failed for %s (%d): %s",
                                    actor_id, resp.status, error[:200])
                        return []

                    run_data = (await resp.json()).get("data", {})

                status = run_data.get("status")
                dataset_id = run_data.get("defaultDatasetId")
                run_id = run_data.get("id", "?")

                if status != "SUCCEEDED":
                    # If still running, poll until done
                    if status == "RUNNING":
                        run_data = await self._poll_run(session, run_id, timeout)
                        status = run_data.get("status")
                        dataset_id = run_data.get("defaultDatasetId")

                    if status != "SUCCEEDED":
                        log.warning("Apify run %s finished with status: %s", run_id, status)
                        return []

                if not dataset_id:
                    log.warning("Apify run %s has no dataset", run_id)
                    return []

                # Fetch dataset items
                items = await self._fetch_dataset(session, dataset_id)
                # Filter out placeholder items
                real_items = [
                    i for i in items
                    if not i.get("noResults") and not i.get("demo")
                ]

                log.info("Apify %s: %d items (%d after filtering)",
                         actor_id, len(items), len(real_items))
                return real_items

        except asyncio.TimeoutError:
            log.warning("Apify run timed out for %s after %ds", actor_id, timeout)
            return []
        except Exception as e:
            log.warning("Apify error for %s: %s", actor_id, e)
            return []

    async def _poll_run(self, session: aiohttp.ClientSession, run_id: str,
                        timeout: int) -> dict:
        """Poll a run until it finishes."""
        url = f"{self._base}/actor-runs/{run_id}"
        deadline = asyncio.get_running_loop().time() + timeout

        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(5)
            try:
                async with session.get(url, headers=self._headers(),
                                       timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = (await resp.json()).get("data", {})
                        if data.get("status") in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                            return data
            except Exception:
                pass

        return {"status": "TIMED-OUT"}

    async def _fetch_dataset(self, session: aiohttp.ClientSession,
                             dataset_id: str) -> list[dict]:
        """Fetch all items from a dataset."""
        max_results = cfg.get("apify.max_results", 50)
        url = f"{self._base}/datasets/{dataset_id}/items"
        params = {"limit": max_results}

        try:
            async with session.get(url, headers=self._headers(), params=params,
                                   timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    return await resp.json()
                return []
        except Exception as e:
            log.warning("Apify dataset fetch error: %s", e)
            return []


# Global singleton
apify = ApifyClient()
