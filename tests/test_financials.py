from __future__ import annotations

from datetime import datetime, timezone

import pytest

from google_finance_mcp.client import (
    ApiMapping,
    CachePolicy,
    DataServiceRequest,
    FINHUB_BATCHEXECUTE_URL,
    GoogleFinanceClient,
)
from google_finance_mcp.rpc_metadata import metadata_for_dataset

UTC = timezone.utc
FINANCIALS_RPC_ID = "Pr8h2e"


def _metrics() -> list[object | None]:
    metrics: list[object | None] = [None] * 32
    metrics[0] = 1000
    metrics[1] = 120
    metrics[4] = 180
    metrics[16] = "USD"
    metrics[17] = "2025-12-31"
    metrics[22] = 500
    metrics[23] = 3000
    metrics[24] = 1400
    metrics[25] = 1700
    metrics[26] = 1300
    metrics[27] = 42
    metrics[28] = 250
    metrics[29] = -100
    metrics[30] = -50
    metrics[31] = 150
    return metrics


def _avgo_metrics() -> list[object | None]:
    metrics = _metrics()
    metrics[0] = 22187000000
    metrics[1] = 9310000000
    metrics[4] = 10869000000
    metrics[17] = [2026, 5, 3]
    metrics[22] = 19628000000
    metrics[23] = 179158000000
    metrics[24] = 42213000000
    metrics[25] = 87691000000
    metrics[26] = 91467000000
    metrics[27] = 4757580198
    metrics[28] = 10493000000
    metrics[29] = -208000000
    metrics[30] = -4831000000
    metrics[31] = 7640125000
    return metrics


def _nested_avgo_data(
    *, quarterly_metrics: list[object | None] | None = None, ticker: tuple[str, str] = ("AVGO", "NASDAQ"), quarter: int = 2
) -> list[object]:
    primary_quarterly_metrics = quarterly_metrics if quarterly_metrics is not None else _avgo_metrics()
    return [
        [
            [
                [[2026, quarter, primary_quarterly_metrics, _avgo_metrics()]],
                [[2025, _avgo_metrics(), _avgo_metrics()]],
                None,
                None,
                None,
                "/g/11cjwh6kxy",
                "Broadcom Inc",
                [ticker[0], ticker[1]],
            ]
        ]
    ]


def _financials_mapping(
    *, rpc_id: str = FINANCIALS_RPC_ID, symbol: str = "AVGO", exchange: str = "NASDAQ"
) -> ApiMapping:
    request = [[[None, [symbol, exchange]]], None, 1]
    return ApiMapping(
        source_url=f"https://www.google.com/finance/beta/quote/{symbol}:{exchange}",
        source_path=f"/finance/beta/quote/{symbol}:{exchange}",
        batchexecute_url=FINHUB_BATCHEXECUTE_URL,
        init_data_keys=["ds:21"],
        requests={
            "ds:21": DataServiceRequest(
                key="ds:21",
                rpc_id=rpc_id,
                request=request,
                metadata=metadata_for_dataset(
                    "ds:21", rpc_id, request, source_path=f"/finance/beta/quote/{symbol}:{exchange}"
                ),
            )
        },
        cache_policy=CachePolicy(
            cache_control="max-age=60",
            expires=None,
            date=None,
            fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
            expires_at=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
        ),
    )


class FinancialsClient(GoogleFinanceClient):
    def __init__(self, raw_data: object, *, rpc_id: str = FINANCIALS_RPC_ID, symbol: str = "AVGO") -> None:
        self.raw_data = raw_data
        self.rpc_id = rpc_id
        self.symbol = symbol

    async def get_mapping(self, *, page_path: str = "/finance/beta", force_refresh: bool = False) -> ApiMapping:
        return _financials_mapping(rpc_id=self.rpc_id, symbol=self.symbol)

    async def batch_call(self, requests, **kwargs):
        return [{"id": requests[0]["id"], "data": self.raw_data}]


@pytest.mark.anyio
async def test_call_dataset_leaves_simplified_financials_raw_only() -> None:
    annual_metrics = _metrics()
    quarterly_metrics = _metrics()
    quarterly_metrics[0] = 275
    data = [[[2025, annual_metrics]], [[2025, 4, quarterly_metrics]]]

    result = await FinancialsClient(data).call_dataset("ds:21")

    assert result == {"id": FINANCIALS_RPC_ID, "data": data}
    assert result["data"] is data
    assert "labeled_data" not in result


@pytest.mark.anyio
async def test_call_dataset_labels_nested_avgo_financial_records() -> None:
    quarterly_metrics = _avgo_metrics()
    annual_metrics = _avgo_metrics()
    annual_metrics[0] = 51600000000
    data = [
        [
            [
                [[2026, 2, quarterly_metrics, _avgo_metrics()]],
                [[2025, annual_metrics, _avgo_metrics()]],
                None,
                None,
                None,
                "/g/11cjwh6kxy",
                "Broadcom Inc",
                ["AVGO", "NASDAQ"],
            ]
        ]
    ]

    enriched = await FinancialsClient(data).call_dataset("ds:21")

    assert enriched["data"] is data
    labeled = enriched["labeled_data"]
    assert labeled["schema_version"] == "google_finance_quote_financials.avgo_ds16_2026_q2.v1"
    assert "Clients must consume raw data" in labeled["caveat"]
    assert labeled["quarterly"][0]["income_statement"]["revenue"] == 22187000000
    assert labeled["annual"][0]["income_statement"]["revenue"] == 51600000000
    assert labeled["quarterly"][0]["metadata"]["period_end_date"] == [2026, 5, 3]
    assert labeled["annual"][0]["metadata"]["period_end_date"] == [2026, 5, 3]


@pytest.mark.anyio
async def test_call_dataset_leaves_nested_financials_unlabeled_for_invalid_date() -> None:
    invalid_metrics = _avgo_metrics()
    invalid_metrics[17] = [2026, 2, 30]
    data = [
        [
            [
                [[2026, 2, invalid_metrics, _avgo_metrics()]],
                [[2025, _avgo_metrics(), _avgo_metrics()]],
                None,
                None,
                None,
                "/g/11cjwh6kxy",
                "Broadcom Inc",
                ["AVGO", "NASDAQ"],
            ]
        ]
    ]

    result = await FinancialsClient(data).call_dataset("ds:21")

    assert result == {"id": FINANCIALS_RPC_ID, "data": data}
    assert result["data"] is data
    assert "labeled_data" not in result


@pytest.mark.anyio
async def test_financials_unknown_rpc_metadata_preserves_nested_raw_result() -> None:
    data = _nested_avgo_data()

    result = await FinancialsClient(data, rpc_id="unknown-rpc").call_dataset("ds:21")

    assert result == {"id": "unknown-rpc", "data": data}
    assert result["data"] is data
    assert "labeled_data" not in result


@pytest.mark.anyio
async def test_financials_nested_ticker_mismatch_preserves_raw_result() -> None:
    data = _nested_avgo_data()

    result = await FinancialsClient(data, symbol="OTHER").call_dataset("ds:21")

    assert result == {"id": FINANCIALS_RPC_ID, "data": data}
    assert result["data"] is data
    assert "labeled_data" not in result


@pytest.mark.anyio
async def test_financials_other_ticker_preserves_raw_result() -> None:
    data = _nested_avgo_data(ticker=("OTHER", "NASDAQ"))

    result = await FinancialsClient(data, symbol="OTHER").call_dataset("ds:21")

    assert result == {"id": FINANCIALS_RPC_ID, "data": data}
    assert result["data"] is data
    assert "labeled_data" not in result


@pytest.mark.anyio
async def test_financials_other_avgo_period_preserves_raw_result() -> None:
    data = _nested_avgo_data(quarter=1)

    result = await FinancialsClient(data).call_dataset("ds:21")

    assert result == {"id": FINANCIALS_RPC_ID, "data": data}
    assert result["data"] is data
    assert "labeled_data" not in result


@pytest.mark.anyio
async def test_financials_avgo_signature_numeric_drift_preserves_raw_result() -> None:
    quarterly_metrics = _avgo_metrics()
    quarterly_metrics[22] = 19628000001
    data = _nested_avgo_data(quarterly_metrics=quarterly_metrics)

    result = await FinancialsClient(data).call_dataset("ds:21")

    assert result == {"id": FINANCIALS_RPC_ID, "data": data}
    assert result["data"] is data
    assert "labeled_data" not in result


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        "not a financial payload",
        [[2025, 4, "not metrics"]],
        [[[[2025, _metrics()]]], [[2025, 4, _metrics()]]],
        [[[2025, _metrics()[:31]]], []],
    ],
)
@pytest.mark.anyio
async def test_call_dataset_ignores_absent_or_malformed_financials(data: object) -> None:
    result = await FinancialsClient(data).call_dataset("ds:21")

    assert result == {"id": FINANCIALS_RPC_ID, "data": data}
    assert result["data"] is data
    assert "labeled_data" not in result


@pytest.mark.anyio
async def test_financials_request_override_mismatch_preserves_raw_result() -> None:
    data = [[[2025, _metrics()]], []]
    client = FinancialsClient(data)

    result = await client.call_dataset("ds:21", [[[None, ["OTHER", "NASDAQ"]]], None, 1])

    assert result["data"] is data
    assert "labeled_data" not in result


@pytest.mark.anyio
async def test_call_dataset_leaves_unpinned_simplified_financials_raw_only() -> None:
    metrics = _metrics()
    raw_data = [[[2025, metrics]], []]
    result = await FinancialsClient(raw_data).call_dataset("ds:21")

    assert result == {"id": FINANCIALS_RPC_ID, "data": raw_data}
    assert result["data"] is raw_data
    assert "labeled_data" not in result
