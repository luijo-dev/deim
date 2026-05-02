import polars as pl

from services.pdf_dian import extractor as dian_extractor
from services.pdf_handler import words_dataframe_from_bytes
from services.pdf_platform import extractor as platform_extractor

COMPARABLE_COLUMNS = ["cantidad", "peso_neto", "peso_bruto", "fob_total"]
RESULT_COLUMNS = [
    "Estado",
    "subpartida",
    *COMPARABLE_COLUMNS,
    *[f"Plat - {column}" for column in COMPARABLE_COLUMNS],
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


def _dian_comparable_rows(dian_df: pl.DataFrame) -> list[dict]:
    if "subpartida" not in dian_df.columns:
        return []

    rows = []
    for row in dian_df.to_dicts():
        subpartida = _normalize_subpartida(row.get("subpartida"))
        if not subpartida:
            continue
        row["subpartida"] = subpartida
        rows.append(row)
    return rows


def _platform_rows_by_subpartida(platform_df: pl.DataFrame) -> dict[str, dict]:
    if "subpartida" not in platform_df.columns:
        return {}

    rows_by_subpartida = {}
    for row in platform_df.to_dicts():
        subpartida = _normalize_subpartida(row.get("subpartida"))
        if subpartida:
            row["subpartida"] = subpartida
            rows_by_subpartida[subpartida] = row
    return rows_by_subpartida


def _compare_rows(dian_rows: list[dict], platform_df: pl.DataFrame) -> list[dict]:
    platform_rows = _platform_rows_by_subpartida(platform_df)
    result_rows = []

    for dian_row in dian_rows:
        subpartida = dian_row["subpartida"]
        platform_row = platform_rows.get(subpartida)

        if platform_row is None:
            estado = "Sin match"
        elif dian_row == platform_row:
            estado = "Todo bien"
        else:
            estado = "Con diferencias"

        result = {
            "Estado": estado,
            "subpartida": subpartida,
            **{column: dian_row.get(column) for column in COMPARABLE_COLUMNS},
        }

        for column in COMPARABLE_COLUMNS:
            result[f"Plat - {column}"] = (
                platform_row.get(column) if platform_row is not None else None
            )

        result_rows.append(result)

    return result_rows


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

    rows = _compare_rows(_dian_comparable_rows(dian_df), platform_df)

    return {
        "message": "Comparación ejecutada correctamente.",
        "message_kind": "success",
        "counters": _counters_for(rows),
        "rows": rows,
        "columns": RESULT_COLUMNS,
    }
