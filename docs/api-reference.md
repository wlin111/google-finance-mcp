# Tool reference

This server exposes a small set of stable MCP tools plus dynamic tools generated
from the current Google Finance beta home-page mapping.

- `google_finance_list_rpcs`: return the current `AF_initDataKeys` and
  `AF_dataServiceRequests` mapping, enriched with inferred purpose metadata.
- `google_finance_list_known_rpc_purposes`: return the article's reference RPC
  ID to purpose table. These IDs are not treated as stable.
- `google_finance_refresh_mapping`: force or revalidate a page mapping cache.
- `google_finance_call_dataset`: call any advertised home-page `ds:*` dataset
  by key.
- `google_finance_list_page_rpcs`: return the current mapping for any Google
  Finance page path or URL.
- `google_finance_call_page_dataset`: call any advertised `ds:*` dataset from a
  specific Google Finance page path or URL.
- `google_finance_list_quote_rpcs`: return the quote-page mapping for a ticker
  and exchange. `/finance/quote/...` is also accepted and currently redirects to
  `/finance/beta/quote/...`.
- `google_finance_call_quote_dataset`: call any advertised quote-page `ds:*`
  dataset for a ticker and exchange.
- `google_finance_get_quote_holdings`: call the quote Holdings tab RPC for a
  ticker and exchange. This RPC is not advertised in `AF_dataServiceRequests`; it
  returns raw data plus best-effort labels for politician holdings, politician
  transactions, insider transactions, and pagination cursors.
- `google_finance_call_rpc`: call a single RPC ID with an explicit request.
  Explicit RPC calls default to the classic `GoogleFinanceUi` endpoint and can
  opt into `endpoint_family: "finhub"`.
- `google_finance_batch_call`: call multiple RPC IDs in one batchexecute POST.
  Explicit batch calls use the same `endpoint_family` option.
- `google_finance_ds_N_<purpose>`: dynamic tools generated only from the
  current `/finance/beta` home-page mapping, one for each advertised beta
  dataset key. The `ds:N` key is the exported interface identity; the current
  live `id`/hash is read from `AF_dataServiceRequests` whenever the mapping is
  refreshed. Classic and quote-page endpoints are not exposed as generated
  tools; use the page/quote dataset tools or explicit RPC tools for those.
