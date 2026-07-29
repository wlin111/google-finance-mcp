from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
import re
from collections.abc import Callable
from typing import TypeAlias

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]

QUOTE_HOLDINGS_RPC_ID = "K5Y6Xb"
QUOTE_HOLDINGS_SCHEMA_VERSION = "google_finance_quote_holdings.v3"
QUOTE_HOLDINGS_MAX_PAGES = 100
_VALIDATED_SYMBOL = "TSLA"
_VALIDATED_EXCHANGE = "NASDAQ"
_VALIDATED_SOURCE_PATH = "/finance/beta/quote/TSLA:NASDAQ"
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_MONETARY_AMOUNT = re.compile(r"\$\d[\d,]*(?:\s*[-–]\s*\$\d[\d,]*)?\Z")
_NUMERIC_TEXT = re.compile(r"\d+(?:\.\d+)?\Z")
_OWNER_VALUES = frozenset({"self", "spouse", "joint", "child", "dependent", "undisclosed"})
_TRANSACTION_TYPES = frozenset(
    {
        "buy",
        "purchase",
        "sale",
        "sell",
        "uninformative buy",
        "uninformative sale",
    }
)


@dataclass(frozen=True)
class QuoteHoldingsContext:
    """Request provenance required before exposing the validated TSLA mapping."""

    source_path: str
    rpc_id: str
    request: JSONValue
    used_default_request: bool

    def validates_contract(self, result_id: object) -> bool:
        return (
            self.source_path == _VALIDATED_SOURCE_PATH
            and self.rpc_id == QUOTE_HOLDINGS_RPC_ID
            and result_id == QUOTE_HOLDINGS_RPC_ID
            and self.used_default_request
            and self.request == quote_holdings_request(_VALIDATED_SYMBOL, _VALIDATED_EXCHANGE)
        )


def quote_holdings_request(symbol: str, exchange: str) -> list[JSONValue]:
    return [[None, [symbol.upper(), exchange.upper()]]]


def quote_holdings_continuation_request(
    symbol: str, exchange: str, *, continuation_type: int, cursor: str
) -> list[JSONValue]:
    if continuation_type not in (1, 2):
        raise ValueError(f"Unsupported quote holdings continuation type: {continuation_type}")
    if not cursor.strip():
        raise ValueError("Quote holdings continuation cursor must not be empty")

    request: list[JSONValue] = [None, [symbol.upper(), exchange.upper()], None, None, None, [continuation_type]]
    if continuation_type == 1:
        request.append(cursor)
    else:
        request.extend([None, cursor])
    return [request]


def quote_holdings_page_rows(result: dict[str, JSONValue], *, continuation_type: int) -> list[list[JSONValue]] | None:
    if result.get("id") != QUOTE_HOLDINGS_RPC_ID or continuation_type not in (1, 2):
        return None
    data = result.get("data")
    if not isinstance(data, list):
        return None
    rows = data[continuation_type - 1] if continuation_type - 1 < len(data) else None
    if not isinstance(rows, list) or not all(isinstance(row, list) for row in rows):
        return None
    return [row for row in rows if isinstance(row, list)]


def quote_holdings_pagination_cursor(result: dict[str, JSONValue], *, continuation_type: int) -> str:
    if result.get("id") != QUOTE_HOLDINGS_RPC_ID or continuation_type not in (1, 2):
        return ""
    data = result.get("data")
    if not isinstance(data, list):
        return ""
    cursor_slots = (6, 10) if continuation_type == 1 else (7,)
    for index in cursor_slots:
        cursor = data[index] if index < len(data) else None
        if isinstance(cursor, str) and cursor.strip():
            return cursor
    return ""


def enrich_quote_holdings_result(
    result: dict[str, JSONValue], context: QuoteHoldingsContext | None = None
) -> dict[str, JSONValue]:
    if context is None or not context.validates_contract(result.get("id")):
        return result

    data = result.get("data")
    validated_rows = _validated_holdings_rows(data)
    if validated_rows is None:
        return result
    politician_holdings, politician_transactions, insider_transactions, cursors = validated_rows

    labeled_data = {
        "schema_version": QUOTE_HOLDINGS_SCHEMA_VERSION,
        "provenance": "validated TSLA:NASDAQ Holdings tab request and response contract",
        "caveat": (
            "Labels are emitted only for the directly validated TSLA:NASDAQ Holdings contract. "
            "Names, share buckets, politician filing dates, insider identity and position, and insider amount and shares remain raw_row-only "
            "because their same-type slots cannot be distinguished at runtime. Format changes remain raw-only."
        ),
        "politician_holdings": [_label_politician_holding(row) for row in politician_holdings],
        "politician_transactions": [_label_politician_transaction(row) for row in politician_transactions],
        "insider_transactions": [_label_insider_transaction(row) for row in insider_transactions],
        "pagination": {
            "politician_holdings_cursor": cursors[0],
            "politician_transactions_cursor": cursors[1],
            "insider_transactions_cursor": cursors[2],
        },
        "raw_slots": {
            "politician_holdings": 0,
            "politician_transactions": 1,
            "insider_transactions": 4,
            "pagination_cursors": [6, 7, 8],
        },
        "withheld_fields": {
            "politician_holdings": ["name", "shares_min", "shares_mid", "shares_max"],
            "politician_transactions": ["name", "filing_date"],
            "insider_transactions": ["insider", "position", "shares", "amount"],
        },
    }

    return {**result, "labeled_data": labeled_data}


def _validated_holdings_rows(
    data: JSONValue,
) -> tuple[list[list[JSONValue]], list[list[JSONValue]], list[list[JSONValue]], tuple[JSONValue, JSONValue, JSONValue]] | None:
    if not isinstance(data, list) or len(data) != 9:
        return None
    politician_holdings, politician_transactions, _, _, insider_transactions, _, *cursors = data
    if (
        not isinstance(politician_holdings, list)
        or not isinstance(politician_transactions, list)
        or data[2:4] != [None, None]
        or not isinstance(insider_transactions, list)
        or data[5] is not None
        or len(cursors) != 3
        or not all(isinstance(cursor, str) or cursor is None for cursor in cursors)
    ):
        return None
    holdings_rows = _validated_rows(politician_holdings, _is_politician_holding_row)
    transaction_rows = _validated_rows(politician_transactions, _is_politician_transaction_row)
    insider_rows = _validated_rows(insider_transactions, _is_insider_transaction_row)
    if holdings_rows is None or transaction_rows is None or insider_rows is None:
        return None
    return holdings_rows, transaction_rows, insider_rows, (cursors[0], cursors[1], cursors[2])


def _validated_rows(
    rows: list[JSONValue], validator: Callable[[list[JSONValue]], bool]
) -> list[list[JSONValue]] | None:
    if not rows:
        return None
    validated_rows: list[list[JSONValue]] = []
    for row in rows:
        if not isinstance(row, list) or not validator(row):
            return None
        validated_rows.append(row)
    return validated_rows


def _is_politician_holding_row(row: list[JSONValue]) -> bool:
    return (
        len(row) == 17
        and all(_is_nonempty_text(row[index]) for index in (0, 3, 4, 9, 11, 12, 13, 14, 15, 16))
        and row[2] == _VALIDATED_SYMBOL
        and _is_integer(row[5])
        and _is_owner(row[1])
        and all(_is_numeric_text(row[index]) for index in (6, 7, 8))
        and isinstance(row[10], bool)
    )


def _is_politician_transaction_row(row: list[JSONValue]) -> bool:
    return (
        len(row) == 12
        and all(_is_nonempty_text(row[index]) for index in (0, 6, 7, 8, 9, 10, 11))
        and _is_iso_date(row[1])
        and row[2] == _VALIDATED_SYMBOL
        and _is_transaction_type(row[3])
        and _is_monetary_amount(row[4])
        and _is_iso_date(row[5])
    )


def _is_insider_transaction_row(row: list[JSONValue]) -> bool:
    return (
        len(row) == 14
        and row[0] == [_VALIDATED_SYMBOL, _VALIDATED_EXCHANGE]
        and _is_integer(row[1])
        and all(_is_nonempty_text(row[index]) for index in (2, 3, 4, 5, 6, 8, 12, 13))
        and _is_transaction_type(row[7])
        and _is_date_parts(row[9])
        and _is_number(row[10])
        and _is_number(row[11])
    )


def _is_nonempty_text(value: JSONValue) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_integer(value: JSONValue) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: JSONValue) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_owner(value: JSONValue) -> bool:
    return isinstance(value, str) and value.casefold() in _OWNER_VALUES


def _is_transaction_type(value: JSONValue) -> bool:
    return isinstance(value, str) and value.casefold() in _TRANSACTION_TYPES


def _is_monetary_amount(value: JSONValue) -> bool:
    return isinstance(value, str) and bool(_MONETARY_AMOUNT.fullmatch(value))


def _is_numeric_text(value: JSONValue) -> bool:
    return isinstance(value, str) and bool(_NUMERIC_TEXT.fullmatch(value))


def _is_iso_date(value: JSONValue) -> bool:
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        return False
    year, month, day = (int(part) for part in value.split("-"))
    return 1 <= month <= 12 and 1 <= day <= monthrange(year, month)[1]


def _is_date_parts(value: JSONValue) -> bool:
    if not isinstance(value, list) or len(value) != 3 or not all(_is_integer(part) for part in value):
        return False
    year, month, day = value
    if not isinstance(year, int) or not isinstance(month, int) or not isinstance(day, int):
        return False
    return 1 <= year and 1 <= month <= 12 and 1 <= day <= monthrange(year, month)[1]


def _label_politician_holding(row: list[JSONValue]) -> dict[str, JSONValue]:
    return {
        "values": {
            "disclosure": row[5],
            "owner": row[1],
        },
        "raw_row": row,
    }


def _label_politician_transaction(row: list[JSONValue]) -> dict[str, JSONValue]:
    return {
        "values": {
            "issuer": row[2],
            "type": row[3],
            "amount": row[4],
        },
        "raw_row": row,
    }


def _label_insider_transaction(row: list[JSONValue]) -> dict[str, JSONValue]:
    return {
        "values": {
            "type": row[7],
            "date": row[9],
        },
        "raw_row": row,
    }
