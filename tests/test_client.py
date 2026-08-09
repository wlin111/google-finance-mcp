from __future__ import annotations

from datetime import datetime, timezone

import pytest

from google_finance_mcp.client import (
    ApiMapping,
    BATCHEXECUTE_URL,
    CLASSIC_BATCHEXECUTE_URL,
    CachePolicy,
    DataServiceRequest,
    FINHUB_BATCHEXECUTE_URL,
    GoogleFinanceClient,
    build_body,
    cache_policy_from_headers,
    parse_batchexecute_response,
    parse_mapping_from_html,
)
from google_finance_mcp.quote_holdings import quote_holdings_request
from google_finance_mcp.rpc_metadata import metadata_for_dataset

UTC = timezone.utc


def test_parse_mapping_from_google_finance_html() -> None:
    html = """
    <script>var AF_initDataKeys = ["ds:0","ds:1"];
    var AF_dataServiceRequests = {'ds:0' : {id:'hgueg',request:[1]},
    'ds:1' : {id:'vNewwe',request:[null,[null,1]]}};
    var AF_initDataChunkQueue = [];</script>
    """

    mapping = parse_mapping_from_html(
        html,
        "https://www.google.com/finance/beta",
        {"cache-control": "max-age=60", "date": "Tue, 26 May 2026 08:13:05 GMT"},
    )

    assert mapping.init_data_keys == ["ds:0", "ds:1"]
    assert mapping.source_path == "/finance/beta"
    assert mapping.batchexecute_url == FINHUB_BATCHEXECUTE_URL
    assert BATCHEXECUTE_URL == CLASSIC_BATCHEXECUTE_URL
    assert mapping.requests["ds:0"].rpc_id == "hgueg"
    assert mapping.requests["ds:0"].metadata.purpose == "Market overview quotes"
    assert mapping.requests["ds:1"].metadata.purpose == "Equity sectors"
    assert mapping.requests["ds:1"].request == [None, [None, 1]]
    assert mapping.cache_policy.max_age_seconds == 60


def test_parse_mapping_infers_purpose_without_stable_rpc_id() -> None:
    html = """
    <script>var AF_initDataKeys = ["ds:8"];
    var AF_dataServiceRequests = {'ds:8' : {id:'changedHash',request:[[1],6,0]}};
    var AF_initDataChunkQueue = [];</script>
    """

    mapping = parse_mapping_from_html(
        html,
        "https://www.google.com/finance/beta",
        {"cache-control": "max-age=60"},
    )

    assert mapping.requests["ds:8"].metadata.purpose == "Market movers"
    assert mapping.requests["ds:8"].metadata.current_rpc_id == "changedHash"
    assert mapping.requests["ds:8"].metadata.request_shape == "[[categories], count, offset]"


def test_runtime_beta_dataset_hint_covers_top_finance_articles() -> None:
    html = """
    <script>var AF_initDataKeys = ["ds:7"];
    var AF_dataServiceRequests = {'ds:7' : {id:'dcwbnc',request:[8]}};
    var AF_initDataChunkQueue = [];</script>
    """

    mapping = parse_mapping_from_html(
        html,
        "https://www.google.com/finance/beta",
        {"cache-control": "max-age=60"},
    )

    assert mapping.requests["ds:7"].metadata.purpose == "Top finance articles"
    assert mapping.requests["ds:7"].metadata.slug == "top_finance_articles"
    assert mapping.requests["ds:7"].metadata.source == "runtime-compiled-beta-dataset-key"


def test_beta_page_mapping_matches_current_dataset_keys() -> None:
    html = """
    <script>var AF_initDataKeys = ["ds:0","ds:1","ds:2","ds:3","ds:4","ds:5","ds:6","ds:7","ds:8","ds:9","ds:10","ds:11"];
    var AF_dataServiceRequests = {'ds:0' : {id:'U20P6c',request:[1]},
    'ds:1' : {id:'zOaLFb',request:[0,1]},
    'ds:2' : {id:'OsY2Qc',request:[null,[null,1]]},
    'ds:3' : {id:'HGhSgc',request:[1,0,2]},
    'ds:4' : {id:'HGhSgc',request:[3,1]},
    'ds:5' : {id:'U20P6c',request:[0]},
    'ds:6' : {id:'D8Aqrd',request:["market_summary",1]},
    'ds:7' : {id:'dcwbnc',request:[8]},
    'ds:8' : {id:'wdVNWe',request:[2,20]},
    'ds:9' : {id:'YtbmEe',request:[[2,3,1],4,0]},
    'ds:10' : {id:'RiQiSd',request:[null,null,25]},
    'ds:11' : {id:'HupQQe',request:[]}};
    var AF_initDataChunkQueue = [];</script>
    """

    mapping = parse_mapping_from_html(
        html,
        "https://www.google.com/finance/beta",
        {"cache-control": "max-age=60"},
    )

    assert mapping.requests["ds:0"].metadata.purpose == "Market overview quotes"
    assert mapping.requests["ds:1"].metadata.purpose == "No-frame initialization endpoint"
    assert mapping.requests["ds:2"].metadata.purpose == "Equity sectors"
    assert mapping.requests["ds:3"].metadata.purpose == "Earnings calendar"
    assert mapping.requests["ds:4"].metadata.purpose == "Earnings calendar secondary"
    assert mapping.requests["ds:5"].metadata.purpose == "Market overview charts"
    assert mapping.requests["ds:6"].metadata.purpose == "Market summary news clusters"
    assert mapping.requests["ds:7"].metadata.purpose == "Top finance articles"
    assert mapping.requests["ds:8"].metadata.purpose == "Market news"
    assert mapping.requests["ds:9"].metadata.purpose == "Market movers"
    assert mapping.requests["ds:10"].metadata.purpose == "Empty initialization endpoint"
    assert mapping.requests["ds:11"].metadata.purpose == "Empty initialization endpoint"


def test_quote_page_mapping_uses_quote_metadata() -> None:
    html = """
    <html><head><script nonce="abc">var AF_initDataKeys = ["ds:3","ds:4"];
    var AF_dataServiceRequests = {'ds:3' : {id:'gCvqoe',request:[[[null,["NVDA","NASDAQ"]]],1]},
    'ds:4' : {id:'JL8oKc',request:[[[null,["NVDA","NASDAQ"]]]]}};
    var AF_initDataChunkQueue = [];</script></head><body>FinHubUi</body></html>
    """

    mapping = parse_mapping_from_html(
        html,
        "https://www.google.com/finance/beta/quote/NVDA:NASDAQ",
        {"cache-control": "max-age=60"},
    )

    assert mapping.source_path == "/finance/beta/quote/NVDA:NASDAQ"
    assert mapping.requests["ds:3"].metadata.purpose == "Quote summary"
    assert mapping.requests["ds:3"].metadata.source == "runtime-compiled-rpc-id"
    assert mapping.requests["ds:3"].metadata.description == "Main quote payload for the requested security."
    assert mapping.requests["ds:4"].metadata.purpose == "Company profile"
    assert mapping.requests["ds:4"].metadata.description == "Long company/security profile and descriptive fields."


def test_quote_page_mapping_matches_current_dataset_keys() -> None:
    html = """
    <html><head><script nonce="abc">var AF_initDataKeys = ["ds:1","ds:2","ds:3","ds:4","ds:5","ds:6","ds:7","ds:8","ds:9","ds:10","ds:15","ds:17","ds:18","ds:20","ds:21","ds:22"];
    var AF_dataServiceRequests = {'ds:1' : {id:'zOaLFb',request:[0,1]},
    'ds:2' : {id:'OsY2Qc',request:[null,[null,1]]},
    'ds:3' : {id:'gCvqoe',request:[[[null,["NVDA","NASDAQ"]]],1]},
    'ds:4' : {id:'JL8oKc',request:[[[null,["NVDA","NASDAQ"]]]]},
    'ds:5' : {id:'smi6ye',request:[["NVDA","NASDAQ"]]},
    'ds:6' : {id:'SICF5d',request:[[null,["NVDA","NASDAQ"]],4]},
    'ds:7' : {id:'YTM9q',request:[[null,["NVDA","NASDAQ"]]]},
    'ds:8' : {id:'Kcy68c',request:[[[null,["NVDA","NASDAQ"]]],1]},
    'ds:9' : {id:'XxQsbd',request:[[[null,["NVDA","NASDAQ"]]],1]},
    'ds:10' : {id:'ADgT7b',request:[[[null,["NVDA","NASDAQ"]]],1,1,1]},
    'ds:15' : {id:'gXxkFd',request:[["NVDA","NASDAQ"]]},
    'ds:17' : {id:'dlNq8b',request:[[[null,["NVDA","NASDAQ"]]],1,1,1]},
    'ds:18' : {id:'Pr8h2e',request:[[[null,["NVDA","NASDAQ"]]],null,1]},
    'ds:20' : {id:'wdVNWe',request:[5,12,[[null,["NVDA","NASDAQ"]]]]},
    'ds:21' : {id:'RiQiSd',request:[null,null,25]},
    'ds:22' : {id:'HupQQe',request:[]}};
    var AF_initDataChunkQueue = [];</script></head><body>FinHubUi</body></html>
    """

    mapping = parse_mapping_from_html(
        html,
        "https://www.google.com/finance/beta/quote/NVDA:NASDAQ",
        {"cache-control": "max-age=60"},
    )

    assert mapping.requests["ds:1"].metadata.purpose == "No-frame initialization endpoint"
    assert mapping.requests["ds:2"].metadata.purpose == "Equity sectors"
    assert mapping.requests["ds:3"].metadata.purpose == "Quote summary"
    assert mapping.requests["ds:4"].metadata.purpose == "Company profile"
    assert mapping.requests["ds:5"].metadata.purpose == "Market statistics"
    assert mapping.requests["ds:5"].metadata.request_shape == '[["SYMBOL", "EXCHANGE"]]'
    assert mapping.requests["ds:6"].metadata.purpose == "Related securities"
    assert mapping.requests["ds:6"].metadata.request_shape == "[tuple, 4]"
    assert mapping.requests["ds:7"].metadata.purpose == "Analyst ratings and price targets"
    assert mapping.requests["ds:8"].metadata.purpose == "Earnings history and estimates"
    assert mapping.requests["ds:9"].metadata.purpose == "Earnings history and estimates alternate"
    assert mapping.requests["ds:10"].metadata.purpose == "Security overview card"
    assert mapping.requests["ds:15"].metadata.purpose == "Market statistics"
    assert mapping.requests["ds:17"].metadata.purpose == "Security overview card alternate"
    assert mapping.requests["ds:18"].metadata.purpose == "Financials / estimates"
    assert mapping.requests["ds:20"].metadata.purpose == "Security news feed"
    assert mapping.requests["ds:21"].metadata.purpose == "Empty initialization endpoint"
    assert mapping.requests["ds:21"].metadata.request_shape == "[null, null, 25]"
    assert mapping.requests["ds:22"].metadata.purpose == "Empty initialization endpoint"


def test_runtime_rpc_metadata_overrides_shifted_dataset_hint() -> None:
    html = """
    <html><head><script nonce="abc">var AF_initDataKeys = ["ds:2"];
    var AF_dataServiceRequests = {'ds:2' : {id:'Kcy68c',request:[[[null,["NVDA","NASDAQ"]]],1]}};
    var AF_initDataChunkQueue = [];</script></head><body>FinHubUi</body></html>
    """

    mapping = parse_mapping_from_html(
        html,
        "https://www.google.com/finance/beta/quote/NVDA:NASDAQ",
        {"cache-control": "max-age=60"},
    )

    assert mapping.requests["ds:2"].metadata.purpose == "Earnings history and estimates"
    assert mapping.requests["ds:2"].metadata.source == "runtime-compiled-rpc-id"
    assert "Live RPC id Kcy68c" in mapping.requests["ds:2"].metadata.justification[0]


def test_runtime_rpc_metadata_recognizes_current_earnings_fallback_rpc() -> None:
    metadata = metadata_for_dataset(
        "rpc:wKsYyb",
        "wKsYyb",
        [[None, ["PLTR", "NASDAQ"]]],
        source_path="/finance/beta/quote/PLTR:NASDAQ",
    )

    assert metadata.purpose == "Current earnings detail"
    assert metadata.source == "runtime-compiled-rpc-id"
    assert metadata.request_shape == "[tuple]"


def test_runtime_dataset_hint_survives_method_id_change_when_shape_still_matches() -> None:
    html = """
    <html><head><script nonce="abc">var AF_initDataKeys = ["ds:3"];
    var AF_dataServiceRequests = {'ds:3' : {id:'newQuoteId',request:[[[null,["NVDA","NASDAQ"]]],1]}};
    var AF_initDataChunkQueue = [];</script></head><body>FinHubUi</body></html>
    """

    mapping = parse_mapping_from_html(
        html,
        "https://www.google.com/finance/beta/quote/NVDA:NASDAQ",
        {"cache-control": "max-age=60"},
    )

    assert mapping.requests["ds:3"].metadata.purpose == "Quote summary"
    assert mapping.requests["ds:3"].metadata.source == "runtime-compiled-quote-dataset-key"
    assert "Live request matches [[tuple], 1]." in mapping.requests["ds:3"].metadata.justification


def test_classic_page_mapping_uses_google_finance_ui_endpoint() -> None:
    html = """
    <script>var AF_initDataKeys = ["ds:0"];
    var AF_dataServiceRequests = {'ds:0' : {id:'xh8wxf',request:[[[null,["GOOGL","NASDAQ"]]],1]}};
    var AF_initDataChunkQueue = [];</script>
    """

    mapping = parse_mapping_from_html(
        html,
        "https://www.google.com/finance/quote/GOOGL:NASDAQ",
        {"cache-control": "max-age=60"},
    )

    assert mapping.source_path == "/finance/quote/GOOGL:NASDAQ"
    assert mapping.batchexecute_url == CLASSIC_BATCHEXECUTE_URL


def test_no_cache_headers_expire_immediately() -> None:
    policy = cache_policy_from_headers(
        {
            "cache-control": "no-cache, no-store, max-age=0, must-revalidate",
            "date": "Tue, 26 May 2026 08:13:05 GMT",
        }
    )

    assert policy.fetched_at == datetime(2026, 5, 26, 8, 13, 5, tzinfo=UTC)
    assert policy.expires_at == policy.fetched_at
    assert policy.max_age_seconds == 0


def test_build_body_matches_batchexecute_shape() -> None:
    body = build_body([{"id": "abc", "request": [[None, ["GOOGL", "NASDAQ"]], 1]}])

    assert body.startswith("f.req=")
    assert "%22abc%22" in body
    assert "GOOGL" in body


def test_parse_batchexecute_response() -> None:
    raw = """)]}'

123
[["wrb.fr","xh8wxf","[[[\\"quote\\"]]]",null,null,null,"1"]]
"""

    assert parse_batchexecute_response(raw) == [{"id": "xh8wxf", "data": [[["quote"]]]}]


@pytest.mark.anyio
async def test_call_dataset_labels_key_statistics_with_valid_context() -> None:
    request = [["UUUU", "NYSEAMERICAN"]]
    mapping = ApiMapping(
        source_url="https://www.google.com/finance/beta/quote/UUUU:NYSEAMERICAN",
        source_path="/finance/beta/quote/UUUU:NYSEAMERICAN",
        batchexecute_url=FINHUB_BATCHEXECUTE_URL,
        init_data_keys=["ds:15"],
        requests={
            "ds:15": DataServiceRequest(
                key="ds:15",
                rpc_id="gXxkFd",
                request=request,
                metadata=metadata_for_dataset("ds:15", "gXxkFd", request, source_path="/finance/beta/quote/UUUU:NYSEAMERICAN"),
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
    data = [
        None,
        None,
        [["UUUU", "NYSEAMERICAN"], 0.625, 0.3125, 0.0625, 56.25, 0.4832, 0.3921, 0.1247, 35.85, 4.5, 11, 1.6842105263157894],
    ]

    class KeyStatisticsClient(GoogleFinanceClient):
        async def get_mapping(self, *, page_path: str = "/finance/beta", force_refresh: bool = False) -> ApiMapping:
            return mapping

        async def batch_call(self, requests, **kwargs):
            return [{"id": requests[0]["id"], "data": data}]

    enriched = await KeyStatisticsClient().call_dataset("ds:15")

    assert enriched["data"] is data
    labeled = enriched["labeled_data"]
    assert labeled["confidence"] == "best_effort"
    assert labeled["rows"][0]["symbol"] == "UUUU"
    assert labeled["rows"][0]["exchange"] == "NYSEAMERICAN"
    assert labeled["rows"][0]["values"]["primary_bucket_1_ratio"] == 0.625
    assert labeled["rows"][0]["groups"]["primary_distribution"]["bucket_ratio_sum"] == 1.0
    assert labeled["rows"][0]["raw_fields"][4]["raw_index"] == 4
    assert labeled["context"]["dataset_key"] == "ds:15"
    assert labeled["context"]["page_path"] == "/finance/beta/quote/UUUU:NYSEAMERICAN"
    assert labeled["context"]["source_path"] == "/finance/beta/quote/UUUU:NYSEAMERICAN"
    assert len(labeled["context"]["effective_request_fingerprint"]) == 64


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("data", "request_override"),
    [
        ([None, None, [["UUUU", "NYSEAMERICAN"], 0.625]], None),
        ([[None, None, [["UUUU", "NYSEAMERICAN"], 0.625, 0.3125, 0.0625, 56.25, 0.4832, 0.3921, 0.1247, 35.85, 4.5, 11, 1.6842105263157894]]], None),
        ([None, None, [["UUUU", "NYSEAMERICAN"], 0.625, 0.3125, 0.0625, 56.25, 0.4832, 0.3921, 0.1247, 35.85, 4.5, 11, 1.6842105263157894]], [["OTHER", "NASDAQ"]]),
    ],
)
async def test_key_statistics_schema_or_request_mismatch_preserves_raw_result(
    data: object, request_override: object | None
) -> None:
    request = [["UUUU", "NYSEAMERICAN"]]
    mapping = ApiMapping(
        source_url="https://www.google.com/finance/beta/quote/UUUU:NYSEAMERICAN",
        source_path="/finance/beta/quote/UUUU:NYSEAMERICAN",
        batchexecute_url=FINHUB_BATCHEXECUTE_URL,
        init_data_keys=["ds:15"],
        requests={
            "ds:15": DataServiceRequest(
                key="ds:15",
                rpc_id="gXxkFd",
                request=request,
                metadata=metadata_for_dataset("ds:15", "gXxkFd", request, source_path="/finance/beta/quote/UUUU:NYSEAMERICAN"),
            )
        },
        cache_policy=CachePolicy(None, None, None, datetime(2026, 5, 26, tzinfo=UTC), datetime(2026, 5, 26, 0, 1, tzinfo=UTC)),
    )
    raw_result: dict[str, object] = {"id": "gXxkFd", "data": data}

    class KeyStatisticsClient(GoogleFinanceClient):
        async def get_mapping(self, *, page_path: str = "/finance/beta", force_refresh: bool = False) -> ApiMapping:
            return mapping

        async def batch_call(self, requests, **kwargs):
            return [raw_result]

    result = await KeyStatisticsClient().call_dataset("ds:15", request_override)

    assert result is raw_result
    assert result["data"] is data
    assert "labeled_data" not in result


def test_quote_holdings_request_uses_holdings_tab_shape() -> None:
    assert quote_holdings_request("tsla", "nasdaq") == [[None, ["TSLA", "NASDAQ"]]]


@pytest.mark.anyio
async def test_call_quote_holdings_paginates_politician_sections() -> None:
    initial = {
        "id": "K5Y6Xb",
        "data": [[], [], None, None, [], None, "holdings-cursor-1", "transactions-cursor-1", None],
    }
    holdings_page = {
        "id": "K5Y6Xb",
        "data": [[["Gilbert Cisneros"]], None, None, None, None, None, None, None, None, None, "holdings-cursor-2"],
    }
    holdings_last_page = {
        "id": "K5Y6Xb",
        "data": [[["Later Holder"]], None, None, None, None, None, None, None, None, None, None],
    }
    transactions_page = {
        "id": "K5Y6Xb",
        "data": [None, [["Later Transaction"]], None, None, None, None, None, None],
    }

    class HoldingsClient(GoogleFinanceClient):
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def call_rpc(self, rpc_id: str, request, **kwargs):
            assert rpc_id == "K5Y6Xb"
            self.requests.append(request)
            if request == quote_holdings_request("TSLA", "NASDAQ"):
                return initial
            continuation_type = request[0][5][0]
            if continuation_type == 1 and request[0][-1] == "holdings-cursor-1":
                return holdings_page
            if continuation_type == 1:
                return holdings_last_page
            return transactions_page

    client = HoldingsClient()
    result = await client.call_quote_holdings("TSLA", "NASDAQ")

    assert result["data"][0] == [["Gilbert Cisneros"], ["Later Holder"]]
    assert result["data"][1] == [["Later Transaction"]]
    assert result["data"][6] is None
    assert result["data"][7] is None
    assert client.requests == [
        quote_holdings_request("TSLA", "NASDAQ"),
        [[None, ["TSLA", "NASDAQ"], None, None, None, [1], "holdings-cursor-1"]],
        [[None, ["TSLA", "NASDAQ"], None, None, None, [1], "holdings-cursor-2"]],
        [[None, ["TSLA", "NASDAQ"], None, None, None, [2], None, "transactions-cursor-1"]],
    ]


@pytest.mark.anyio
async def test_call_quote_holdings_labels_validated_tsla_slots() -> None:
    result = {
        "id": "K5Y6Xb",
        "data": [
            [
                [
                    "08d939a4-f63b-4a4b-b431-7096644081bb",
                    "spouse",
                    "TSLA",
                    "stock",
                    "TSLA",
                    2024,
                    "40",
                    "5",
                    "76",
                    "Ro Khanna",
                    True,
                    "ro",
                    "khanna",
                    "male",
                    "House",
                    "democrat",
                    "CA-17",
                ]
            ],
            [
                [
                    "739eca36-a8f3-4894-96b1-420354fe17b6",
                    "2026-03-13",
                    "TSLA",
                    "Sell",
                    "$15,001 - $50,000",
                    "2026-04-08",
                    "Hon. Gilbert Cisneros",
                    "Gilbert Cisneros",
                    "House",
                    "democrat",
                    "CA-31",
                    "undisclosed",
                ]
            ],
            None,
            None,
            [
                [
                    ["TSLA", "NASDAQ"],
                    0,
                    "Elon Musk",
                    "aef9cb66681469593c871ed3b677e62cfdcbb453",
                    "CEO, Director, Ten Percent Owner",
                    "51652_JIDHFHAGI_tsqr.jpg",
                    "4.9",
                    "Uninformative buy",
                    "NB",
                    [2026, 6, 17],
                    6685247561.82,
                    286428773,
                    "USD",
                    "http://sec.gov/example.xml",
                ]
            ],
            None,
            None,
            None,
            "insiders-cursor",
        ],
    }
    result["data"][0].append(
        [
            "b45d52cf-87d2-410f-a28b-19bf0b59974f",
            "self",
            "TSLA",
            "stock",
            "Tesla, Inc.",
            2025,
            "100",
            "250",
            "500",
            "Updated Holder",
            False,
            "updated",
            "holder",
            "unspecified",
            "Senate",
            "independent",
            "WA",
        ]
    )
    result["data"][1].append(
        [
            "ad0ad00f-5898-4864-9d55-f08de5b04bb0",
            "2025-01-02",
            "TSLA",
            "Purchase",
            "$1,001 - $15,000",
            "2025-01-31",
            "Rep. Updated Holder",
            "Updated Holder",
            "Senate",
            "independent",
            "WA",
            "self",
        ]
    )
    result["data"][4].append(
        [
            ["TSLA", "NASDAQ"],
            1,
            "Updated Insider",
            "b9ef3d0298d9f27e72e4962f0f9bc19d7606ef6f",
            "Director",
            "updated.jpg",
            "3.2",
            "Sale",
            "S",
            [2025, 1, 2],
            1500.5,
            42,
            "USD",
            "https://www.sec.gov/Archives/edgar/data/example.xml",
        ]
    )

    class HoldingsClient(GoogleFinanceClient):
        async def call_rpc(self, rpc_id: str, request, **kwargs):
            return result

    enriched = await HoldingsClient().call_quote_holdings("TSLA", "NASDAQ")

    assert enriched["data"] is result["data"]
    labeled = enriched["labeled_data"]
    assert labeled["schema_version"] == "google_finance_quote_holdings.v3"
    assert labeled["politician_holdings"][0]["values"] == {
        "disclosure": 2024,
        "owner": "spouse",
    }
    assert labeled["politician_holdings"][1]["values"] == {
        "disclosure": 2025,
        "owner": "self",
    }
    assert labeled["politician_transactions"][0]["values"] == {
        "issuer": "TSLA",
        "type": "Sell",
        "amount": "$15,001 - $50,000",
    }
    assert labeled["withheld_fields"]["politician_transactions"] == ["name", "filing_date"]
    insider = labeled["insider_transactions"][0]
    assert insider["values"] == {
        "type": "Uninformative buy",
        "date": [2026, 6, 17],
    }
    assert insider["raw_row"] is result["data"][4][0]
    assert labeled["insider_transactions"][1]["values"] == {
        "type": "Sale",
        "date": [2025, 1, 2],
    }
    assert labeled["insider_transactions"][1]["raw_row"] is result["data"][4][1]
    assert labeled["pagination"]["insider_transactions_cursor"] == "insiders-cursor"
    assert labeled["withheld_fields"]["insider_transactions"] == ["insider", "position", "shares", "amount"]

    result["data"][4][0][10], result["data"][4][0][11] = result["data"][4][0][11], result["data"][4][0][10]
    swapped_numeric = await HoldingsClient().call_quote_holdings("TSLA", "NASDAQ")
    swapped_insider = swapped_numeric["labeled_data"]["insider_transactions"][0]

    assert swapped_insider["values"] == {"type": "Uninformative buy", "date": [2026, 6, 17]}
    assert swapped_insider["raw_row"] is result["data"][4][0]

    result["data"][0][0][6], result["data"][0][0][8] = result["data"][0][0][8], result["data"][0][0][6]
    result["data"][4][0][2], result["data"][4][0][4] = result["data"][4][0][4], result["data"][4][0][2]
    swapped_unlabeled_slots = await HoldingsClient().call_quote_holdings("TSLA", "NASDAQ")

    assert swapped_unlabeled_slots["labeled_data"]["politician_holdings"][0]["values"] == {
        "disclosure": 2024,
        "owner": "spouse",
    }
    assert swapped_unlabeled_slots["labeled_data"]["insider_transactions"][0]["raw_row"] is result["data"][4][0]

    result["data"][0][0][1], result["data"][0][0][9] = result["data"][0][0][9], result["data"][0][0][1]
    owner_reordered = await HoldingsClient().call_quote_holdings("TSLA", "NASDAQ")
    result["data"][0][0][1], result["data"][0][0][9] = result["data"][0][0][9], result["data"][0][0][1]
    result["data"][1][0][3], result["data"][1][0][4] = result["data"][1][0][4], result["data"][1][0][3]
    transaction_reordered = await HoldingsClient().call_quote_holdings("TSLA", "NASDAQ")
    result["data"][1][0][3], result["data"][1][0][4] = result["data"][1][0][4], result["data"][1][0][3]
    result["data"][1][0][1], result["data"][1][0][5] = result["data"][1][0][5], result["data"][1][0][1]
    filing_dates_reordered = await HoldingsClient().call_quote_holdings("TSLA", "NASDAQ")
    result["data"][1][0][1], result["data"][1][0][5] = result["data"][1][0][5], result["data"][1][0][1]
    result["data"][4][0][2], result["data"][4][0][7] = result["data"][4][0][7], result["data"][4][0][2]
    insider_type_reordered = await HoldingsClient().call_quote_holdings("TSLA", "NASDAQ")
    result["data"][4][0][2], result["data"][4][0][7] = result["data"][4][0][7], result["data"][4][0][2]

    assert owner_reordered is result
    assert transaction_reordered is result
    assert filing_dates_reordered["labeled_data"]["politician_transactions"][0]["values"] == {
        "issuer": "TSLA",
        "type": "Sell",
        "amount": "$15,001 - $50,000",
    }
    assert insider_type_reordered is result

    other_ticker = await HoldingsClient().call_quote_holdings("NVDA", "NASDAQ")
    overridden = await HoldingsClient().call_quote_holdings(
        "TSLA", "NASDAQ", request_override=quote_holdings_request("TSLA", "NASDAQ")
    )
    result["data"][4][0][9] = "not-a-date"
    semantic_drift = await HoldingsClient().call_quote_holdings("TSLA", "NASDAQ")
    result["data"][2] = []
    structural_drift = await HoldingsClient().call_quote_holdings("TSLA", "NASDAQ")

    assert other_ticker is result
    assert overridden is result
    assert semantic_drift is result
    assert structural_drift is result
    assert "labeled_data" not in result


@pytest.mark.anyio
async def test_call_dataset_refreshes_mapping_when_cached_rpc_returns_no_frame() -> None:
    def mapping_for(rpc_id: str) -> ApiMapping:
        request = [1]
        return ApiMapping(
            source_url="https://www.google.com/finance/beta",
            source_path="/finance/beta",
            batchexecute_url=FINHUB_BATCHEXECUTE_URL,
            init_data_keys=["ds:0"],
            requests={
                "ds:0": DataServiceRequest(
                    key="ds:0",
                    rpc_id=rpc_id,
                    request=request,
                    metadata=metadata_for_dataset("ds:0", rpc_id, request),
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

    class RepairingClient(GoogleFinanceClient):
        def __init__(self) -> None:
            self.rpc_ids: list[str] = []

        async def get_mapping(self, *, page_path: str = "/finance/beta", force_refresh: bool = False) -> ApiMapping:
            return mapping_for("newRpc") if force_refresh else mapping_for("oldRpc")

        async def batch_call(self, requests, **kwargs):
            rpc_id = requests[0]["id"]
            self.rpc_ids.append(rpc_id)
            if rpc_id == "oldRpc":
                return []
            return [{"id": rpc_id, "data": [["ok"]]}]

    client = RepairingClient()

    result = await client.call_dataset("ds:0")

    assert result == {"id": "newRpc", "data": [["ok"]]}
    assert client.rpc_ids == ["oldRpc", "newRpc"]


@pytest.mark.anyio
async def test_no_frame_initialization_dataset_returns_structured_noop() -> None:
    request = [0, 1]
    mapping = ApiMapping(
        source_url="https://www.google.com/finance/beta",
        source_path="/finance/beta",
        batchexecute_url=FINHUB_BATCHEXECUTE_URL,
        init_data_keys=["ds:1"],
        requests={
            "ds:1": DataServiceRequest(
                key="ds:1",
                rpc_id="zOaLFb",
                request=request,
                metadata=metadata_for_dataset("ds:1", "zOaLFb", request),
            )
        },
        cache_policy=CachePolicy(None, None, None, datetime(2026, 5, 26, tzinfo=UTC), datetime(2026, 5, 26, 0, 1, tzinfo=UTC)),
    )

    class NoFrameClient(GoogleFinanceClient):
        async def get_mapping(self, *, page_path: str = "/finance/beta", force_refresh: bool = False) -> ApiMapping:
            return mapping

        async def batch_call(self, requests, **kwargs):
            return []

    result = await NoFrameClient().call_dataset("ds:1")

    assert result == {"id": "zOaLFb", "data": None, "no_frame": True}


@pytest.mark.anyio
async def test_call_quote_holdings_uses_finhub_rpc_and_enriches_result() -> None:
    class HoldingsClient(GoogleFinanceClient):
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def call_rpc(self, rpc_id: str, request, **kwargs):
            self.calls.append({"rpc_id": rpc_id, "request": request, "kwargs": kwargs})
            return {"id": rpc_id, "data": [[], [], None, None, [], None, None, None, None]}

    client = HoldingsClient()

    result = await client.call_quote_holdings("tsla", "nasdaq")

    assert result["id"] == "K5Y6Xb"
    assert "labeled_data" not in result
    assert client.calls[0]["rpc_id"] == "K5Y6Xb"
    assert client.calls[0]["request"] == [[None, ["TSLA", "NASDAQ"]]]
    kwargs = client.calls[0]["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["source_path"] == "/finance/beta/quote/TSLA:NASDAQ"
    assert kwargs["batchexecute_url"] == FINHUB_BATCHEXECUTE_URL
