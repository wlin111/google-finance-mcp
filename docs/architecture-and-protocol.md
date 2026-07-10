# Architecture and protocol details

The server fetches Google Finance pages such as
`https://www.google.com/finance/beta` or
`https://www.google.com/finance/beta/quote/NVDA:NASDAQ`, extracts
`AF_initDataKeys` and `AF_dataServiceRequests`, and uses each page's cache
headers to decide when the internal RPC mapping must be refreshed.

## Mapping model

Google Finance embeds dataset entries like this in the beta page:

```js
var AF_initDataKeys = ["ds:0", "ds:1", "..."];
var AF_dataServiceRequests = {
  "ds:1": {id: "vNewwe", request: [null, [null, 1]]}
};
```

This server treats the `ds:N` key as the exported interface identity. The
`id` field is the current live method token/hash used in the `batchexecute`
POST body, and it may change over time. Do not build clients against a hardcoded
`id`; call by `ds:N` or by the generated `google_finance_ds_N_<purpose>` tool.

Metadata is compiled at runtime from the live `AF_dataServiceRequests` entry.
The compiler scores evidence from the current RPC id, the live request shape,
and the `ds:N` page hint, then records a `justification` array in each metadata
object. If Google shifts quote-page dataset numbers, RPC-id and request-shape
evidence can override stale `ds:N` assumptions without a code change.

Dataset calls also self-repair stale cached method tokens. If a cached dataset
call returns no `wrb.fr` batchexecute frame, the client force-refreshes the page
HTML, re-parses the current RPC id and endpoint, and retries the dataset once.

## Generated beta tools

These generated tools are for the Google Finance beta home page only
(`/finance/beta`). The meanings were verified against the live beta page on
2026-06-23. The `id` values below are examples from that run and can change; the
server refreshes them from `AF_dataServiceRequests`.

| Dataset | Example live id | Generated tool | Meaning | Default request |
| --- | --- | --- | --- | --- |
| `ds:0` | `hgueg` | `google_finance_ds_0_market_overview_quotes` | Market overview quotes | `[1]` |
| `ds:1` | `vNewwe` | `google_finance_ds_1_equity_sectors` | Equity sectors | `[null,[null,1]]` |
| `ds:2` | `HGhSgc` | `google_finance_ds_2_earnings_calendar` | Earnings calendar | `[1,0,2]` |
| `ds:3` | `HGhSgc` | `google_finance_ds_3_earnings_calendar_secondary` | Earnings calendar secondary, currently empty | `[3,1]` |
| `ds:4` | `hgueg` | `google_finance_ds_4_market_overview_charts` | Market overview charts with SVG sparklines | `[0]` |
| `ds:5` | `HacE5d` | `google_finance_ds_5_market_summary_news_clusters` | Market summary news clusters | `["market_summary",1]` |
| `ds:6` | `MlXU3e` | `google_finance_ds_6_top_finance_articles` | Top finance articles | `[8]` |
| `ds:7` | `kA4MVd` | `google_finance_ds_7_market_news` | Market news | `[2,20]` |
| `ds:8` | `YtbmEe` | `google_finance_ds_8_market_movers` | Market movers | `[[2,3,1],4,0]` |
| `ds:9` | `RiQiSd` | `google_finance_ds_9_empty_initialization_endpoint` | Empty initialization endpoint | `[null,null,25]` |
| `ds:10` | `X12h2b` | `google_finance_ds_10_empty_initialization_endpoint` | Empty initialization endpoint | `[]` |

The article's IDs such as `xh8wxf`, `HqGpWd`, and `YtbmEe` are kept only as
reference examples. Calls use the live `id` currently associated with each
`ds:N` entry.

## Quote-page dataset discovery

Classic quote URLs such as `/finance/quote/GOOGL:NASDAQ` are accepted by the
server and currently redirect to `/finance/beta/quote/GOOGL:NASDAQ`. That
redirected quote page advertises `ds:0` through `ds:20`. These are not generated
`google_finance_ds_N_<purpose>` tools; call them with
`google_finance_call_quote_dataset` or `google_finance_call_page_dataset`.

These meanings were discovered from the live quote page and response payloads on
2026-06-23 using `NVDA:NASDAQ`. The `id` values are examples from that run and
can change.

| Dataset | Example live id | Meaning | Default request shape | Notes |
| --- | --- | --- | --- | --- |
| `ds:0` | `hgueg` | Market overview quotes | `[1]` | Symbol-independent market quote groups. |
| `ds:1` | `vNewwe` | Equity sectors | `[null,[null,1]]` | Sector performance list. |
| `ds:2` | `gCvqoe` | Quote summary | `[[tuple],1]` | Main quote payload for the requested security. |
| `ds:3` | `JL8oKc` | Company profile | `[[tuple]]` | Long company/security profile and descriptive fields. |
| `ds:4` | `SICF5d` | Related securities | `[tuple,4]` | Peer/related quote cards for comparison. |
| `ds:5` | `YTM9q` | Analyst ratings and price targets | `[tuple]` | Analyst consensus, price target range, and recent analyst actions. |
| `ds:6` | `Kcy68c` | Earnings history and estimates | `[[tuple],1]` | Quarterly rows with actual and estimated revenue/EPS fields. |
| `ds:7` | `XxQsbd` | Earnings history and estimates alternate | `[[tuple],1]` | Alternate quarterly rows with actual and estimated revenue/EPS fields. |
| `ds:8` | `ADgT7b` | Security overview card | `[[tuple],1,1,1]` | Price, market cap, industry, logo, and summary quote fields. |
| `ds:9` | `c2u4wc` | Intraday chart points | `[[tuple],1]` | Minute-level price points. |
| `ds:10` | `c2u4wc` | Intraday OHLCV chart | `[[tuple],1,null,null,null,null,null,1]` | Intraday candle rows with open, close, high, low, timestamp, and volume. |
| `ds:11` | `c2u4wc` | One-month chart points | `[[tuple],3]` | Daily price points. |
| `ds:12` | `c2u4wc` | One-month OHLCV chart | `[[tuple],3,null,null,null,null,null,1]` | Daily candle rows with open, close, high, low, timestamp, and volume. |
| `ds:13` | `gXxkFd` | Key statistics / ratios | `[["SYMBOL","EXCHANGE"]]` | Compact numeric ratio vector. Responses include `labeled_data` with best-effort structural labels and preserved raw indices. |
| `ds:14` | `gCvqoe` | Quote summary alternate | `[[tuple]]` | Quote payload without the trailing mode flag. |
| `ds:15` | `dlNq8b` | Security overview card alternate | `[[tuple],1,1,1]` | Alternate price, market cap, industry, logo, and summary quote fields. |
| `ds:16` | `Pr8h2e` | Financials / estimates | `[[tuple],null,1]` | Financial statement and estimate arrays. |
| `ds:17` | `kA4MVd` | Market news feed | `[2,12,[tuple]]` | General market or related news list. |
| `ds:18` | `kA4MVd` | Security news feed | `[5,12,[tuple]]` | Company/security-specific article list. |
| `ds:19` | `RiQiSd` | Empty initialization endpoint | `[null,null,25]` | Initialization request that returns an empty data array. |
| `ds:20` | `X12h2b` | Empty initialization endpoint | `[]` | Initialization request that returns an empty data array. |

## Quote Holdings tab RPC

The quote page's Holdings tab is not present in the `AF_dataServiceRequests`
`ds:*` mapping. It is loaded by a render-time FinHub RPC observed from the live
page network traffic on 2026-07-02:

| RPC id | Tool | Default request shape | Notes |
| --- | --- | --- | --- |
| `K5Y6Xb` | `google_finance_get_quote_holdings` | `[[null,["SYMBOL","EXCHANGE"]]]` | Returns politician holdings, politician transactions, insider transactions, and pagination cursors. |

Because this method token is not advertised as a page dataset, treat it as more
volatile than `ds:N` calls. The tool preserves the raw batchexecute payload and
adds `labeled_data` with best-effort structural labels inferred from the rendered
Holdings tab and observed response rows. Insider transaction rows include fields
such as `insider_name`, `position`, `transaction_type`, `transaction_date`,
`shares`, `amount`, `currency`, and `sec_form4_url`.

## Endpoint handling

Classic explicit RPC calls use:

```text
https://www.google.com/finance/_/GoogleFinanceUi/data/batchexecute
```

Current beta pages advertise the FinHubUi endpoint, and dataset calls use the
endpoint associated with the page mapping:

```text
https://www.google.com/finance/beta/_/FinHubUi/data/batchexecute
```

Generated `google_finance_ds_N_<purpose>` tools are intentionally limited to the
beta home page. Other pages, including quote pages or classic `/finance/...`
paths, can still be inspected with `google_finance_list_page_rpcs` or
`google_finance_list_quote_rpcs` and called with
`google_finance_call_page_dataset`, `google_finance_call_quote_dataset`,
`google_finance_call_rpc`, or `google_finance_batch_call`.

The request body is a URL-encoded `f.req` value containing batched RPC calls.
Responses are Google batchexecute frames; the server strips the anti-JSON prefix,
decodes `wrb.fr` frames, and returns structured JSON.

Generic `google_finance_call_rpc` and `google_finance_batch_call` accept an
explicit `source_path` plus `endpoint_family: "classic" | "finhub"`. Dataset
calls use the fetched page path and endpoint by default, so the home page and
quote pages can both define `ds:0`, `ds:1`, and so on without sharing meaning.
