# google-finance-mcp

<p align="center">
<img src="./docs/assets/lmstudio-google-finance-amzn-news-camera-hq.gif" alt="record" width="600">
</p>

Unofficial MCP server for Google Finance. It lets an MCP client run Google
Finance lookup tools from your own computer.

This project is not affiliated with, endorsed by, or sponsored by Google. It
does not grant rights to Google Finance data or any third-party market data.
Review the [legal, usage, and contribution policy](LEGAL.md) before using,
contributing to, packaging, publishing, or deploying this project.

Intended use is local, personal, manually configured, and user-initiated. This
wrapper behaves as an execution layer for endpoints advertised in the Google
Finance web page, plus narrowly documented render-time requests made by visible
page features during manual interaction; it is not intended to run as a hosted
API, shared proxy, crawler, scheduled data puller, data store, or redistribution
service.

## Quick install for Mac users

Use this section if you just want to install the Mac release and connect it to
your MCP client. You do not need to install Python for this path.

The Mac installer is currently built for Apple Silicon Macs only (`arm64`). If
you use an Intel Mac, skip to [Python install from source](#python-install-from-source).

### Step 1: Download and install from Terminal

Open **Terminal**, paste these commands, and press Enter:

```bash
VERSION=v0.1.2
curl -L -o google-finance-mcp-macos-arm64.pkg \
  "https://github.com/woodstock-tokyo/google-finance-mcp/releases/download/${VERSION}/google-finance-mcp-${VERSION}-macos-arm64.pkg"
sudo installer -pkg google-finance-mcp-macos-arm64.pkg -target /
```

Your Mac may ask for your password because the installer places the command at:

```text
/usr/local/bin/google-finance-mcp
```

Downloading with Terminal `curl` normally avoids the browser-added
`com.apple.quarantine` marker that can trigger the scary “Apple could not verify
this package is free of malware” warning for unsigned open-source packages.

### Step 2: Add it to your MCP client

In your MCP client configuration, use this command path:

```json
{
  "mcpServers": {
    "google-finance": {
      "command": "/usr/local/bin/google-finance-mcp",
      "args": []
    }
  }
}
```

Use the full path above. Desktop apps may not know where `/usr/local/bin` is if
you only write `google-finance-mcp`.

### Step 3: Start with these tools

After connecting your MCP client, try these first in the AI tools:<br/>
" Get latest news about NVDA. ”<br/>
" Get company infor for SPCX. '<br/>
" Get analysis of INTC, show me the target prices. "<br/>

## Other easy release downloads

GitHub releases include standalone binaries for macOS, Linux, and Windows. These
artifacts bundle Python and the project dependencies, so users do not need to
install Python first.

### macOS notes

Intel Mac users should use the Python/`uv` source install path.

### Linux

Download the Linux `.tar.gz`, extract it, and place the binary somewhere stable,
for example `/usr/local/bin`:

```bash
tar -xzf google-finance-mcp-v0.1.2-linux-x86_64.tar.gz
sudo install -m 755 google-finance-mcp /usr/local/bin/google-finance-mcp
```

Then configure the MCP client with the absolute path:

```json
{
  "mcpServers": {
    "google-finance": {
      "command": "/usr/local/bin/google-finance-mcp",
      "args": []
    }
  }
}
```

Linux release binaries are built on Ubuntu 22.04 for `x86_64`. Very old Linux
distributions with older glibc versions may need the Python source install path
instead.

### Windows

Download the Windows `.zip`, extract it to a stable folder, and point the MCP
client at the `.exe`:

```json
{
  "mcpServers": {
    "google-finance": {
      "command": "C:\\Users\\you\\Apps\\google-finance-mcp\\google-finance-mcp.exe",
      "args": []
    }
  }
}
```

Windows release builds are not Authenticode-signed yet. Windows SmartScreen may
show a “Windows protected your PC” warning on first run; choose More info, then
Run anyway if you trust the downloaded GitHub release artifact.

## Python install from source

Use this path if you are developing the project, using an Intel Mac, or cannot
use the standalone release files.

Requirements:

- Python 3.10 or newer. The upstream `mcp` Python SDK does not publish
  installable releases for Python 3.9, which is what many clean macOS installs
  expose as `/usr/bin/python3` after installing the Command Line Tools.
- Network access to `www.google.com` at runtime.
- An MCP client that can launch stdio servers.

If `python3 --version` reports Python 3.9, `python3 -m pip install ...` cannot
install this package because its `mcp>=1.0` dependency requires Python 3.10+.
The easiest path is to let `uv` use a managed interpreter instead of asking the
user to install Homebrew Python or a Python.org framework build:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
cd google-finance-mcp
uv tool install --python 3.11 .
```

This installs the `google-finance-mcp` console script as a user tool. `uv` may
download a private Python into its cache if macOS does not already have a
compatible interpreter; it does not replace the system `python3`.

There is not a supported install path that keeps using macOS's Python 3.9,
because the official MCP Python SDK does not publish Python 3.9-compatible
releases.

For local development from a checkout, use the same managed-Python approach:

```bash
cd google-finance-mcp
uv venv --python 3.11
uv pip install -e ".[dev]"
uv run pytest -q
```

Run the MCP server directly:

```bash
google-finance-mcp
```

The server uses MCP stdio transport. It does not print an HTTP URL or listen on
a port; the MCP client starts the command and communicates over stdin/stdout.

## Build package

This is a pure Python package, so there is no native compile step. To build a
wheel and source distribution:

```bash
python -m pip install build
python -m build
```

Install the built wheel:

```bash
python -m pip install dist/google_finance_mcp-0.1.2-py3-none-any.whl
```

You can also run the module entry point without relying on the console script:

```bash
python -m google_finance_mcp
```

To build release artifacts locally:

```bash
bash scripts/build-macos-release.sh
bash scripts/build-linux-release.sh
pwsh scripts/build-windows-release.ps1
```

The macOS build script creates an unsigned `pkgbuild` component package and
verifies its installer `Bom` before publishing the `.pkg` artifact. This avoids a
paid Apple Developer ID dependency, but it does not bypass Gatekeeper's trust
checks for downloaded installers.

Release preparation starts from the version in `pyproject.toml`. In the release
pull request, update the README download examples and refresh package metadata:

```bash
python scripts/update-readme-release-version.py v<version>
python -m build
```

When the release pull request lands on `master`,
`.github/workflows/prepare-release.yml` verifies those generated files are
already committed, creates tag `v<version>`, and publishes the GitHub Release for
that tag. The workflow does not push generated commits back to `master`, so it
works with branch protection rules that require changes to go through pull
requests.

GitHub release assets are then built by `.github/workflows/release.yml` for that
release tag. The prepare workflow dispatches the asset builder after publishing
the Release, and the builder uploads the generated files to that Release, so
direct download URLs such as
`https://github.com/woodstock-tokyo/google-finance-mcp/releases/download/v0.1.2/google-finance-mcp-v0.1.2-macos-arm64.pkg`
work with `curl`.

The workflow uploads:

- macOS Apple Silicon (`arm64`) `.pkg`, `.tar.gz`, and `.sha256` files.
- Linux `x86_64` `.tar.gz` and `.sha256` files.
- Windows `x86_64` `.zip` and `.sha256` files.

## What this server exposes

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

## MCP client configuration reference

For a local editable install, point your MCP client at the virtualenv console
script so it always uses this checkout:

```json
{
  "mcpServers": {
    "google-finance": {
      "command": "/absolute/path/to/google-finance-mcp/.venv/bin/google-finance-mcp",
      "args": []
    }
  }
}
```

For a globally installed wheel or package, the shorter command is enough in
terminal-launched clients:

```json
{
  "mcpServers": {
    "google-finance": {
      "command": "google-finance-mcp",
      "args": []
    }
  }
}
```

## Technical details

The server fetches Google Finance pages such as
`https://www.google.com/finance/beta` or
`https://www.google.com/finance/beta/quote/NVDA:NASDAQ`, extracts
`AF_initDataKeys` and `AF_dataServiceRequests`, and uses each page's cache
headers to decide when the internal RPC mapping must be refreshed.

### Mapping model

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

### Generated beta tools

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

### Quote-page dataset discovery

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
| `ds:4` | `smi6ye` | Unclassified quote dataset | `—` | Dataset key observed on the live page; purpose is not mapped. |
| `ds:5` | `SICF5d` | Related securities | `[tuple,4]` | Peer/related quote cards for comparison. |
| `ds:6` | `YTM9q` | Analyst ratings and price targets | `[tuple]` | Analyst consensus, price target range, and recent analyst actions. |
| `ds:7` | `Kcy68c` | Earnings history and estimates | `[[tuple],1]` | Quarterly rows with actual and estimated revenue/EPS fields. |
| `ds:8` | `XxQsbd` | Earnings history and estimates alternate | `[[tuple],1]` | Alternate quarterly rows with actual and estimated revenue/EPS fields. |
| `ds:9` | `ADgT7b` | Security overview card | `[[tuple],1,1,1]` | Price, market cap, industry, logo, and summary quote fields. |
| `ds:10` | `c2u4wc` | Intraday OHLCV chart | `[[tuple],1,null,null,null,null,null,1]` | Intraday candle rows with open, close, high, low, timestamp, and volume. |
| `ds:11` | `c2u4wc` | One-month chart points | `[[tuple],3]` | Daily price points. |
| `ds:12` | `c2u4wc` | One-month OHLCV chart | `[[tuple],3,null,null,null,null,null,1]` | Daily candle rows with open, close, high, low, timestamp, and volume. |
| `ds:13` | `gXxkFd` | Key statistics / ratios | `[["SYMBOL","EXCHANGE"]]` | Compact numeric ratio vector. Responses include `labeled_data` with best-effort structural labels and preserved raw indices. |
| `ds:14` | `gCvqoe` | Quote summary alternate | `[[tuple]]` | Quote payload without the trailing mode flag. |
| `ds:16` | `dlNq8b` | Security overview card alternate | `[[tuple],1,1,1]` | Alternate price, market cap, industry, logo, and summary quote fields. |
| `ds:17` | `kA4MVd` | Market news feed | `[2,12,[tuple]]` | General market or related news list. |
| `ds:18` | `kA4MVd` | Security news feed | `[5,12,[tuple]]` | Company/security-specific article list. |
| `ds:19` | `RiQiSd` | Empty initialization endpoint | `[null,null,25]` | Initialization request that returns an empty data array. |
| `ds:20` | `X12h2b` | Empty initialization endpoint | `[]` | Initialization request that returns an empty data array. |

### Quote Holdings tab RPC

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

### Endpoint handling

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

## Smoke test

A quick local import and live mapping check:

```bash
python - <<'PY'
import anyio
from google_finance_mcp.client import GoogleFinanceClient

async def main():
    client = GoogleFinanceClient()
    mapping = await client.get_mapping(force_refresh=True)
    print(mapping.source_path)
    print(sorted(mapping.requests))

anyio.run(main)
PY
```
