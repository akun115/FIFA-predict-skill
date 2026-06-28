"""Small injectable JSON HTTP client."""

from __future__ import annotations

import json
import socket
from typing import Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class JsonHttpClient(Protocol):
    def get_json(
        self, url: str, *, headers: Mapping[str, str] | None = None
    ) -> object: ...


class HttpRequestError(RuntimeError):
    def __init__(self, category: str, status: int | None = None):
        self.category = category
        self.status = status
        suffix = f" ({status})" if status is not None else ""
        super().__init__(f"HTTP request failed: {category}{suffix}")


class UrllibJsonClient:
    def __init__(
        self,
        timeout_seconds: float = 15.0,
        opener: Callable | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self._opener = opener or urlopen

    def get_json(
        self, url: str, *, headers: Mapping[str, str] | None = None
    ) -> object:
        request_headers = {"User-Agent": "world-cup-oracle/2.1"}
        request_headers.update(headers or {})
        request = Request(url, headers=request_headers)
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as error:
            raise HttpRequestError("http", error.code) from error
        except (socket.timeout, TimeoutError) as error:
            raise HttpRequestError("timeout") from error
        except (URLError, OSError) as error:
            raise HttpRequestError("network") from error
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise HttpRequestError("invalid_json") from error
