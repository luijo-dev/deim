import polars as pl

from services.pdf_dian import extractor as dian_extractor
from services.pdf_handler import words_dataframe_from_bytes
from services.pdf_platform import extractor as platform_extractor

COMPARABLE_COLUMNS = ["cantidad", "peso_neto", "peso_bruto", "fob_total"]
DIAN_COLUMNS = {col: f"dian_{col}" for col in COMPARABLE_COLUMNS}
CLIENTE_COLUMNS = {col: f"cliente_{col}" for col in COMPARABLE_COLUMNS}
RESULT_COLUMNS = [
    "Estado",
    "subpartida",
    *[f"dian_{col}" for col in COMPARABLE_COLUMNS],
    *[f"cliente_{col}" for col in COMPARABLE_COLUMNS],
]
COUNTER_KEYS = ["total", "Sin match", "Todo bien", "Con diferencias"]


def _empty_platform_dataframe() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "subpartida": pl.String,
            "cantidad": pl.Float64,
            "peso_neto": pl.Float64,
            "peso_bruto": pl.Float64,
            "fob_total": pl.Float64,
        }
    )


def _empty_counters() -> dict[str, int]:
    return {key: 0 for key in COUNTER_KEYS}


def _normalize_subpartida(value: object) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _comparable_dataframe(df: pl.DataFrame) -> pl.DataFrame:
    required_columns = ["subpartida", *COMPARABLE_COLUMNS]

    if "subpartida" not in df.columns:
        return pl.DataFrame(schema={column: pl.Null for column in required_columns})

    comparable_df = df.select(required_columns).with_columns(
        pl.col("subpartida")
        .map_elements(_normalize_subpartida, return_dtype=pl.String)
        .alias("subpartida")
    )
    comparable_df = comparable_df.filter(pl.col("subpartida").is_not_null())

    comparable_df = comparable_df.group_by("subpartida").agg(
        [pl.col(col).sum().round(2).alias(col) for col in COMPARABLE_COLUMNS]
    )

    return comparable_df


def _compare_rows(dian_df: pl.DataFrame, platform_df: pl.DataFrame) -> pl.DataFrame:
    dian_renamed = dian_df.rename(DIAN_COLUMNS)
    platform_renamed = platform_df.rename(CLIENTE_COLUMNS)

    joined = dian_renamed.join(platform_renamed, on="subpartida", how="left")

    has_platform = pl.col("cliente_cantidad").is_not_null()
    all_match = pl.all_horizontal(
        [pl.col(f"dian_{col}").eq(pl.col(f"cliente_{col}")) for col in COMPARABLE_COLUMNS]
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


def run(dian_pdf_bytes: bytes, platform_pdf_bytes: bytes | None = None) -> dict:
    dian_words_df = words_dataframe_from_bytes(dian_pdf_bytes)
    dian_df = dian_extractor.run(dian_words_df)

    if platform_pdf_bytes:
        platform_words_df = words_dataframe_from_bytes(platform_pdf_bytes)
        platform_df = platform_extractor.run(platform_words_df)
    else:
        platform_df = _empty_platform_dataframe()

    comparison_df = _compare_rows(
        _comparable_dataframe(dian_df),
        _comparable_dataframe(platform_df),
    )
    rows = comparison_df.to_dicts()

    return {
        "message": "Comparación ejecutada correctamente.",
        "message_kind": "success",
        "counters": _counters_for(rows),
        "rows": rows,
        "columns": RESULT_COLUMNS,
    }
