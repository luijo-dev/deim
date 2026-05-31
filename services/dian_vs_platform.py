import logging

import polars as pl

from services.pdf_dian import extractor as dian_extractor
from services.pdf_handler import words_dataframe_from_bytes
from services.pdf_platform import extractor as platform_extractor

logger = logging.getLogger(__name__)

COMPARABLE_COLUMNS = [
    "cantidad",
    "peso_neto",
    "peso_bruto",
    "fob_total",
    "valor_flete",
    "valor_seguro",
    "otros_gastos",
]
STATUS_COLUMNS = ["cantidad", "peso_neto", "peso_bruto", "fob_total"]
DIAN_INFO_COLUMNS = ["codigo_acuerdo", "numero_formulario", "numero_levante", "numero"]
DIAN_COLUMNS = {col: f"dian_{col}" for col in COMPARABLE_COLUMNS}
CLIENTE_COLUMNS = {col: f"cliente_{col}" for col in COMPARABLE_COLUMNS}
RESULT_COLUMNS = [
    "Estado",
    "subpartida",
    *DIAN_INFO_COLUMNS,
    *[f"dian_{col}" for col in COMPARABLE_COLUMNS],
    *[f"cliente_{col}" for col in STATUS_COLUMNS],
]
COUNTER_KEYS = ["total", "Sin match", "Todo bien", "Con diferencias"]
TOTAL_FIELD_LABELS = {
    "valor_flete": "Valor flete",
    "valor_seguro": "Valor seguro",
    "otros_gastos": "Otros gastos",
}
INFORMATIVE_FIELD_LABELS = {
    "valor_cif_us": "Valor CIF US",
}


def _empty_platform_dataframe() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "subpartida": pl.String,
            "cantidad": pl.Float64,
            "peso_neto": pl.Float64,
            "peso_bruto": pl.Float64,
            "fob_total": pl.Float64,
            "valor_flete": pl.Float64,
            "valor_seguro": pl.Float64,
            "otros_gastos": pl.Float64,
        }
    )


def _empty_counters() -> dict[str, int]:
    return {key: 0 for key in COUNTER_KEYS}


def _normalize_subpartida(value: object) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _sum_or_none_expr(column: str) -> pl.Expr:
    non_null_values = pl.col(column).drop_nulls()
    return (
        pl.when(non_null_values.count() == 0)
        .then(pl.lit(None))
        .otherwise(non_null_values.sum().round(2))
        .alias(column)
    )


def _ordered_unique_join(values: pl.Series | list[object] | None) -> str | None:
    if values is None:
        return None

    raw_values = values.to_list() if isinstance(values, pl.Series) else values
    if not raw_values:
        return None

    normalized_values = []
    for value in raw_values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            normalized_values.append(text)

    if not normalized_values:
        return None

    return ", ".join(dict.fromkeys(normalized_values))


def _with_missing_columns(df: pl.DataFrame, columns: list[str], dtype: pl.DataType) -> pl.DataFrame:
    missing_columns = [column for column in columns if column not in df.columns]
    if not missing_columns:
        return df

    return df.with_columns([pl.lit(None, dtype=dtype).alias(column) for column in missing_columns])


def _grouped_subpartida_dataframe(df: pl.DataFrame, text_columns: list[str]) -> pl.DataFrame:
    required_columns = ["subpartida", *COMPARABLE_COLUMNS, *text_columns]

    if "subpartida" not in df.columns:
        return pl.DataFrame(schema={column: pl.Null for column in required_columns})

    normalized_df = _with_missing_columns(df, COMPARABLE_COLUMNS, pl.Float64)
    normalized_df = _with_missing_columns(normalized_df, text_columns, pl.String)

    comparable_df = normalized_df.select(required_columns).with_columns(
        pl.col("subpartida")
        .map_elements(_normalize_subpartida, return_dtype=pl.String)
        .alias("subpartida")
    )
    comparable_df = comparable_df.filter(pl.col("subpartida").is_not_null())

    comparable_df = comparable_df.group_by("subpartida").agg(
        [_sum_or_none_expr(col) for col in COMPARABLE_COLUMNS]
        + [pl.col(column).alias(column) for column in text_columns]
    )

    if text_columns:
        comparable_df = comparable_df.with_columns(
            [
                pl.col(column)
                .map_elements(_ordered_unique_join, return_dtype=pl.String)
                .alias(column)
                for column in text_columns
            ]
        )

    return comparable_df


def _compare_rows(dian_df: pl.DataFrame, platform_df: pl.DataFrame) -> pl.DataFrame:
    dian_renamed = dian_df.rename(DIAN_COLUMNS)
    platform_renamed = platform_df.rename(CLIENTE_COLUMNS)

    joined = dian_renamed.join(platform_renamed, on="subpartida", how="left")

    has_platform = pl.col("cliente_cantidad").is_not_null()
    all_match = pl.all_horizontal(
        [pl.col(f"dian_{col}").eq(pl.col(f"cliente_{col}")) for col in STATUS_COLUMNS]
    )
    estado_expr = (
        pl.when(~has_platform)
        .then(pl.lit("Sin match"))
        .when(all_match)
        .then(pl.lit("Todo bien"))
        .otherwise(pl.lit("Con diferencias"))
    )

    return joined.with_columns(estado_expr.alias("Estado")).select(RESULT_COLUMNS)


def _counters_for(rows: list[dict]) -> dict[str, int]:
    counters = _empty_counters()
    counters["total"] = len(rows)

    for row in rows:
        estado = row.get("Estado")
        if estado in counters:
            counters[estado] += 1

    return counters


def _total_status(dian_value: float | None, platform_value: float | None) -> str:
    if platform_value is None:
        return "Sin match"
    if dian_value == platform_value:
        return "Todo bien"
    return "Con diferencias"


def _sum_column_or_none(df: pl.DataFrame, column: str) -> float | None:
    if column not in df.columns:
        return None

    values = df.get_column(column).drop_nulls()
    if values.is_empty():
        return None

    return round(float(values.sum()), 2)


def _build_totals(
    dian_df: pl.DataFrame,
    platform_df: pl.DataFrame,
    platform_totals: dict[str, float | None],
) -> list[dict[str, object]]:
    totals = []
    for key, label in TOTAL_FIELD_LABELS.items():
        dian_value = _sum_column_or_none(dian_df, key)
        platform_value = _sum_column_or_none(platform_df, key)
        if platform_value is None:
            platform_value = platform_totals.get(key)
        totals.append(
            {
                "key": key,
                "label": label,
                "dian_value": dian_value,
                "platform_value": platform_value,
                "dian_missing": dian_value is None,
                "platform_missing": platform_value is None,
                "status": _total_status(dian_value, platform_value),
            }
        )
    return totals


def _build_informative_fields(
    dian_fields: dict[str, object], platform_fields: dict[str, object]
) -> list[dict[str, object]]:
    informative_fields = []
    for key, label in INFORMATIVE_FIELD_LABELS.items():
        dian_value = dian_fields.get(key)
        platform_value = platform_fields.get(key)
        informative_fields.append(
            {
                "key": key,
                "label": label,
                "dian_value": dian_value,
                "platform_value": platform_value,
                "dian_missing": dian_value is None,
                "platform_missing": platform_value is None,
            }
        )
    return informative_fields


def run(dian_pdf_bytes: bytes, platform_pdf_bytes: bytes | None = None) -> dict:
    dian_words_df = words_dataframe_from_bytes(dian_pdf_bytes, filter_footer=False)
    logger.info("DIAN words_df shape=%s", getattr(dian_words_df, "shape", None))
    dian_result = dian_extractor.run(dian_words_df)
    dian_df = dian_result["rows"]
    logger.info("DIAN extracted_df shape=%s columns=%s", dian_df.shape, dian_df.columns)
    logger.info("DIAN extracted_df head:\n%s", dian_df.head())

    if platform_pdf_bytes:
        platform_words_df = words_dataframe_from_bytes(platform_pdf_bytes)
        logger.info("Platform words_df shape=%s", getattr(platform_words_df, "shape", None))
        platform_result = platform_extractor.run(platform_words_df)
        platform_df = platform_result["rows"]
        logger.info(
            "Platform extracted_df shape=%s columns=%s",
            platform_df.shape,
            platform_df.columns,
        )
    else:
        platform_result = {
            "rows": _empty_platform_dataframe(),
            "totals": {},
            "informative_fields": {},
        }
        platform_df = _empty_platform_dataframe()
        logger.info("No platform PDF provided; using empty platform dataframe")

    dian_comparable = _grouped_subpartida_dataframe(dian_df, DIAN_INFO_COLUMNS)
    platform_comparable = _grouped_subpartida_dataframe(platform_df, [])
    logger.info("DIAN comparable shape=%s", dian_comparable.shape)
    logger.info("Platform comparable shape=%s", platform_comparable.shape)

    comparison_df = _compare_rows(dian_comparable, platform_comparable)
    rows = comparison_df.to_dicts()
    logger.info("Comparison rows=%s", len(rows))

    return {
        "message": "Comparación ejecutada correctamente.",
        "message_kind": "success",
        "counters": _counters_for(rows),
        "rows": rows,
        "totals": _build_totals(
            dian_comparable,
            platform_comparable,
            platform_result.get("totals", {}),
        ),
        "informative_fields": _build_informative_fields(
            dian_result.get("informative_fields", {}),
            platform_result.get("informative_fields", {}),
        ),
        "columns": RESULT_COLUMNS,
    }
