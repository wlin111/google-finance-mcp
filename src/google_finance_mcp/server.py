from __future__ import annotations

import json
import re
from typing import Any

import anyio
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool

from .client import CLASSIC_BATCHEXECUTE_URL, DEFAULT_SOURCE_PATH, FINHUB_BATCHEXECUTE_URL, GoogleFinanceClient
from .rpc_metadata import ARTICLE_REFERENCE_RPC_PURPOSES, EndpointMetadata

JSONValue = Any

client = GoogleFinanceClient()
server = Server(
    "google-finance-mcp",
    version="0.1.2",
    instructions=(
        "Fetches Google Finance beta page RPC mappings from AF_initDataKeys and "
        "AF_dataServiceRequests, honors the page cache headers, and calls the "
        "Google Finance batchexecute RPC endpoint."
    ),
)


def _schema(properties: dict[str, JSONValue], required: list[str] | None = None) -> dict[str, JSONValue]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


ANY_JSON_SCHEMA: dict[str, JSONValue] = {
    "description": "Any JSON value accepted by Google Finance for this RPC request.",
}

SOURCE_FIELDS: dict[str, JSONValue] = {
    "source_path": {
        "type": "string",
        "default": DEFAULT_SOURCE_PATH,
        "description": "Google Finance page path used in the batchexecute source-path query parameter.",
    },
    "hl": {"type": "string", "default": "en"},
    "gl": {"type": "string", "default": "us"},
}

ENDPOINT_FAMILY_FIELD: dict[str, JSONValue] = {
    "endpoint_family": {
        "type": "string",
        "enum": ["classic", "finhub"],
        "default": "classic",
        "description": "batchexecute endpoint family for explicit RPC calls: classic uses GoogleFinanceUi; finhub uses FinHubUi.",
    }
}

GENERIC_RPC_FIELDS: dict[str, JSONValue] = {
    **SOURCE_FIELDS,
    **ENDPOINT_FAMILY_FIELD,
}

OPTIONAL_SOURCE_FIELDS: dict[str, JSONValue] = {
    "source_path": {
        "type": "string",
        "description": "Override the batchexecute source-path query parameter; defaults to the fetched page path.",
    },
    "hl": {"type": "string", "default": "en"},
    "gl": {"type": "string", "default": "us"},
}

PAGE_FIELD: dict[str, JSONValue] = {
    "page_path": {
        "type": "string",
        "default": DEFAULT_SOURCE_PATH,
        "description": "Google Finance page path or URL to fetch AF_dataServiceRequests from.",
    }
}

QUOTE_FIELDS: dict[str, JSONValue] = {
    "symbol": {"type": "string", "description": "Ticker symbol, such as NVDA."},
    "exchange": {"type": "string", "description": "Exchange code, such as NASDAQ."},
    "beta": {
        "type": "boolean",
        "default": True,
        "description": "Use /finance/beta/quote when true; use /finance/quote when false.",
    },
}


GENERIC_TOOLS = [
    Tool(
        name="google_finance_refresh_mapping",
        description="Refresh or revalidate the Google Finance AF_dataServiceRequests mapping.",
        inputSchema=_schema(
            {
                "force": {
                    "type": "boolean",
                    "default": False,
                    "description": "Fetch the page even if the current cache entry is still fresh.",
                },
                **PAGE_FIELD,
            }
        ),
    ),
    Tool(
        name="google_finance_list_rpcs",
        description=(
            "List the current Google Finance beta AF_initDataKeys and AF_dataServiceRequests "
            "mapping, enriched with RPC purpose metadata where known."
        ),
        inputSchema=_schema({}),
    ),
    Tool(
        name="google_finance_list_known_rpc_purposes",
        description=(
            "List the reference RPC ID to purpose mapping from the reverse-engineering article. "
            "These IDs are examples only; live calls use the current id from AF_dataServiceRequests."
        ),
        inputSchema=_schema({}),
    ),
    Tool(
        name="google_finance_call_dataset",
        description="Call any Google Finance home-page dataset key advertised by AF_dataServiceRequests.",
        inputSchema=_schema(
            {
                "dataset_key": {
                    "type": "string",
                    "description": "Dataset key such as ds:0.",
                },
                "request_override": ANY_JSON_SCHEMA,
                **SOURCE_FIELDS,
            },
            required=["dataset_key"],
        ),
    ),
    Tool(
        name="google_finance_list_page_rpcs",
        description="List AF_initDataKeys and AF_dataServiceRequests for a Google Finance page path or URL.",
        inputSchema=_schema(PAGE_FIELD),
    ),
    Tool(
        name="google_finance_call_page_dataset",
        description="Call any dataset key advertised by a specific Google Finance page path or URL.",
        inputSchema=_schema(
            {
                **PAGE_FIELD,
                "dataset_key": {
                    "type": "string",
                    "description": "Dataset key such as ds:0.",
                },
                "request_override": ANY_JSON_SCHEMA,
                **OPTIONAL_SOURCE_FIELDS,
            },
            required=["dataset_key"],
        ),
    ),
    Tool(
        name="google_finance_list_quote_rpcs",
        description="List quote-page AF_initDataKeys and AF_dataServiceRequests for a ticker and exchange.",
        inputSchema=_schema(QUOTE_FIELDS, required=["symbol", "exchange"]),
    ),
    Tool(
        name="google_finance_call_quote_dataset",
        description="Call a quote-page dataset key for a ticker and exchange.",
        inputSchema=_schema(
            {
                **QUOTE_FIELDS,
                "dataset_key": {
                    "type": "string",
                    "description": "Quote-page dataset key such as ds:12.",
                },
                "request_override": ANY_JSON_SCHEMA,
                **OPTIONAL_SOURCE_FIELDS,
            },
            required=["symbol", "exchange", "dataset_key"],
        ),
    ),
    Tool(
        name="google_finance_get_quote_holdings",
        description=(
            "Call the Google Finance quote Holdings tab RPC for a ticker and exchange. "
            "Returns raw data plus best-effort labels for politician holdings, politician transactions, "
            "insider transactions, and pagination cursors. This RPC is not advertised in AF_dataServiceRequests."
        ),
        inputSchema=_schema(
            {
                **QUOTE_FIELDS,
                "request_override": ANY_JSON_SCHEMA,
                "hl": {"type": "string", "default": "en"},
                "gl": {"type": "string", "default": "us"},
            },
            required=["symbol", "exchange"],
        ),
    ),
    Tool(
        name="google_finance_call_rpc",
        description="Call a Google Finance RPC ID with an explicit JSON request payload.",
        inputSchema=_schema(
            {
                "rpc_id": {"type": "string", "description": "RPC ID such as YtbmEe."},
                "request": ANY_JSON_SCHEMA,
                **GENERIC_RPC_FIELDS,
            },
            required=["rpc_id", "request"],
        ),
    ),
    Tool(
        name="google_finance_batch_call",
        description="Call multiple Google Finance RPCs in one batchexecute request.",
        inputSchema=_schema(
            {
                "requests": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "request": ANY_JSON_SCHEMA,
                        },
                        "required": ["id", "request"],
                        "additionalProperties": False,
                    },
                },
                **GENERIC_RPC_FIELDS,
            },
            required=["requests"],
        ),
    ),
]


def quote_page_path(symbol: str, exchange: str, *, beta: bool = True) -> str:
    prefix = "/finance/beta/quote" if beta else "/finance/quote"
    return f"{prefix}/{symbol.upper()}:{exchange.upper()}"


def _optional_str(value: JSONValue) -> str | None:
    return None if value is None else str(value)


def _batchexecute_url_from_endpoint_family(value: JSONValue) -> str:
    endpoint_family = str(value or "classic")
    if endpoint_family == "finhub":
        return FINHUB_BATCHEXECUTE_URL
    if endpoint_family == "classic":
        return CLASSIC_BATCHEXECUTE_URL
    raise ValueError(f"Unknown endpoint_family: {endpoint_family}")


def dataset_tool_name(dataset_key: str, metadata: EndpointMetadata | None = None) -> str:
    ds_suffix = re.sub(r"[^A-Za-z0-9_-]+", "_", dataset_key).strip("_").lower()
    if metadata is None:
        return f"google_finance_{ds_suffix}"
    if metadata.source == "live-af_dataServiceRequests":
        return f"google_finance_{ds_suffix}"
    return f"google_finance_{ds_suffix}_{metadata.slug}"


def dataset_key_from_tool_name(tool_name: str) -> str | None:
    match = re.fullmatch(r"google_finance_ds_(\d+)(?:_[a-z0-9_]+)?", tool_name)
    if not match:
        return None
    return f"ds:{match.group(1)}"


def _dynamic_tool(dataset_key: str, rpc_id: str, request: JSONValue, metadata: EndpointMetadata) -> Tool:
    explanation = f" {metadata.description}" if metadata.description else ""
    return Tool(
        name=dataset_tool_name(dataset_key, metadata),
        description=(
            f"Call Google Finance {metadata.purpose} endpoint {dataset_key}.{explanation} "
            f"The current live id/hash from AF_dataServiceRequests is {rpc_id}. "
            f"Request shape: {metadata.request_shape}. "
            f"Default request: {json.dumps(request, separators=(',', ':'))}"
        ),
        inputSchema=_schema({"request_override": ANY_JSON_SCHEMA, **SOURCE_FIELDS}),
    )


@server.list_tools()
async def list_tools() -> list[Tool]:
    mapping = await client.get_mapping()
    dynamic_tools = [
        _dynamic_tool(dataset_key, request.rpc_id, request.request, request.metadata)
        for dataset_key, request in sorted(mapping.requests.items())
    ]
    return [*GENERIC_TOOLS, *dynamic_tools]


@server.call_tool(validate_input=True)
async def call_tool(name: str, arguments: dict[str, JSONValue]) -> dict[str, JSONValue]:
    if name == "google_finance_refresh_mapping":
        mapping = await client.get_mapping(
            page_path=str(arguments.get("page_path", DEFAULT_SOURCE_PATH)),
            force_refresh=bool(arguments.get("force", False)),
        )
        return mapping.as_dict()

    if name == "google_finance_list_rpcs":
        mapping = await client.get_mapping(page_path=DEFAULT_SOURCE_PATH)
        return mapping.as_dict()

    if name == "google_finance_list_known_rpc_purposes":
        return {"rpcs": ARTICLE_REFERENCE_RPC_PURPOSES}

    if name == "google_finance_call_dataset":
        return await client.call_dataset(
            str(arguments["dataset_key"]),
            arguments.get("request_override"),
            page_path=DEFAULT_SOURCE_PATH,
            source_path=str(arguments.get("source_path", DEFAULT_SOURCE_PATH)),
            hl=str(arguments.get("hl", "en")),
            gl=str(arguments.get("gl", "us")),
        )

    if name == "google_finance_list_page_rpcs":
        mapping = await client.get_mapping(page_path=str(arguments.get("page_path", DEFAULT_SOURCE_PATH)))
        return mapping.as_dict()

    if name == "google_finance_call_page_dataset":
        return await client.call_dataset(
            str(arguments["dataset_key"]),
            arguments.get("request_override"),
            page_path=str(arguments.get("page_path", DEFAULT_SOURCE_PATH)),
            source_path=_optional_str(arguments.get("source_path")),
            hl=str(arguments.get("hl", "en")),
            gl=str(arguments.get("gl", "us")),
        )

    if name == "google_finance_list_quote_rpcs":
        mapping = await client.get_mapping(
            page_path=quote_page_path(
                str(arguments["symbol"]),
                str(arguments["exchange"]),
                beta=bool(arguments.get("beta", True)),
            )
        )
        return mapping.as_dict()

    if name == "google_finance_call_quote_dataset":
        return await client.call_dataset(
            str(arguments["dataset_key"]),
            arguments.get("request_override"),
            page_path=quote_page_path(
                str(arguments["symbol"]),
                str(arguments["exchange"]),
                beta=bool(arguments.get("beta", True)),
            ),
            source_path=_optional_str(arguments.get("source_path")),
            hl=str(arguments.get("hl", "en")),
            gl=str(arguments.get("gl", "us")),
        )

    if name == "google_finance_get_quote_holdings":
        return await client.call_quote_holdings(
            str(arguments["symbol"]),
            str(arguments["exchange"]),
            arguments.get("request_override"),
            beta=bool(arguments.get("beta", True)),
            hl=str(arguments.get("hl", "en")),
            gl=str(arguments.get("gl", "us")),
        )

    if name == "google_finance_call_rpc":
        return await client.call_rpc(
            str(arguments["rpc_id"]),
            arguments["request"],
            source_path=str(arguments.get("source_path", DEFAULT_SOURCE_PATH)),
            batchexecute_url=_batchexecute_url_from_endpoint_family(arguments.get("endpoint_family")),
            hl=str(arguments.get("hl", "en")),
            gl=str(arguments.get("gl", "us")),
        )

    if name == "google_finance_batch_call":
        return {
            "results": await client.batch_call(
                list(arguments["requests"]),
                source_path=str(arguments.get("source_path", DEFAULT_SOURCE_PATH)),
                batchexecute_url=_batchexecute_url_from_endpoint_family(arguments.get("endpoint_family")),
                hl=str(arguments.get("hl", "en")),
                gl=str(arguments.get("gl", "us")),
            )
        }

    dataset_key = dataset_key_from_tool_name(name)
    if dataset_key:
        return await client.call_dataset(
            dataset_key,
            arguments.get("request_override"),
            page_path=DEFAULT_SOURCE_PATH,
            source_path=str(arguments.get("source_path", DEFAULT_SOURCE_PATH)),
            hl=str(arguments.get("hl", "en")),
            gl=str(arguments.get("gl", "us")),
        )

    raise KeyError(f"Unknown tool: {name}")


async def serve() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(NotificationOptions(tools_changed=True)),
        )


def main() -> None:
    anyio.run(serve)
