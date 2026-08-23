from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

JSONValue = Any


@dataclass(frozen=True)
class EndpointMetadata:
    dataset_key: str
    current_rpc_id: str
    purpose: str
    request_shape: str
    slug: str
    source: str
    description: str = ""
    reference_rpc_ids: tuple[str, ...] = ()
    justification: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, JSONValue]:
        return {
            "dataset_key": self.dataset_key,
            "current_rpc_id": self.current_rpc_id,
            "purpose": self.purpose,
            "request_shape": self.request_shape,
            "slug": self.slug,
            "source": self.source,
            "description": self.description,
            "reference_rpc_ids": list(self.reference_rpc_ids),
            "justification": list(self.justification),
        }


@dataclass(frozen=True)
class LabeledDataContext:
    """Live provenance required before attaching positional-vector labels."""

    dataset_key: str
    page_path: str
    source_path: str
    metadata: EndpointMetadata
    mapped_request: JSONValue
    effective_request: JSONValue
    effective_request_fingerprint: str

    def validates_dataset(
        self, dataset_key: str, request_shape: str, purpose: str, *, require_runtime_rpc_id: bool = False
    ) -> bool:
        return (
            self.dataset_key == dataset_key
            and self.page_path == self.source_path
            and "/quote/" in self.page_path
            and self.metadata.dataset_key == dataset_key
            and self.metadata.purpose == purpose
            and self.metadata.request_shape == request_shape
            and self.metadata.source
            in ({"runtime-compiled-rpc-id"} if require_runtime_rpc_id else {"runtime-compiled-rpc-id", "runtime-compiled-quote-dataset-key"})
            and self.effective_request == self.mapped_request
            and _request_matches_shape(self.effective_request, request_shape)
        )

    def validates_result_id(self, result_id: object) -> bool:
        return result_id == self.metadata.current_rpc_id

    def quote_request_ticker(self) -> tuple[str, str] | None:
        request = self.effective_request
        if (
            not isinstance(request, list)
            or len(request) != 3
            or not isinstance(request[0], list)
            or len(request[0]) != 1
            or not isinstance(request[0][0], list)
            or len(request[0][0]) != 2
            or request[0][0][0] is not None
            or not isinstance(request[0][0][1], list)
            or len(request[0][0][1]) != 2
            or not all(isinstance(value, str) for value in request[0][0][1])
        ):
            return None
        return request[0][0][1][0], request[0][0][1][1]

    def quote_request_matches_page(self, ticker: tuple[str, str]) -> bool:
        marker = "/quote/"
        if marker not in self.page_path:
            return False
        route_ticker = self.page_path.split(marker, 1)[1].split("/", 1)[0].split(":", 1)
        return len(route_ticker) == 2 and tuple(value.casefold() for value in route_ticker) == tuple(
            value.casefold() for value in ticker
        )

    def as_labeled_data_dict(self) -> dict[str, JSONValue]:
        return {
            "dataset_key": self.dataset_key,
            "page_path": self.page_path,
            "source_path": self.source_path,
            "metadata_provenance": {
                "purpose": self.metadata.purpose,
                "source": self.metadata.source,
                "request_shape": self.metadata.request_shape,
                "reference_rpc_ids": list(self.metadata.reference_rpc_ids),
                "justification": list(self.metadata.justification),
            },
            "effective_request_fingerprint": self.effective_request_fingerprint,
        }


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


# Reference-only table from:
# https://scraper.run/blog/reverse-engineering-google-finance
#
# These short method IDs are not treated as stable. The live id/hash used for a
# call always comes from the current page's AF_dataServiceRequests entry.
ARTICLE_REFERENCE_RPC_PURPOSES: dict[str, dict[str, str]] = {
    "xh8wxf": {"purpose": "Quote", "request_shape": "[[tuple], 1] or [[tuple]]"},
    "HqGpWd": {"purpose": "Company info", "request_shape": "[[tuple]]"},
    "uwlMvd": {"purpose": "Classification", "request_shape": "[[tuple]]"},
    "Pr8h2e": {"purpose": "Financials / Estimates", "request_shape": "[[tuple]] or [[tuple], 1]"},
    "AiCwsd": {"purpose": "Chart", "request_shape": "[[tuple], mode]"},
    "nBEQBc": {"purpose": "News", "request_shape": "[type, limit, [tuple]]"},
    "o6pODe": {"purpose": "Analyst articles", "request_shape": "[tuple]"},
    "SICF5d": {"purpose": "Related stocks", "request_shape": "[tuple, 4] or [tuple, 18] or [tuple]"},
    "mKsvE": {"purpose": "Stock context", "request_shape": '["GOOGL:NASDAQ"]'},
    "Xhdx2e": {"purpose": "Market indices", "request_shape": "[null, 1]"},
    "YtbmEe": {"purpose": "Market movers", "request_shape": "[[categories], count, offset]"},
    "lvVhof": {"purpose": "Trending stocks", "request_shape": "[18]"},
    "JFUMjd": {"purpose": "Earnings calendar", "request_shape": "[]"},
    "XqaYg": {"purpose": "Category stocks", "request_shape": "[category, offset]"},
    "QKZUzd": {"purpose": "Top headline", "request_shape": "[1]"},
    "mysBRb": {"purpose": "Featured stocks", "request_shape": "[]"},
    "qt5Q2d": {"purpose": "Top stocks by metric", "request_shape": "[6, 1]"},
    "sy8gqe": {"purpose": "Category news", "request_shape": "[category, offset]"},
    "yYvDpf": {"purpose": "Unknown (empty)", "request_shape": "[tuple]"},
}


BETA_DATASET_PURPOSES: dict[str, tuple[str, str, str]] = {
    "ds:0": ("Market overview quotes", "[1]", "Symbol-independent market quote groups for the beta home page."),
    "ds:1": (
        "No-frame initialization endpoint",
        "[0, 1]",
        "Home-page initialization request observed in AF_dataServiceRequests; currently returns no wrb.fr frame.",
    ),
    "ds:2": ("Equity sectors", "[null, [null, 1]]", "Sector performance list."),
    "ds:3": ("Earnings calendar", "[1, 0, 2]", "Upcoming and recent earnings calendar entries."),
    "ds:4": ("Earnings calendar secondary", "[3, 1]", "Secondary earnings calendar request; currently returns little or no data."),
    "ds:5": ("Market overview charts", "[0]", "Market overview chart data with SVG sparklines."),
    "ds:6": ("Market summary news clusters", '["market_summary", 1]', "Clustered market summary news cards."),
    "ds:7": ("Top finance articles", "[8]", "Top finance article list."),
    "ds:8": ("Market news", "[2, 20]", "Market news feed."),
    "ds:9": ("Market movers", "[[categories], count, offset]", "Market mover lists by category, count, and offset."),
    "ds:10": ("Empty initialization endpoint", "[null, null, 25]", "Initialization request that returns an empty payload."),
    "ds:11": ("Empty initialization endpoint", "[]", "Initialization request that returns an empty payload."),
}


QUOTE_PAGE_DATASET_PURPOSES: dict[str, tuple[str, str, str]] = {
    "ds:0": ("Market overview quotes", "[1]", "Symbol-independent market quote groups."),
    "ds:1": (
        "No-frame initialization endpoint",
        "[0, 1]",
        "Quote-page initialization request observed in AF_dataServiceRequests; currently returns no wrb.fr frame.",
    ),
    "ds:2": ("Equity sectors", "[null, [null, 1]]", "Sector performance list."),
    "ds:3": ("Quote summary", "[[tuple], 1]", "Main quote payload for the requested security."),
    "ds:4": ("Company profile", "[[tuple]]", "Long company/security profile and descriptive fields."),
    "ds:5": (
        "Market statistics",
        '[["SYMBOL", "EXCHANGE"]]',
        "52-week high, 52-week low, beta, and related compact market-statistics values.",
    ),
    "ds:6": (
        "Related securities",
        "[tuple, 4]",
        "Peer and related quote cards for comparison.",
    ),
    "ds:7": (
        "Analyst ratings and price targets",
        "[tuple]",
        "Analyst consensus, price target range, and recent analyst actions.",
    ),
    "ds:8": (
        "Earnings history and estimates",
        "[[tuple], 1]",
        "Quarterly rows with actual and estimated revenue/EPS fields.",
    ),
    "ds:9": (
        "Earnings history and estimates alternate",
        "[[tuple], 1]",
        "Alternate quarterly rows with actual and estimated revenue/EPS fields.",
    ),
    "ds:10": (
        "Security overview card",
        "[[tuple], 1, 1, 1]",
        "Price, market cap, industry, logo, and summary quote fields.",
    ),
    "ds:11": ("Intraday chart points", "[[tuple], 1]", "Minute-level price points."),
    "ds:12": (
        "Intraday OHLCV chart",
        "[[tuple], 1, null, null, null, null, null, 1]",
        "Intraday candle rows with open, close, high, low, timestamp, and volume.",
    ),
    "ds:13": ("One-month chart points", "[[tuple], 3]", "Daily price points."),
    "ds:14": (
        "One-month OHLCV chart",
        "[[tuple], 3, null, null, null, null, null, 1]",
        "Daily candle rows with open, close, high, low, timestamp, and volume.",
    ),
    "ds:15": (
        "Market statistics",
        '[["SYMBOL", "EXCHANGE"]]',
        "52-week high, 52-week low, beta, and related compact market-statistics values.",
    ),
    "ds:16": ("Quote summary alternate", "[[tuple]]", "Quote payload without the trailing mode flag."),
    "ds:17": (
        "Security overview card alternate",
        "[[tuple], 1, 1, 1]",
        "Alternate price, market cap, industry, logo, and summary quote fields.",
    ),
    "ds:18": ("Financials / estimates", "[[tuple], null, 1]", "Financial statement and estimate arrays."),
    "ds:19": ("Market news feed", "[2, 12, [tuple]]", "General market or related news list."),
    "ds:20": ("Security news feed", "[5, 12, [tuple]]", "Company/security-specific article list."),
    "ds:21": ("Empty initialization endpoint", "[null, null, 25]", "Initialization request that returns an empty payload."),
    "ds:22": ("Empty initialization endpoint", "[]", "Initialization request that returns an empty payload."),
    "ds:23": ("Empty initialization endpoint", "[]", "Initialization request that returns an empty payload."),
}


QUOTE_RPC_PURPOSES: dict[str, list[tuple[str, str, str]]] = {
    "U20P6c": [("Market overview quotes", "[1]", "Symbol-independent market quote groups.")],
    "zOaLFb": [
        (
            "No-frame initialization endpoint",
            "[0, 1]",
            "Quote-page initialization request observed in AF_dataServiceRequests; currently returns no wrb.fr frame.",
        )
    ],
    "OsY2Qc": [("Equity sectors", "[null, [null, 1]]", "Sector performance list.")],
    "gCvqoe": [
        ("Quote summary", "[[tuple], 1]", "Main quote payload for the requested security."),
        ("Quote summary alternate", "[[tuple]]", "Quote payload without the trailing mode flag."),
    ],
    "JL8oKc": [("Company profile", "[[tuple]]", "Long company/security profile and descriptive fields.")],
    "SICF5d": [("Related securities", "[tuple, 4]", "Peer and related quote cards for comparison.")],
    "YTM9q": [
        ("Analyst ratings and price targets", "[tuple]", "Analyst consensus, price target range, and recent analyst actions.")
    ],
    "Kcy68c": [
        ("Earnings history and estimates", "[[tuple], 1]", "Quarterly rows with actual and estimated revenue/EPS fields.")
    ],
    "XxQsbd": [
        (
            "Earnings history and estimates alternate",
            "[[tuple], 1]",
            "Alternate quarterly rows with actual and estimated revenue/EPS fields.",
        )
    ],
    "ADgT7b": [
        ("Security overview card", "[[tuple], 1, 1, 1]", "Price, market cap, industry, logo, and summary quote fields.")
    ],
    "dlNq8b": [
        (
            "Security overview card alternate",
            "[[tuple], 1, 1, 1]",
            "Alternate price, market cap, industry, logo, and summary quote fields.",
        )
    ],
    "smi6ye": [
        (
            "Market statistics",
            '[["SYMBOL", "EXCHANGE"]]',
            "52-week high, 52-week low, beta, and related compact market-statistics values.",
        )
    ],
    "c2u4wc": [
        ("Intraday chart points", "[[tuple], 1]", "Minute-level price points."),
        (
            "Intraday OHLCV chart",
            "[[tuple], 1, null, null, null, null, null, 1]",
            "Intraday candle rows with open, close, high, low, timestamp, and volume.",
        ),
        ("One-month chart points", "[[tuple], 3]", "Daily price points."),
        (
            "One-month OHLCV chart",
            "[[tuple], 3, null, null, null, null, null, 1]",
            "Daily candle rows with open, close, high, low, timestamp, and volume.",
        ),
    ],
    "gXxkFd": [
        (
            "Market statistics",
            '[["SYMBOL", "EXCHANGE"]]',
            "52-week high, 52-week low, beta, and related compact market-statistics values.",
        )
    ],
    "Pr8h2e": [("Financials / estimates", "[[tuple], null, 1]", "Financial statement and estimate arrays.")],
    "kA4MVd": [
        ("Market news feed", "[2, 12, [tuple]]", "General market or related news list."),
    ],
    "wdVNWe": [
        ("Security news feed", "[5, 12, [tuple]]", "Company/security-specific article list."),
    ],
    "wKsYyb": [
        (
            "Current earnings detail",
            "[tuple]",
            "Current-quarter earnings row used by Woodstock jobs as an explicit RPC fallback when page datasets rotate.",
        )
    ],
    "RiQiSd": [
        ("Empty initialization endpoint", "[null, null, 25]", "Initialization request that returns an empty payload.")
    ],
    "ZdCSte": [
        ("Empty initialization endpoint", "[null, null, 25]", "Initialization request that returns an empty payload.")
    ],
    "X12h2b": [("Empty initialization endpoint", "[]", "Initialization request that returns an empty payload.")],
    "HupQQe": [("Empty initialization endpoint", "[]", "Initialization request that returns an empty payload.")],
    "stRW5d": [("Empty initialization endpoint", "[]", "Initialization request that returns an empty payload.")],
}


@dataclass(frozen=True)
class _MetadataCandidate:
    score: int
    metadata: EndpointMetadata


def metadata_for_dataset(
    dataset_key: str,
    current_rpc_id: str,
    request: JSONValue,
    *,
    source_path: str = "/finance/beta",
) -> EndpointMetadata:
    if "/quote/" in source_path:
        candidates = [
            *_rpc_candidates(dataset_key, current_rpc_id, request),
            *_dataset_hint_candidates(
                dataset_key,
                current_rpc_id,
                request,
                QUOTE_PAGE_DATASET_PURPOSES,
                source="runtime-compiled-quote-dataset-key",
                justification_prefix="quote-page dataset hint",
            ),
            *_shape_candidates(dataset_key, current_rpc_id, request, source="runtime-compiled-quote-request-shape"),
        ]
        if candidates:
            return max(candidates, key=lambda candidate: candidate.score).metadata

        return EndpointMetadata(
            dataset_key=dataset_key,
            current_rpc_id=current_rpc_id,
            purpose=f"Quote page dataset {dataset_key}",
            request_shape=_request_shape(request),
            slug=f"quote_page_{dataset_key.replace(':', '_')}",
            source="runtime-compiled-quote-unknown",
            description="Quote-page dataset discovered from AF_dataServiceRequests; purpose is not mapped yet.",
            justification=("No runtime RPC, dataset-key, or request-shape rule matched the live request.",),
        )

    candidates = [
        *_dataset_hint_candidates(
            dataset_key,
            current_rpc_id,
            request,
            BETA_DATASET_PURPOSES,
            source="runtime-compiled-beta-dataset-key",
            justification_prefix="beta home-page dataset hint",
        ),
        *_shape_candidates(dataset_key, current_rpc_id, request, source="runtime-compiled-request-shape"),
    ]
    if candidates:
        return max(candidates, key=lambda candidate: candidate.score).metadata

    return EndpointMetadata(
        dataset_key=dataset_key,
        current_rpc_id=current_rpc_id,
        purpose=f"Dataset {dataset_key}",
        request_shape="Discovered from AF_dataServiceRequests; purpose not inferred from request shape.",
        slug=dataset_key.replace(":", "_"),
        source="runtime-compiled-unknown",
        description="Dataset discovered from AF_dataServiceRequests; purpose is not mapped yet.",
        justification=("No runtime dataset-key or request-shape rule matched the live request.",),
    )


def _rpc_candidates(dataset_key: str, current_rpc_id: str, request: JSONValue) -> list[_MetadataCandidate]:
    candidates: list[_MetadataCandidate] = []
    for purpose, request_shape, description in QUOTE_RPC_PURPOSES.get(current_rpc_id, []):
        if _request_matches_shape(request, request_shape):
            candidates.append(
                _MetadataCandidate(
                    100,
                    _metadata(
                        dataset_key,
                        current_rpc_id,
                        purpose,
                        request_shape,
                        source="runtime-compiled-rpc-id",
                        description=description,
                        justification=(
                            f"Live RPC id {current_rpc_id} is a known Google Finance method for {purpose}.",
                            f"Live request matches {request_shape}.",
                        ),
                    ),
                )
            )
    return candidates


def _dataset_hint_candidates(
    dataset_key: str,
    current_rpc_id: str,
    request: JSONValue,
    hints: dict[str, tuple[str, str, str]],
    *,
    source: str,
    justification_prefix: str,
) -> list[_MetadataCandidate]:
    hint = hints.get(dataset_key)
    if not hint:
        return []

    purpose, request_shape, description = hint
    if not _request_matches_shape(request, request_shape):
        return []

    return [
        _MetadataCandidate(
            60,
            _metadata(
                dataset_key,
                current_rpc_id,
                purpose,
                request_shape,
                source=source,
                description=description,
                justification=(
                    f"Live {justification_prefix} {dataset_key} maps to {purpose}.",
                    f"Live request matches {request_shape}.",
                ),
            ),
        )
    ]


def _shape_candidates(dataset_key: str, current_rpc_id: str, request: JSONValue, *, source: str) -> list[_MetadataCandidate]:
    inferred = _infer_from_request(request)
    if not inferred:
        return []

    purpose, request_shape, reference_rpc_ids = inferred
    return [
        _MetadataCandidate(
            40,
            EndpointMetadata(
                dataset_key=dataset_key,
                current_rpc_id=current_rpc_id,
                purpose=purpose,
                request_shape=request_shape,
                slug=_slug(purpose),
                source=source,
                description="Purpose inferred from the live AF_dataServiceRequests request shape.",
                reference_rpc_ids=reference_rpc_ids,
                justification=(f"Live request matches generic shape {request_shape}.",),
            ),
        )
    ]


def _metadata(
    dataset_key: str,
    current_rpc_id: str,
    purpose: str,
    request_shape: str,
    *,
    source: str,
    description: str,
    justification: tuple[str, ...],
) -> EndpointMetadata:
    return EndpointMetadata(
        dataset_key=dataset_key,
        current_rpc_id=current_rpc_id,
        purpose=purpose,
        request_shape=request_shape,
        slug=_slug(purpose),
        source=source,
        description=description,
        reference_rpc_ids=_reference_rpc_ids_for_purpose(purpose),
        justification=justification,
    )


def _reference_rpc_ids_for_purpose(purpose: str) -> tuple[str, ...]:
    normalized = purpose.lower()
    return tuple(
        rpc_id for rpc_id, metadata in ARTICLE_REFERENCE_RPC_PURPOSES.items() if metadata["purpose"].lower() == normalized
    )


def _request_shape(request: JSONValue) -> str:
    try:
        return json.dumps(request, separators=(",", ":"))
    except TypeError:
        return "Discovered from AF_dataServiceRequests; request shape is not JSON serializable."


def _request_matches_shape(request: JSONValue, request_shape: str) -> bool:
    normalized = re.sub(r"\s+", "", request_shape)
    if normalized == "[1]":
        return request == [1]
    if normalized == "[0]":
        return request == [0]
    if normalized == "[18]":
        return request == [18]
    if normalized == "[1,0,2]":
        return request == [1, 0, 2]
    if normalized == "[3,1]":
        return request == [3, 1]
    if normalized == "[6,1]":
        return request == [6, 1]
    if normalized == "[8]":
        return request == [8]
    if normalized == "[2,20]":
        return request == [2, 20]
    if normalized == "[0,1]":
        return request == [0, 1]
    if normalized == "[null,[null,1]]":
        return request == [None, [None, 1]]
    if normalized == '["market_summary",1]':
        return request == ["market_summary", 1]
    if normalized == "[]":
        return request == []
    if normalized == "[null,null,25]":
        return request == [None, None, 25]
    if normalized == "[[categories],count,offset]":
        return _is_market_movers_request(request)
    if normalized == "[tuple]":
        return isinstance(request, list) and len(request) == 1 and _looks_like_tuple(request[0])
    if normalized == "[tuple,4]":
        return isinstance(request, list) and len(request) == 2 and _looks_like_tuple(request[0]) and request[1] == 4
    if normalized == "[[tuple]]":
        return _is_company_info_like_request(request)
    if normalized == "[[tuple],1]":
        return _is_quote_request(request) and len(request) == 2 and request[1] == 1
    if normalized == "[[tuple],null,1]":
        return (
            isinstance(request, list)
            and len(request) == 3
            and _looks_like_tuple_group(request[0])
            and request[1] is None
            and request[2] == 1
        )
    if normalized == "[[tuple],1,1,1]":
        return (
            isinstance(request, list)
            and len(request) == 4
            and _looks_like_tuple_group(request[0])
            and request[1:] == [1, 1, 1]
        )
    if normalized == "[[tuple],3]":
        return _is_chart_request(request) and len(request) == 2 and request[1] == 3
    if normalized == "[[tuple],1,null,null,null,null,null,1]":
        return _is_ohlcv_chart_request(request, mode=1)
    if normalized == "[[tuple],3,null,null,null,null,null,1]":
        return _is_ohlcv_chart_request(request, mode=3)
    if normalized == '[["SYMBOL","EXCHANGE"]]':
        return (
            isinstance(request, list)
            and len(request) == 1
            and isinstance(request[0], list)
            and len(request[0]) == 2
            and all(isinstance(item, str) for item in request[0])
        )
    if normalized == "[2,12,[tuple]]":
        return _is_news_request(request) and request[0] == 2 and request[1] == 12
    if normalized == "[5,12,[tuple]]":
        return _is_news_request(request) and request[0] == 5 and request[1] == 12
    return False


def _infer_from_request(request: JSONValue) -> tuple[str, str, tuple[str, ...]] | None:
    if request == [1]:
        return "Top headline", "[1]", ("QKZUzd",)
    if request == [18]:
        return "Trending stocks", "[18]", ("lvVhof",)
    if request == [None, 1]:
        return "Market indices", "[null, 1]", ("Xhdx2e",)
    if request == [6, 1]:
        return "Top stocks by metric", "[6, 1]", ("qt5Q2d",)
    if request == [None, [None, 1]]:
        return "Equity sectors", "[null, [null, 1]]", ()
    if request == [0, 1]:
        return "No-frame initialization endpoint", "[0, 1]", ()
    if _is_empty_initialization_request(request):
        return "Empty initialization endpoint", "[null, null, count]", ()
    if request == []:
        return "Empty request endpoint", "[]", ("JFUMjd", "mysBRb")
    if _is_market_movers_request(request):
        return "Market movers", "[[categories], count, offset]", ("YtbmEe",)
    if _is_market_summary_request(request):
        return "Market summary", '["market_summary", mode]', ()
    if _is_ticker_context_request(request):
        return "Stock context", '["SYMBOL:EXCHANGE"]', ("mKsvE",)
    if _is_quote_request(request):
        return "Quote", "[[tuple], 1] or [[tuple]]", ("xh8wxf",)
    if _is_chart_request(request):
        return "Chart", "[[tuple], mode]", ("AiCwsd",)
    if _is_company_info_like_request(request):
        return "Security tuple endpoint", "[[tuple]]", ("HqGpWd", "uwlMvd", "o6pODe", "yYvDpf")
    if _is_related_stocks_request(request):
        return "Related stocks", "[tuple, 4] or [tuple, 18] or [tuple]", ("SICF5d",)
    if _is_news_request(request):
        return "News", "[type, limit, [tuple]]", ("nBEQBc",)
    return None


def _is_market_movers_request(request: JSONValue) -> bool:
    return (
        isinstance(request, list)
        and len(request) == 3
        and isinstance(request[0], list)
        and all(isinstance(item, int) for item in request[0])
        and isinstance(request[1], int)
        and isinstance(request[2], int)
    )


def _is_market_summary_request(request: JSONValue) -> bool:
    return (
        isinstance(request, list)
        and len(request) == 2
        and request[0] == "market_summary"
        and isinstance(request[1], int)
    )


def _is_empty_initialization_request(request: JSONValue) -> bool:
    return (
        isinstance(request, list)
        and len(request) == 3
        and request[0] is None
        and request[1] is None
        and isinstance(request[2], int)
    )


def _is_ticker_context_request(request: JSONValue) -> bool:
    return (
        isinstance(request, list)
        and len(request) == 1
        and isinstance(request[0], str)
        and ":" in request[0]
    )


def _is_chart_request(request: JSONValue) -> bool:
    return isinstance(request, list) and len(request) == 2 and _looks_like_tuple_group(request[0]) and isinstance(request[1], int)


def _is_ohlcv_chart_request(request: JSONValue, *, mode: int) -> bool:
    return (
        isinstance(request, list)
        and len(request) == 8
        and _looks_like_tuple_group(request[0])
        and request[1] == mode
        and request[2:7] == [None, None, None, None, None]
        and request[7] == 1
    )


def _is_quote_request(request: JSONValue) -> bool:
    return (
        isinstance(request, list)
        and _looks_like_tuple_group(request[0] if request else None)
        and (len(request) == 1 or (len(request) == 2 and request[1] == 1))
    )


def _is_company_info_like_request(request: JSONValue) -> bool:
    return isinstance(request, list) and len(request) == 1 and _looks_like_tuple_group(request[0])


def _is_related_stocks_request(request: JSONValue) -> bool:
    return isinstance(request, list) and len(request) in (1, 2) and _looks_like_tuple(request[0]) and (
        len(request) == 1 or request[1] in {4, 18}
    )


def _is_news_request(request: JSONValue) -> bool:
    return (
        isinstance(request, list)
        and len(request) in (2, 3)
        and isinstance(request[0], int)
        and isinstance(request[1], int)
        and (len(request) == 2 or _looks_like_tuple_group(request[2]))
    )


def _looks_like_tuple_group(value: JSONValue) -> bool:
    return isinstance(value, list) and len(value) == 1 and _looks_like_tuple(value[0])


def _looks_like_tuple(value: JSONValue) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= 2
        and value[0] is None
        and isinstance(value[1], list)
    )
