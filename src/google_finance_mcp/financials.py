from __future__ import annotations

from datetime import date
from typing import Any

from .rpc_metadata import LabeledDataContext

JSONValue = Any

FINANCIALS_SCHEMA_VERSION = "google_finance_quote_financials.avgo_ds16_2026_q2.v1"

# Captured from the live AVGO ds:16 response on the Financials quote page.
# This narrow, versioned marker guards the confirmed numeric slots against
# same-type positional drift without assigning labels to any new raw fields.
AVGO_DS16_SIGNATURE_VERSION = "avgo-ds16-2026-q2.v1"
_AVGO_DS16_SIGNATURE: dict[int, int] = {
    0: 22187000000,
    1: 9310000000,
    4: 10869000000,
    22: 19628000000,
    23: 179158000000,
    24: 42213000000,
    25: 87691000000,
    26: 91467000000,
    27: 4757580198,
    28: 10493000000,
    29: -208000000,
    30: -4831000000,
    31: 7640125000,
}

FINANCIALS_FIELD_GROUPS: tuple[tuple[str, tuple[tuple[str, int], ...]], ...] = (
    (
        "income_statement",
        (
            ("revenue", 0),
            ("net_income", 1),
            ("operating_income", 4),
        ),
    ),
    (
        "balance_sheet",
        (
            ("cash_and_equivalents", 22),
            ("total_assets", 23),
            ("total_current_assets", 24),
            ("total_equity", 25),
            ("total_liabilities", 26),
            ("shares_outstanding", 27),
        ),
    ),
    (
        "cash_flow",
        (
            ("cash_from_operations", 28),
            ("cash_from_investing", 29),
            ("cash_from_financing", 30),
            ("free_cash_flow", 31),
        ),
    ),
    (
        "metadata",
        (
            ("currency_code", 16),
            ("period_end_date", 17),
        ),
    ),
)


def enrich_financials_result(result: dict[str, JSONValue], context: LabeledDataContext | None = None) -> dict[str, JSONValue]:
    """Attach confirmed labels to quote-page financial statement rows.

    Google Finance returns these financial rows as positional vectors. Only
    positions directly verified against the rendered Financials tab are labeled.
    """

    if (
        context is None
        or not context.validates_dataset(
            context.dataset_key, "[[tuple], null, 1]", "Financials / estimates", require_runtime_rpc_id=True
        )
        or not context.validates_result_id(result.get("id"))
    ):
        return result

    expected_ticker = context.quote_request_ticker()
    if expected_ticker is None or not context.quote_request_matches_page(expected_ticker):
        return result

    annual_rows, quarterly_rows = _extract_nested_company_period_rows(result.get("data"), expected_ticker)
    if not annual_rows and not quarterly_rows:
        return result

    return {
        **result,
        "labeled_data": {
            "schema_version": FINANCIALS_SCHEMA_VERSION,
            "confidence": "confirmed_fields_only",
            "caveat": (
                "Labels are pinned to the independently validated AVGO:NASDAQ Q2 FY2026 ds:16 sample "
                f"({AVGO_DS16_SIGNATURE_VERSION}). Clients must consume raw data for every other response."
            ),
            "context": context.as_labeled_data_dict(),
            "annual": [_label_annual_row(row) for row in annual_rows],
            "quarterly": [_label_quarterly_row(row) for row in quarterly_rows],
        },
    }


def _extract_nested_company_period_rows(
    data: JSONValue, expected_ticker: tuple[str, str]
) -> tuple[list[list[JSONValue]], list[list[JSONValue]]]:
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], list) or len(data[0]) != 1:
        return [], []

    company_record = data[0][0]
    if not isinstance(company_record, list) or len(company_record) != 8:
        return [], []
    quarterly_rows, annual_rows = company_record[:2]
    if (
        not isinstance(quarterly_rows, list)
        or not isinstance(annual_rows, list)
        or company_record[2:5] != [None, None, None]
        or not isinstance(company_record[5], str)
        or not isinstance(company_record[6], str)
        or not _looks_like_ticker(company_record[7])
        or not _ticker_matches(company_record[7], expected_ticker)
        or not _has_valid_period_rows(annual_rows, quarterly_rows, nested=True)
        or not _matches_avgo_ds16_signature(company_record[7], quarterly_rows)
    ):
        return [], []
    return annual_rows, quarterly_rows


def _has_valid_period_rows(annual_rows: list[JSONValue], quarterly_rows: list[JSONValue], *, nested: bool) -> bool:
    if not annual_rows and not quarterly_rows:
        return False
    return all(
        isinstance(row, list) and _looks_like_annual_row(row, nested=nested) for row in annual_rows
    ) and all(isinstance(row, list) and _looks_like_quarterly_row(row, nested=nested) for row in quarterly_rows)


def _looks_like_ticker(value: JSONValue) -> bool:
    return isinstance(value, list) and len(value) == 2 and all(isinstance(item, str) for item in value)


def _ticker_matches(ticker: JSONValue, expected_ticker: tuple[str, str]) -> bool:
    return _looks_like_ticker(ticker) and tuple(value.casefold() for value in ticker) == tuple(
        value.casefold() for value in expected_ticker
    )


def _matches_avgo_ds16_signature(ticker: JSONValue, quarterly_rows: list[JSONValue]) -> bool:
    if not _ticker_matches(ticker, ("AVGO", "NASDAQ")):
        return False
    for row in quarterly_rows:
        if (
            isinstance(row, list)
            and len(row) == 4
            and row[0] == 2026
            and row[1] == 2
            and isinstance(row[2], list)
            and row[2][17] == [2026, 5, 3]
        ):
            return all(row[2][index] == value for index, value in _AVGO_DS16_SIGNATURE.items())
    return False


def _looks_like_quarterly_row(value: list[JSONValue], *, nested: bool) -> bool:
    return (
        len(value) == (4 if nested else 3)
        and isinstance(value[0], int)
        and not isinstance(value[0], bool)
        and isinstance(value[1], int)
        and not isinstance(value[1], bool)
        and value[1] in {1, 2, 3, 4}
        and _looks_like_metric_vector(value[2])
        and (not nested or _looks_like_metric_vector(value[3]))
    )


def _looks_like_annual_row(value: list[JSONValue], *, nested: bool) -> bool:
    return (
        len(value) == (3 if nested else 2)
        and isinstance(value[0], int)
        and not isinstance(value[0], bool)
        and _looks_like_metric_vector(value[1])
        and (not nested or _looks_like_metric_vector(value[2]))
    )


def _looks_like_metric_vector(value: JSONValue) -> bool:
    if not isinstance(value, list) or len(value) < 32:
        return False
    numeric_indices = (0, 1, 4, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31)
    return (
        all(isinstance(value[index], int | float) and not isinstance(value[index], bool) for index in numeric_indices)
        and isinstance(value[16], str)
        and _is_valid_period_end_date(value[17])
    )


def _is_valid_period_end_date(value: JSONValue) -> bool:
    if isinstance(value, str):
        try:
            return date.fromisoformat(value).isoformat() == value
        except ValueError:
            return False
    if not isinstance(value, list | tuple) or len(value) != 3:
        return False
    if not all(isinstance(part, int) and not isinstance(part, bool) for part in value):
        return False
    try:
        date(value[0], value[1], value[2])
    except ValueError:
        return False
    return True


def _label_annual_row(row: list[JSONValue]) -> dict[str, JSONValue]:
    return _label_row(year=row[0], quarter=None, metrics=row[1], raw_row=row)


def _label_quarterly_row(row: list[JSONValue]) -> dict[str, JSONValue]:
    return _label_row(year=row[0], quarter=row[1], metrics=row[2], raw_row=row)


def _label_row(
    *, year: JSONValue, quarter: JSONValue, metrics: JSONValue, raw_row: list[JSONValue]
) -> dict[str, JSONValue]:
    metric_values = metrics if isinstance(metrics, list) else []
    groups: dict[str, JSONValue] = {"year": year, "quarter": quarter}
    raw_fields: list[dict[str, JSONValue]] = []

    for group_name, fields in FINANCIALS_FIELD_GROUPS:
        groups[group_name] = {}
        group_values = groups[group_name]
        if not isinstance(group_values, dict):
            continue
        for name, raw_index in fields:
            value = metric_values[raw_index] if raw_index < len(metric_values) else None
            group_values[name] = value
            raw_fields.append({"name": name, "raw_index": raw_index, "value": value})

    return {**groups, "raw_fields": raw_fields, "raw_row": raw_row}
