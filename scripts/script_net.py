from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_USER_AGENT = "bangumi-comment-skill/0.3 (+https://bangumi.tv/)"


class RequestError(RuntimeError):
    def __init__(self, message: str, *, url: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.status_code = status_code


@dataclass(slots=True)
class DiskCache:
    root: Path
    ttl_seconds: int = 24 * 3600

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, method: str, url: str, params: dict[str, Any] | None = None) -> Path:
        payload = json.dumps(
            {"method": method.upper(), "url": url, "params": params or {}},
            ensure_ascii=False,
            sort_keys=True,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    def load(self, method: str, url: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        path = self._path_for(method, url, params)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        timestamp = payload.get("time", 0)
        if self.ttl_seconds > 0 and time.time() - timestamp > self.ttl_seconds:
            return None
        return payload

    def save(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        status_code: int,
        headers: dict[str, Any],
        text: str,
    ) -> None:
        path = self._path_for(method, url, params)
        payload = {
            "time": time.time(),
            "status_code": status_code,
            "headers": headers,
            "text": text,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class RateLimiter:
    def __init__(self, min_interval: float = 0.8) -> None:
        self.min_interval = max(0.0, min_interval)
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            sleep_for = self._next_allowed - now
            if sleep_for > 0:
                time.sleep(sleep_for)
                now = time.monotonic()
            self._next_allowed = now + self.min_interval


class HttpClient:
    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: tuple[float, float] = (10.0, 30.0),
        min_interval: float = 0.8,
        cache_dir: Path | None = None,
        cache_ttl_seconds: int = 24 * 3600,
        logger: logging.Logger | None = None,
    ) -> None:
        self.timeout = timeout
        self.logger = logger or logging.getLogger("http")
        self.rate_limiter = RateLimiter(min_interval=min_interval)
        self.cache = DiskCache(cache_dir, cache_ttl_seconds) if cache_dir else None

        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def get_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: tuple[float, float] | None = None,
        allow_cache: bool = True,
        force_refresh: bool = False,
    ) -> str:
        cached = None
        if self.cache and allow_cache and not force_refresh:
            cached = self.cache.load("GET", url, params)
            if cached:
                self.logger.debug("cache hit: %s", url)
                return cached.get("text", "")

        self.rate_limiter.wait()
        try:
            response = self.session.get(url, params=params, timeout=timeout or self.timeout)
        except requests.RequestException as exc:
            raise RequestError(f"request failed: {exc}", url=url) from exc

        if response.status_code >= 400:
            raise RequestError(
                f"unexpected HTTP status {response.status_code}",
                url=url,
                status_code=response.status_code,
            )

        response.encoding = response.encoding or "utf-8"
        text = response.text
        if self.cache and allow_cache:
            self.cache.save(
                "GET",
                url,
                params=params,
                status_code=response.status_code,
                headers=dict(response.headers),
                text=text,
            )
        return text

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: tuple[float, float] | None = None,
        allow_cache: bool = True,
        force_refresh: bool = False,
    ) -> Any:
        text = self.get_text(
            url,
            params=params,
            timeout=timeout,
            allow_cache=allow_cache,
            force_refresh=force_refresh,
        )
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RequestError(f"invalid JSON response: {exc}", url=url) from exc
