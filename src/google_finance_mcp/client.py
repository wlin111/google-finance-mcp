from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode, urlsplit

import anyio
import httpx

from .financials import enrich_financials_result
from .key_statistics import enrich_key_statistics_result
from .quote_holdings import (
    QUOTE_HOLDINGS_MAX_PAGES,
    QUOTE_HOLDINGS_RPC_ID,
    QuoteHoldingsContext,
    enrich_quote_holdings_result,
    quote_holdings_continuation_request,
    quote_holdings_page_rows,
    quote_holdings_pagination_cursor,
    quote_holdings_request,
)
from .rpc_metadata import EndpointMetadata, LabeledDataContext, metadata_for_dataset

JSONValue = Any
UTC = timezone.utc

BETA_URL = "https://www.google.com/finance/beta"
DEFAULT_SOURCE_PATH = "/finance/beta"
CLASSIC_BATCHEXECUTE_URL = "https://www.google.com/finance/_/GoogleFinanceUi/data/batchexecute"
FINHUB_BATCHEXECUTE_URL = "https://www.google.com/finance/beta/_/FinHubUi/data/batchexecute"
BATCHEXECUTE_URL = CLASSIC_BATCHEXECUTE_URL

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",
    "Cookie": "CONSENT=YES+",
}


@dataclass(frozen=True)
class DataServiceRequest:
    key: str
    rpc_id: str
    request: JSONValue
    metadata: EndpointMetadata

    def as_dict(self) -> dict[str, JSONValue]:
        return {
            "key": self.key,
            "id": self.rpc_id,
            "purpose": self.metadata.purpose,
            "request_shape": self.metadata.request_shape,
            "request": self.request,
            "metadata": self.metadata.as_dict(),
        }


@dataclass(frozen=True)
class CachePolicy:
    cache_control: str | None
    expires: str | None
    date: str | None
    fetched_at: datetime
    expires_at: datetime

    @property
    def max_age_seconds(self) -> int:
        delta = self.expires_at - self.fetched_at
        return max(0, int(delta.total_seconds()))

    @property
    def is_stale(self) -> bool:
        return datetime.now(UTC) >= self.expires_at

    def as_dict(self) -> dict[str, JSONValue]:
        return {
            "cache_control": self.cache_control,
            "expires": self.expires,
            "date": self.date,
            "fetched_at": self.fetched_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "max_age_seconds": self.max_age_seconds,
            "is_stale": self.is_stale,
        }


@dataclass(frozen=True)
class ApiMapping:
    source_url: str
    source_path: str
    batchexecute_url: str
    init_data_keys: list[str]
    requests: dict[str, DataServiceRequest]
    cache_policy: CachePolicy

    def as_dict(self) -> dict[str, JSONValue]:
        return {
            "source_url": self.source_url,
            "source_path": self.source_path,
            "batchexecute_url": self.batchexecute_url,
            "init_data_keys": self.init_data_keys,
            "requests": {key: value.as_dict() for key, value in self.requests.items()},
            "cache": self.cache_policy.as_dict(),
        }


class MappingParseError(ValueError):
    """Raised when Google Finance page HTML does not contain a usable mapping."""


def _read_js_assignment(html: str, name: str) -> str:
    marker = re.search(rf"\bvar\s+{re.escape(name)}\s*=", html)
    if not marker:
        raise MappingParseError(f"Could not find var {name}")

    start = marker.end()
    quote: str | None = None
    escape = False
    depth = 0

    for pos in range(start, len(html)):
        char = html[pos]
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = None
            continue

        if char in ("'", '"'):
            quote = char
        elif char in "[{(":
            depth += 1
        elif char in "]})":
            depth -= 1
        elif char == ";" and depth == 0:
            return html[start:pos].strip()

    raise MappingParseError(f"Could not find end of var {name}")


_SINGLE_QUOTED = re.compile(r"'(?:\\.|[^'\\])*'")
_UNQUOTED_OBJECT_KEY = re.compile(r"([,{]\s*)([A-Za-z_$][A-Za-z0-9_$]*)(\s*:)")


def _js_literal_to_json(value: str) -> JSONValue:
    def replace_single_quote(match: re.Match[str]) -> str:
        return json.dumps(ast.literal_eval(match.group(0)))

    value = _SINGLE_QUOTED.sub(replace_single_quote, value)
    value = _UNQUOTED_OBJECT_KEY.sub(r'\1"\2"\3', value)
    return json.loads(value)


def parse_mapping_from_html(html: str, source_url: str, headers: httpx.Headers | dict[str, str]) -> ApiMapping:
    init_data_keys = _js_literal_to_json(_read_js_assignment(html, "AF_initDataKeys"))
    raw_requests = _js_literal_to_json(_read_js_assignment(html, "AF_dataServiceRequests"))
    source_path = _source_path_from_url(source_url)

    if not isinstance(init_data_keys, list) or not all(isinstance(key, str) for key in init_data_keys):
        raise MappingParseError("AF_initDataKeys was not a string array")
    if not isinstance(raw_requests, dict):
        raise MappingParseError("AF_dataServiceRequests was not an object")

    requests: dict[str, DataServiceRequest] = {}
    for key, value in raw_requests.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise MappingParseError(f"Invalid request entry for {key!r}")
        rpc_id = value.get("id")
        if not isinstance(rpc_id, str) or "request" not in value:
            raise MappingParseError(f"Invalid RPC request entry for {key!r}")
        requests[key] = DataServiceRequest(
            key=key,
            rpc_id=rpc_id,
            request=value["request"],
            metadata=metadata_for_dataset(key, rpc_id, value["request"], source_path=source_path),
        )

    return ApiMapping(
        source_url=source_url,
        source_path=source_path,
        batchexecute_url=_batchexecute_url_for_page(html, source_url),
        init_data_keys=init_data_keys,
        requests=requests,
        cache_policy=cache_policy_from_headers(headers),
    )


def _source_path_from_url(url: str) -> str:
    path = urlsplit(url).path
    return path or DEFAULT_SOURCE_PATH


def _batchexecute_url_for_page(html: str, source_url: str) -> str:
    parsed = urlsplit(source_url)
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "https://www.google.com"
    if "FinHubUi" in html or parsed.path.startswith("/finance/beta"):
        return FINHUB_BATCHEXECUTE_URL.replace("https://www.google.com", origin)
    return CLASSIC_BATCHEXECUTE_URL.replace("https://www.google.com", origin)


def _page_url(base_url: str, page_path: str) -> str:
    parsed = urlsplit(page_path)
    if parsed.scheme and parsed.netloc:
        return page_path
    if not page_path.startswith("/"):
        raise ValueError("page_path must be an absolute path or URL")
    base = urlsplit(base_url)
    return f"{base.scheme}://{base.netloc}{page_path}"


def cache_policy_from_headers(headers: httpx.Headers | dict[str, str]) -> CachePolicy:
    normalized = {key.lower(): value for key, value in dict(headers).items()}
    cache_control = normalized.get("cache-control")
    expires = normalized.get("expires")
    date = normalized.get("date")
    fetched_at = _parse_http_date(date) or datetime.now(UTC)
    expires_at = _compute_expires_at(fetched_at, cache_control, expires)

    return CachePolicy(
        cache_control=cache_control,
        expires=expires,
        date=date,
        fetched_at=fetched_at,
        expires_at=expires_at,
    )


def _parse_http_date(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _compute_expires_at(fetched_at: datetime, cache_control: str | None, expires: str | None) -> datetime:
    if cache_control:
        directives = {
            part.strip().split("=", 1)[0].lower(): part.strip().split("=", 1)[1].strip('"')
            if "=" in part
            else None
            for part in cache_control.split(",")
        }
        if any(directive in directives for directive in ("no-store", "no-cache", "must-revalidate")):
            return fetched_at
        max_age = directives.get("s-maxage") or directives.get("max-age")
        if max_age is not None:
            try:
                return fetched_at + timedelta(seconds=max(0, int(max_age)))
            except ValueError:
                pass

    parsed_expires = _parse_http_date(expires)
    if parsed_expires:
        return parsed_expires
    return fetched_at + timedelta(minutes=5)


def build_body(requests: list[dict[str, JSONValue]]) -> str:
    body = [
        [
            item["id"],
            json.dumps(item["request"], separators=(",", ":")),
            None,
            str(index + 1),
        ]
        for index, item in enumerate(requests)
    ]
    return urlencode({"f.req": json.dumps([body], separators=(",", ":"))})


def _request_fingerprint(request: JSONValue) -> str:
    serialized = json.dumps(request, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def parse_batchexecute_response(raw: str) -> list[dict[str, JSONValue]]:
    stripped = re.sub(r"^\)\]\}'\n\n?", "", raw)
    lines = stripped.splitlines()
    results: list[dict[str, JSONValue]] = []
    index = 0

    while index < len(lines):
        if re.fullmatch(r"[0-9a-fA-F ]+", lines[index].strip()) and index + 1 < len(lines):
            try:
                payload = json.loads(lines[index + 1])
            except json.JSONDecodeError:
                index += 2
                continue

            for entry in payload:
                if (
                    isinstance(entry, list)
                    and len(entry) >= 3
                    and entry[0] == "wrb.fr"
                    and isinstance(entry[1], str)
                    and isinstance(entry[2], str)
                ):
                    results.append({"id": entry[1], "data": json.loads(entry[2])})
            index += 2
        else:
            index += 1

    return results


class GoogleFinanceClient:
    def __init__(
        self,
        beta_url: str = BETA_URL,
        batchexecute_url: str = BATCHEXECUTE_URL,
        timeout: float = 20.0,
    ) -> None:
        self.beta_url = beta_url
        self.batchexecute_url = batchexecute_url
        self.timeout = timeout
        self._mappings: dict[str, ApiMapping] = {}
        self._lock = anyio.Lock()

    async def get_mapping(self, *, page_path: str = DEFAULT_SOURCE_PATH, force_refresh: bool = False) -> ApiMapping:
        async with self._lock:
            cache_key = _source_path_from_url(page_path) if urlsplit(page_path).scheme else page_path
            mapping = self._mappings.get(cache_key)
            if force_refresh or mapping is None or mapping.cache_policy.is_stale:
                mapping = await self.fetch_mapping(page_path=page_path)
                self._mappings[cache_key] = mapping
                self._mappings[mapping.source_path] = mapping
            return mapping

    async def fetch_mapping(self, *, page_path: str = DEFAULT_SOURCE_PATH) -> ApiMapping:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=DEFAULT_HEADERS) as client:
            response = await client.get(_page_url(self.beta_url, page_path))
            response.raise_for_status()
            return parse_mapping_from_html(str(response.text), str(response.url), response.headers)

    async def call_dataset(
        self,
        dataset_key: str,
        request_override: JSONValue | None = None,
        *,
        page_path: str = DEFAULT_SOURCE_PATH,
        source_path: str | None = None,
        hl: str = "en",
        gl: str = "us",
    ) -> dict[str, JSONValue]:
        mapping = await self.get_mapping(page_path=page_path)
        try:
            return await self._call_dataset_from_mapping(
                mapping,
                dataset_key,
                request_override,
                source_path=source_path,
                hl=hl,
                gl=gl,
            )
        except KeyError:
            mapping = await self.get_mapping(page_path=page_path, force_refresh=True)
            return await self._call_dataset_from_mapping(
                mapping,
                dataset_key,
                request_override,
                source_path=source_path,
                hl=hl,
                gl=gl,
            )

    async def _call_dataset_from_mapping(
        self,
        mapping: ApiMapping,
        dataset_key: str,
        request_override: JSONValue | None,
        *,
        source_path: str | None,
        hl: str,
        gl: str,
    ) -> dict[str, JSONValue]:
        request = mapping.requests.get(dataset_key)
        if request is None:
            raise KeyError(f"Unknown Google Finance dataset key for {mapping.source_path}: {dataset_key}")
        effective_request = request.request if request_override is None else request_override
        effective_source_path = source_path or mapping.source_path
        results = await self.batch_call(
            [{"id": request.rpc_id, "request": effective_request}],
            source_path=effective_source_path,
            batchexecute_url=mapping.batchexecute_url,
            hl=hl,
            gl=gl,
        )
        if not results:
            refreshed = await self.get_mapping(page_path=mapping.source_path, force_refresh=True)
            refreshed_request = refreshed.requests.get(dataset_key)
            if refreshed_request is None:
                raise KeyError(f"Unknown Google Finance dataset key for {refreshed.source_path}: {dataset_key}")
            mapping = refreshed
            request = refreshed_request
            effective_request = request.request if request_override is None else request_override
            effective_source_path = source_path or mapping.source_path
            results = await self.batch_call(
                [{"id": request.rpc_id, "request": effective_request}],
                source_path=effective_source_path,
                batchexecute_url=refreshed.batchexecute_url,
                hl=hl,
                gl=gl,
            )
        if not results:
            if request.metadata.purpose == "No-frame initialization endpoint":
                return {"id": request.rpc_id, "data": None, "no_frame": True}
            raise MappingParseError(
                f"Google Finance returned no batchexecute frame for {dataset_key} on {mapping.source_path}"
            )
        result = results[0]
        context = LabeledDataContext(
            dataset_key=dataset_key,
            page_path=mapping.source_path,
            source_path=effective_source_path,
            metadata=request.metadata,
            mapped_request=request.request,
            effective_request=effective_request,
            effective_request_fingerprint=_request_fingerprint(effective_request),
        )
        if request.metadata.purpose in {"Market statistics", "Key statistics / ratios"}:
            return enrich_key_statistics_result(result, context)
        if request.metadata.purpose == "Financials / estimates":
            return enrich_financials_result(result, context)
        return result

    async def call_rpc(
        self,
        rpc_id: str,
        request: JSONValue,
        *,
        source_path: str = DEFAULT_SOURCE_PATH,
        batchexecute_url: str | None = None,
        hl: str = "en",
        gl: str = "us",
    ) -> dict[str, JSONValue]:
        return (
            await self.batch_call(
                [{"id": rpc_id, "request": request}],
                source_path=source_path,
                batchexecute_url=batchexecute_url,
                hl=hl,
                gl=gl,
            )
        )[0]

    async def call_quote_holdings(
        self,
        symbol: str,
        exchange: str,
        request_override: JSONValue | None = None,
        *,
        beta: bool = True,
        hl: str = "en",
        gl: str = "us",
    ) -> dict[str, JSONValue]:
        source_path = f"/finance/{'beta/' if beta else ''}quote/{symbol.upper()}:{exchange.upper()}"
        request = quote_holdings_request(symbol, exchange) if request_override is None else request_override
        result = await self.call_rpc(
            QUOTE_HOLDINGS_RPC_ID,
            request,
            source_path=source_path,
            batchexecute_url=FINHUB_BATCHEXECUTE_URL,
            hl=hl,
            gl=gl,
        )
        if request_override is None:
            result = await self._paginate_quote_holdings(
                result,
                symbol=symbol,
                exchange=exchange,
                source_path=source_path,
                hl=hl,
                gl=gl,
            )
        context = QuoteHoldingsContext(
            source_path=source_path,
            rpc_id=QUOTE_HOLDINGS_RPC_ID,
            request=request,
            used_default_request=request_override is None,
        )
        return enrich_quote_holdings_result(result, context)

    async def _paginate_quote_holdings(
        self,
        result: dict[str, JSONValue],
        *,
        symbol: str,
        exchange: str,
        source_path: str,
        hl: str,
        gl: str,
    ) -> dict[str, JSONValue]:
        data = result.get("data")
        if not isinstance(data, list):
            return result

        aggregated_data = list(data)
        changed = False
        for continuation_type in (1, 2):
            rows = quote_holdings_page_rows(result, continuation_type=continuation_type)
            if rows is None:
                continue
            aggregated_rows = list(rows)
            cursor = quote_holdings_pagination_cursor(result, continuation_type=continuation_type)
            seen_cursors: set[str] = set()
            stream_changed = False
            for _ in range(QUOTE_HOLDINGS_MAX_PAGES):
                if not cursor or cursor in seen_cursors:
                    break
                seen_cursors.add(cursor)
                page = await self.call_rpc(
                    QUOTE_HOLDINGS_RPC_ID,
                    quote_holdings_continuation_request(
                        symbol,
                        exchange,
                        continuation_type=continuation_type,
                        cursor=cursor,
                    ),
                    source_path=source_path,
                    batchexecute_url=FINHUB_BATCHEXECUTE_URL,
                    hl=hl,
                    gl=gl,
                )
                page_rows = quote_holdings_page_rows(page, continuation_type=continuation_type)
                if page_rows is None:
                    break
                aggregated_rows.extend(page_rows)
                cursor = quote_holdings_pagination_cursor(page, continuation_type=continuation_type)
                stream_changed = True
                changed = True

            data_index = continuation_type - 1
            cursor_index = 6 if continuation_type == 1 else 7
            if stream_changed:
                aggregated_data[data_index] = aggregated_rows
                if cursor_index < len(aggregated_data):
                    aggregated_data[cursor_index] = cursor or None

        return {**result, "data": aggregated_data} if changed else result

    async def batch_call(
        self,
        requests: list[dict[str, JSONValue]],
        *,
        source_path: str = DEFAULT_SOURCE_PATH,
        batchexecute_url: str | None = None,
        hl: str = "en",
        gl: str = "us",
    ) -> list[dict[str, JSONValue]]:
        if not requests:
            raise ValueError("At least one RPC request is required")

        rpcids = ",".join(dict.fromkeys(str(item["id"]) for item in requests))
        query = urlencode({"rpcids": rpcids, "source-path": source_path, "hl": hl, "gl": gl, "rt": "c"})
        url = f"{batchexecute_url or self.batchexecute_url}?{query}"
        headers = {**DEFAULT_HEADERS, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"}

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.post(url, headers=headers, content=build_body(requests))
            response.raise_for_status()
            return parse_batchexecute_response(response.text)
