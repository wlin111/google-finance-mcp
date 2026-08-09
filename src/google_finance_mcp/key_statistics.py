from __future__ import annotations

from typing import Any

from .rpc_metadata import LabeledDataContext

JSONValue = Any


KEY_STATISTICS_VECTOR_SCHEMA_VERSION = "google_finance_quote_key_statistics_ratios.v1"

KEY_STATISTICS_VECTOR_FIELDS: tuple[dict[str, JSONValue], ...] = (
    {
        "raw_index": 0,
        "name": "symbol_exchange",
        "type": "tuple",
        "confidence": "high",
        "description": "Ticker and exchange tuple returned as [symbol, exchange].",
    },
    {
        "raw_index": 1,
        "name": "primary_bucket_1_ratio",
        "type": "ratio",
        "confidence": "low",
        "description": "First ratio in the primary three-bucket distribution. The exact Google Finance label is not exposed.",
    },
    {
        "raw_index": 2,
        "name": "primary_bucket_2_ratio",
        "type": "ratio",
        "confidence": "low",
        "description": "Second ratio in the primary three-bucket distribution. The exact Google Finance label is not exposed.",
    },
    {
        "raw_index": 3,
        "name": "primary_bucket_3_ratio",
        "type": "ratio",
        "confidence": "low",
        "description": "Third ratio in the primary three-bucket distribution. The exact Google Finance label is not exposed.",
    },
    {
        "raw_index": 4,
        "name": "primary_distribution_score",
        "type": "number",
        "confidence": "low",
        "description": "Score paired with the primary three-bucket distribution.",
    },
    {
        "raw_index": 5,
        "name": "comparison_bucket_1_ratio",
        "type": "ratio",
        "confidence": "low",
        "description": "First ratio in the comparison three-bucket distribution. Often repeats across related securities.",
    },
    {
        "raw_index": 6,
        "name": "comparison_bucket_2_ratio",
        "type": "ratio",
        "confidence": "low",
        "description": "Second ratio in the comparison three-bucket distribution. Often repeats across related securities.",
    },
    {
        "raw_index": 7,
        "name": "comparison_bucket_3_ratio",
        "type": "ratio",
        "confidence": "low",
        "description": "Third ratio in the comparison three-bucket distribution. Often repeats across related securities.",
    },
    {
        "raw_index": 8,
        "name": "comparison_distribution_score",
        "type": "number",
        "confidence": "low",
        "description": "Score paired with the comparison three-bucket distribution.",
    },
    {
        "raw_index": 9,
        "name": "auxiliary_metric_1",
        "type": "number",
        "confidence": "unknown",
        "description": "Unlabeled trailing metric returned by Google Finance.",
    },
    {
        "raw_index": 10,
        "name": "auxiliary_metric_2",
        "type": "number",
        "confidence": "unknown",
        "description": "Unlabeled trailing metric returned by Google Finance.",
    },
    {
        "raw_index": 11,
        "name": "auxiliary_metric_3_ratio",
        "type": "ratio",
        "confidence": "unknown",
        "description": "Unlabeled trailing ratio returned by Google Finance.",
    },
)


def enrich_key_statistics_result(
    result: dict[str, JSONValue], context: LabeledDataContext | None = None
) -> dict[str, JSONValue]:
    """Attach best-effort labels to Google Finance quote-page market-stat vectors.

    Google Finance currently returns gXxkFd as a compact vector without field
    names. The labels here are intentionally conservative: they describe the
    stable structure and preserve raw indices instead of asserting unsupported
    semantic names.
    """

    if context is None or not _validates_market_statistics_context(context) or not context.validates_result_id(result.get("id")):
        return result

    rows = _extract_rows(result.get("data"))
    if not rows:
        return result
    labeled_rows = [_label_row(row) for row in rows]

    return {
        **result,
        "labeled_data": {
            "schema_version": KEY_STATISTICS_VECTOR_SCHEMA_VERSION,
            "confidence": "best_effort",
            "caveat": (
                "Google Finance does not expose labels for this compact key-statistics vector. "
                "Names are structural/inferred labels; use raw_index and raw_value as the source of truth."
            ),
            "context": context.as_labeled_data_dict(),
            "field_definitions": list(KEY_STATISTICS_VECTOR_FIELDS),
            "rows": labeled_rows,
        },
    }


def _validates_market_statistics_context(context: LabeledDataContext) -> bool:
    return any(
        context.validates_dataset(dataset_key, '[["SYMBOL", "EXCHANGE"]]', purpose)
        for dataset_key in ("ds:5", "ds:13", "ds:15")
        for purpose in ("Market statistics", "Key statistics / ratios")
    )


def _extract_rows(data: JSONValue) -> list[list[JSONValue]]:
    if not isinstance(data, list) or len(data) != 3 or data[:2] != [None, None]:
        return []
    rows = data[2]
    if not isinstance(rows, list):
        return []
    if _looks_like_key_statistics_row(rows):
        return [rows]
    if not rows or not all(_looks_like_key_statistics_row(row) for row in rows):
        return []
    return rows


def _looks_like_key_statistics_row(value: JSONValue) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= len(KEY_STATISTICS_VECTOR_FIELDS)
        and isinstance(value[0], list)
        and len(value[0]) == 2
        and all(isinstance(item, str) for item in value[0])
        and all(isinstance(item, int | float) and not isinstance(item, bool) for item in value[1:])
    )


def _label_row(row: list[JSONValue]) -> dict[str, JSONValue]:
    values: dict[str, JSONValue] = {}
    raw_fields: list[dict[str, JSONValue]] = []
    for field in KEY_STATISTICS_VECTOR_FIELDS:
        raw_index = int(field["raw_index"])
        raw_value = row[raw_index] if raw_index < len(row) else None
        values[str(field["name"])] = raw_value
        raw_fields.append(
            {
                "raw_index": raw_index,
                "name": field["name"],
                "raw_value": raw_value,
                "confidence": field["confidence"],
            }
        )

    primary_values = [values["primary_bucket_1_ratio"], values["primary_bucket_2_ratio"], values["primary_bucket_3_ratio"]]
    comparison_values = [
        values["comparison_bucket_1_ratio"],
        values["comparison_bucket_2_ratio"],
        values["comparison_bucket_3_ratio"],
    ]

    return {
        "symbol": _symbol_from_tuple(values["symbol_exchange"]),
        "exchange": _exchange_from_tuple(values["symbol_exchange"]),
        "values": values,
        "groups": {
            "primary_distribution": {
                "raw_indices": [1, 2, 3, 4],
                "bucket_ratios": primary_values,
                "bucket_ratio_sum": _sum_numeric(primary_values),
                "score": values["primary_distribution_score"],
                "confidence": "low",
            },
            "comparison_distribution": {
                "raw_indices": [5, 6, 7, 8],
                "bucket_ratios": comparison_values,
                "bucket_ratio_sum": _sum_numeric(comparison_values),
                "score": values["comparison_distribution_score"],
                "confidence": "low",
            },
            "auxiliary_metrics": {
                "raw_indices": [9, 10, 11],
                "values": [values["auxiliary_metric_1"], values["auxiliary_metric_2"], values["auxiliary_metric_3_ratio"]],
                "confidence": "unknown",
            },
        },
        "raw_fields": raw_fields,
        "raw_row": row,
    }


def _symbol_from_tuple(value: JSONValue) -> str | None:
    return str(value[0]) if isinstance(value, list) and value else None


def _exchange_from_tuple(value: JSONValue) -> str | None:
    return str(value[1]) if isinstance(value, list) and len(value) > 1 else None


def _sum_numeric(values: list[JSONValue]) -> float | None:
    if not all(isinstance(value, int | float) for value in values):
        return None
    return float(sum(values))
