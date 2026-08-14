"""Shared HTTP fetch boundary: Result-typed, budget-counted, cached by URL hash."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from goldflow.domain.results import Err, InfrastructureError, Ok, Result


@dataclass(slots=True)
class HttpBudget:
    """Mutable counter owned by a single run (imperative shell state)."""

    max_requests: int
    used: int = 0

    def take(self) -> bool:
        if self.used >= self.max_requests:
            return False
        self.used += 1
        return True


@dataclass(slots=True)
class FetchClient:
    budget: HttpBudget
    cache_dir: Path | None = None
    timeout_s: float = 60.0
    _client: httpx.AsyncClient | None = field(default=None, repr=False)

    async def __aenter__(self) -> FetchClient:
        self._client = httpx.AsyncClient(
            timeout=self.timeout_s,
            headers={"User-Agent": "GoldFlow-Israel/0.1 (research; contact: local)"},
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._client is not None:
            await self._client.aclose()

    def _cache_path(self, key: str) -> Path | None:
        if self.cache_dir is None:
            return None
        digest = hashlib.sha256(key.encode()).hexdigest()
        return self.cache_dir / f"{digest}.json"

    async def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        cache: bool = True,
    ) -> Result[Any, InfrastructureError]:
        key = url + "?" + json.dumps(params or {}, sort_keys=True)
        cache_path = self._cache_path(key)
        if cache and cache_path is not None and cache_path.exists():
            return Ok(json.loads(cache_path.read_text()))
        if not self.budget.take():
            return Err(
                InfrastructureError(code="HTTP_BUDGET_EXCEEDED", message=f"budget spent: {url}")
            )
        if self._client is None:
            return Err(InfrastructureError(code="CLIENT_NOT_OPEN", message="use async with"))
        try:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            return Err(InfrastructureError(code="HTTP_ERROR", message=f"{url}: {exc}"))
        except json.JSONDecodeError as exc:
            return Err(InfrastructureError(code="BAD_JSON", message=f"{url}: {exc}"))
        if cache and cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(payload))
        return Ok(payload)

    async def post_json(
        self, url: str, *, data: dict[str, str], cache: bool = True
    ) -> Result[Any, InfrastructureError]:
        key = url + "!" + json.dumps(data, sort_keys=True)
        cache_path = self._cache_path(key)
        if cache and cache_path is not None and cache_path.exists():
            return Ok(json.loads(cache_path.read_text()))
        if not self.budget.take():
            return Err(
                InfrastructureError(code="HTTP_BUDGET_EXCEEDED", message=f"budget spent: {url}")
            )
        if self._client is None:
            return Err(InfrastructureError(code="CLIENT_NOT_OPEN", message="use async with"))
        try:
            response = await self._client.post(url, data=data)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            return Err(InfrastructureError(code="HTTP_ERROR", message=f"{url}: {exc}"))
        except json.JSONDecodeError as exc:
            return Err(InfrastructureError(code="BAD_JSON", message=f"{url}: {exc}"))
        if cache and cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(payload))
        return Ok(payload)
