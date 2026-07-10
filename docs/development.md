# Development

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

## Local test suite

From an editable checkout, install the development dependencies and run tests:

```bash
uv venv --python 3.11
uv pip install -e ".[dev]"
uv run pytest -q
```
