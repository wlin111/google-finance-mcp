from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, cast

import pytest

from google_finance_mcp.client import ApiMapping, CachePolicy, DataServiceRequest
from google_finance_mcp.rpc_metadata import metadata_for_dataset
from google_finance_mcp import server

UTC = timezone.utc


async def _list_tools() -> list[Any]:
    list_tools = cast(Callable[[], Awaitable[list[Any]]], getattr(server, "list_tools"))
    return await list_tools()


async def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    call_tool = cast(Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]], getattr(server, "call_tool"))
    return await call_tool(name, arguments)


class FakeClient:
    async def get_mapping(self, *, page_path: str = "/finance/beta", force_refresh: bool = False) -> ApiMapping:
        return ApiMapping(
            source_url="https://www.google.com/finance/beta",
            source_path="/finance/beta",
            batchexecute_url="https://www.google.com/finance/beta/_/FinHubUi/data/batchexecute",
            init_data_keys=["ds:9"],
            requests={
                "ds:9": DataServiceRequest(
                    key="ds:9",
                    rpc_id="changedHash",
                    request=[[1], 6, 0],
                    metadata=metadata_for_dataset("ds:9", "changedHash", [[1], 6, 0]),
                )
            },
            cache_policy=CachePolicy(
                cache_control="max-age=60",
                expires=None,
                date=None,
                fetched_at=datetime(2026, 5, 26, tzinfo=UTC),
                expires_at=datetime(2026, 5, 26, 0, 1, tzinfo=UTC),
            ),
        )

    async def call_dataset(self, dataset_key: str, request_override=None, **kwargs):
        return {"dataset_key": dataset_key, "request_override": request_override}


class QuoteFakeClient(FakeClient):
    async def get_mapping(self, *, page_path: str = "/finance/beta", force_refresh: bool = False) -> ApiMapping:
        request = [["NVDA", "NASDAQ"]]
        return ApiMapping(
            source_url="https://www.google.com/finance/beta/quote/NVDA:NASDAQ",
            source_path="/finance/beta/quote/NVDA:NASDAQ",
            batchexecute_url="https://www.google.com/finance/beta/_/FinHubUi/data/batchexecute",
            init_data_keys=["ds:15"],
            requests={
                "ds:15": DataServiceRequest(
                    key="ds:15",
                    rpc_id="gXxkFd",
                    request=request,
                    metadata=metadata_for_dataset("ds:15", "gXxkFd", request, source_path="/finance/beta/quote/NVDA:NASDAQ"),
                )
            },
            cache_policy=CachePolicy(
                cache_control="max-age=60",
                expires=None,
                date=None,
                fetched_at=datetime(2026, 5, 26, tzinfo=UTC),
                expires_at=datetime(2026, 5, 26, 0, 1, tzinfo=UTC),
            ),
        )


@pytest.mark.anyio
async def test_dynamic_tool_uses_rpc_purpose(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "client", FakeClient())

    tools = await _list_tools()
    names = [tool.name for tool in tools]

    assert "google_finance_ds_9_market_movers" in names
    tool = next(tool for tool in tools if tool.name == "google_finance_ds_9_market_movers")
    description = str(tool.description or "")
    assert "Market movers" in description
    assert "Market mover lists by category, count, and offset." in description
    assert "changedHash" in description


@pytest.mark.anyio
async def test_dynamic_purpose_tool_calls_dataset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "client", FakeClient())

    result = await _call_tool("google_finance_ds_9_market_movers", {})

    assert result == {"dataset_key": "ds:9", "request_override": None}


@pytest.mark.anyio
async def test_key_statistics_dynamic_tool_description_mentions_best_effort_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "client", QuoteFakeClient())

    tools = await _list_tools()
    tool = next(tool for tool in tools if tool.name == "google_finance_ds_15_market_statistics")

    assert "52-week high, 52-week low, beta" in str(tool.description)


@pytest.mark.anyio
async def test_quote_dataset_tool_uses_quote_page_path(monkeypatch: pytest.MonkeyPatch) -> None:
    class RecordingClient:
        async def call_dataset(self, dataset_key: str, request_override=None, **kwargs):
            return {"dataset_key": dataset_key, "request_override": request_override, "kwargs": kwargs}

    monkeypatch.setattr(server, "client", RecordingClient())

    result = await _call_tool(
        "google_finance_call_quote_dataset",
        {"symbol": "nvda", "exchange": "nasdaq", "dataset_key": "ds:12"},
    )

    assert result["dataset_key"] == "ds:12"
    assert result["kwargs"]["page_path"] == "/finance/beta/quote/NVDA:NASDAQ"
    assert result["kwargs"]["source_path"] is None


@pytest.mark.anyio
async def test_call_rpc_defaults_to_classic_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    class RecordingClient:
        async def call_rpc(self, rpc_id: str, request, **kwargs):
            return {"rpc_id": rpc_id, "request": request, "kwargs": kwargs}

    monkeypatch.setattr(server, "client", RecordingClient())

    result = await _call_tool("google_finance_call_rpc", {"rpc_id": "xh8wxf", "request": [[[None, ["GOOGL", "NASDAQ"]]], 1]})

    assert result["kwargs"]["batchexecute_url"].endswith("/finance/_/GoogleFinanceUi/data/batchexecute")


@pytest.mark.anyio
async def test_call_rpc_can_use_finhub_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    class RecordingClient:
        async def call_rpc(self, rpc_id: str, request, **kwargs):
            return {"rpc_id": rpc_id, "request": request, "kwargs": kwargs}

    monkeypatch.setattr(server, "client", RecordingClient())

    result = await _call_tool(
        "google_finance_call_rpc",
        {"rpc_id": "gCvqoe", "request": [[[None, ["NVDA", "NASDAQ"]]], 1], "endpoint_family": "finhub"},
    )

    assert result["kwargs"]["batchexecute_url"].endswith("/finance/beta/_/FinHubUi/data/batchexecute")


@pytest.mark.anyio
async def test_quote_holdings_tool_uses_quote_holdings_client_method(monkeypatch: pytest.MonkeyPatch) -> None:
    class RecordingClient:
        async def call_quote_holdings(self, symbol: str, exchange: str, request_override=None, **kwargs):
            return {"symbol": symbol, "exchange": exchange, "request_override": request_override, "kwargs": kwargs}

    monkeypatch.setattr(server, "client", RecordingClient())

    result = await _call_tool("google_finance_get_quote_holdings", {"symbol": "tsla", "exchange": "nasdaq"})

    assert result["symbol"] == "tsla"
    assert result["exchange"] == "nasdaq"
    assert result["request_override"] is None
    assert result["kwargs"] == {"beta": True, "hl": "en", "gl": "us"}


@pytest.mark.anyio
async def test_quote_holdings_tool_is_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "client", FakeClient())

    tools = await _list_tools()

    assert "google_finance_get_quote_holdings" in [tool.name for tool in tools]
