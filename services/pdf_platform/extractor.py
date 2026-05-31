import re
import unicodedata

import polars as pl

from .chunk import chunk_words_subpartidas_hasta_anexos
from .summary import build_rows

_NUMERIC_MERCHANDISE_COLUMN_IDS = ["p_bruto", "p_neto", "cantidad", "valor_fob_total"]
_NUMERIC_TEXT_REGEX = r"^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$"
_TOTAL_LABELS = {
    "valor_flete": "Valor Fletes :",
    "valor_seguro": "Valor Seguro :",
    "otros_gastos": "Otros Gastos :",
}
_INFORMATIVE_LABELS = {
    "valor_cif_us": "Valor CIF US :",
}

_MERCANCIA_HEADER_CONFIG = [
    {"name": "Ref.", "x0_tolerance": 0, "x1_tolerance": 0, "is_align_left": True},
    {"name": "Embalaje", "x0_tolerance": 0, "x1_tolerance": 0, "is_align_left": True},
    {"name": "Descripción", "x0_tolerance": 0, "x1_tolerance": 0, "is_align_left": True},
    {"name": "P. Bruto", "x0_tolerance": 0, "x1_tolerance": 10, "is_align_left": False},
    {"name": "P. Neto", "x0_tolerance": 0, "x1_tolerance": 10, "is_align_left": False},
    {"name": "Cantidad", "x0_tolerance": 0, "x1_tolerance": 10, "is_align_left": False},
    {
        "name": "Valor FOB Total",
        "x0_tolerance": 0,
        "x1_tolerance": 10,
        "is_align_left": False,
    },
    {
        "name": "Valor FOB Real",
        "x0_tolerance": 0,
        "x1_tolerance": 10,
        "is_align_left": False,
    },
]

HEADER_MERCANCIA = [config["name"] for config in _MERCANCIA_HEADER_CONFIG]


def _normalize_header_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", normalized.lower())
    return normalized.strip("_")


def find_header_rows(df: pl.DataFrame, header_text: str) -> list[dict[str, object]]:
    header_line = (
        df.sort(["page", "row_id", "x0"])
        .group_by(["page", "row_id"], maintain_order=True)
        .agg(pl.col("text").str.join(" ").alias("text"))
        .filter(pl.col("text").str.strip_chars().str.contains(header_text))
        .unique(subset=["page", "row_id"], maintain_order=True)
        .head(1)
    )

    if header_line.is_empty():
        return []

    header = header_line.row(0, named=True)

    return (
        df.filter((pl.col("page") == header["page"]) & (pl.col("row_id") == header["row_id"]))
        .sort("x0")
        .select(["page", "row_id", "x0", "x1", "text"])
        .to_dicts()
    )


def build_mercancia_header_ranges(
    mercancia_header_rows: list[dict[str, object]], header_mercancia: list[str]
) -> list[dict[str, object]]:
    config_by_name = {config["name"]: config for config in _MERCANCIA_HEADER_CONFIG}
    rows = sorted(
        mercancia_header_rows,
        key=lambda row: (int(row.get("page", 0)), int(row.get("row_id", 0)), float(row["x0"])),
    )

    header_ranges: list[dict[str, object]] = []
    cursor = 0
    row_words = [str(row.get("text", "")).strip().casefold() for row in rows]

    for header_name in header_mercancia:
        target_words = header_name.split()
        target_words_normalized = [word.strip().casefold() for word in target_words]
        match_start = None

        for start in range(cursor, len(rows) - len(target_words) + 1):
            window_words = row_words[start : start + len(target_words)]
            if window_words == target_words_normalized:
                match_start = start
                break

        if match_start is None:
            continue

        window = rows[match_start : match_start + len(target_words)]
        header_config = config_by_name[header_name]
        header_ranges.append(
            {
                "name": header_name,
                "column_id": _normalize_header_name(header_name),
                "x0": min(float(row["x0"]) for row in window),
                "x1": max(float(row["x1"]) for row in window),
                "x0_tolerance": header_config["x0_tolerance"],
                "x1_tolerance": header_config["x1_tolerance"],
                "is_align_left": header_config["is_align_left"],
            }
        )
        cursor = match_start + len(target_words)

    return header_ranges


def build_columns(df: pl.DataFrame, header_config: list[dict[str, object]]) -> pl.DataFrame:
    required = {"page", "x0", "x1", "text"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"df falta columnas requeridas para build_columns: {sorted(missing)}")

    if not header_config:
        return df.with_columns(
            pl.lit(None, dtype=pl.String).alias("column_id"),
            pl.lit(None, dtype=pl.String).alias("column_name"),
        )

    result = df.with_row_index("_original_order").with_columns(
        pl.lit(None, dtype=pl.String).alias("column_id"),
        pl.lit(None, dtype=pl.String).alias("column_name"),
    )

    for header in header_config:
        lower = float(header["x0"]) - float(header["x0_tolerance"])
        upper = float(header["x1"]) + float(header["x1_tolerance"])
        anchor = "x0" if bool(header["is_align_left"]) else "x1"
        matches_header = pl.col("column_id").is_null() & pl.col(anchor).is_between(
            lower, upper, closed="both"
        )

        result = result.with_columns(
            pl.when(matches_header)
            .then(pl.lit(str(header["column_id"])))
            .otherwise(pl.col("column_id"))
            .alias("column_id"),
            pl.when(matches_header)
            .then(pl.lit(str(header["name"])))
            .otherwise(pl.col("column_name"))
            .alias("column_name"),
        )

    return result.sort("_original_order").drop("_original_order")


def _clean_numeric_text_expr(column_name: str = "text") -> pl.Expr:
    return (
        pl.col(column_name)
        .str.strip_chars()
        .str.replace(r"^\$", "")
        .str.replace_all(r"^[\.\-–—'\"“”‘’`:;\s]+", "")
        .str.replace_all(r"[\.\-–—'\"“”‘’`:;\s]+$", "")
    )


def _parse_summary_numeric(value: str | None) -> float | None:
    if value is None:
        return None

    cleaned = re.sub(r"[^\d\.,]", "", value)
    if not cleaned:
        return None

    cleaned = cleaned.replace(",", "")
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def _page_one_lines(words_df: pl.DataFrame) -> pl.DataFrame:
    return (
        words_df.filter(pl.col("page") == 1)
        .sort(["block_no", "line_no", "word_no"])
        .group_by(["block_no", "line_no"], maintain_order=True)
        .agg(pl.col("text").str.join(" ").alias("line_text"))
        .sort(["block_no", "line_no"])
    )


def _extract_page_one_summary_values(
    words_df: pl.DataFrame, fields: dict[str, str]
) -> dict[str, float | None]:
    lines_df = _page_one_lines(words_df)
    values: dict[str, float | None] = {}

    for key, label in fields.items():
        match = lines_df.filter(pl.col("line_text").eq(label)).head(1)
        if match.is_empty():
            values[key] = None
            continue

        block_no = match.item(0, "block_no")
        line_no = match.item(0, "line_no")
        value_line = lines_df.filter(
            (pl.col("block_no") == block_no) & (pl.col("line_no") == line_no + 1)
        ).head(1)
        values[key] = _parse_summary_numeric(
            None if value_line.is_empty() else value_line.item(0, "line_text")
        )

    return values


def select_numeric_merchandise_columns(df: pl.DataFrame) -> pl.DataFrame:
    return (
        df.filter(pl.col("column_id").is_in(_NUMERIC_MERCHANDISE_COLUMN_IDS))
        .with_columns(_clean_numeric_text_expr().alias("text_numeric_cleaned"))
        .filter(pl.col("text_numeric_cleaned").str.contains(_NUMERIC_TEXT_REGEX))
        .with_columns(
            pl.col("text_numeric_cleaned")
            .str.replace_all(",", "")
            .cast(pl.Float64)
            .round(2)
            .alias("column_value")
        )
    )


def build_platform_values_contract(df: pl.DataFrame) -> pl.DataFrame:
    required = {"page", "row_id", "column_id", "column_value", "subpartida_code"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            "df falta columnas requeridas para build_platform_values_contract: "
            f"{sorted(missing)}"
        )

    return (
        df.select(
            [
                "page",
                "row_id",
                "column_id",
                pl.col("column_value").alias("value"),
                pl.col("subpartida_code").alias("subpartida"),
            ]
        )
        .filter(pl.col("subpartida").is_not_null())
    )


def platform_df_adapter(df: pl.DataFrame) -> pl.DataFrame:
    required = {"page", "row_id", "column_id", "value", "subpartida"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"df falta columnas requeridas para platform_df_adapter: {sorted(missing)}"
        )

    # Comparable contract intentionally excludes valor_fob_real/fob_real until DIAN
    # exposes an equivalent source for a fair comparison.
    return (
        df.filter(pl.col("column_id").is_in(_NUMERIC_MERCHANDISE_COLUMN_IDS))
        .group_by(["page", "row_id", "subpartida"], maintain_order=True)
        .agg(
            [
                pl.col("value").filter(pl.col("column_id") == column_id).first().alias(column_id)
                for column_id in _NUMERIC_MERCHANDISE_COLUMN_IDS
            ]
        )
        .filter(pl.all_horizontal(pl.col(_NUMERIC_MERCHANDISE_COLUMN_IDS).is_not_null()))
        .select(["subpartida", *_NUMERIC_MERCHANDISE_COLUMN_IDS])
        .rename(
            {
                "p_bruto": "peso_bruto",
                "p_neto": "peso_neto",
                "valor_fob_total": "fob_total",
            }
        )
    )


def add_subpartida_id(df: pl.DataFrame) -> pl.DataFrame:
    required = {"page", "x0", "y0", "x1", "y1", "text", "row_id"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"df falta columnas requeridas para add_subpartida_id: {sorted(missing)}")

    row_columns = ["page", "x0", "y0", "x1", "y1", "text", "row_id"]

    return (
        df.sort(["page", "row_id", "x0"])
        .with_columns(
            pl.col("text")
            .str.strip_chars()
            .str.to_lowercase()
            .eq("subpartidas")
            .cast(pl.Int64)
            .cum_sum()
            .alias("subpartida_id")
        )
        .filter(pl.col("subpartida_id") > 0)
        .select(row_columns + ["subpartida_id"])
    )


def add_subpartida_code(df: pl.DataFrame) -> pl.DataFrame:
    required = {"page", "x0", "row_id", "text", "subpartida_id"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"df falta columnas requeridas para add_subpartida_code: {sorted(missing)}"
        )

    row_texts = (
        df.sort(["subpartida_id", "page", "row_id", "x0"])
        .group_by(["subpartida_id", "page", "row_id"], maintain_order=True)
        .agg(pl.col("text").str.join(" ").alias("line_text"))
        .with_columns(pl.int_range(pl.len()).over("subpartida_id").alias("row_pos"))
    )

    description_rows = (
        row_texts.filter(
            pl.col("line_text").str.strip_chars().str.starts_with("Descripción de la Mercancía")
        )
        .group_by("subpartida_id")
        .agg(pl.col("row_pos").min().alias("description_row_pos"))
    )

    codes = (
        row_texts.join(description_rows, on="subpartida_id", how="inner")
        .filter(pl.col("row_pos") < pl.col("description_row_pos"))
        .with_columns(pl.col("line_text").str.extract(r"^(\d{10})\s", 1).alias("subpartida_code"))
        .filter(pl.col("subpartida_code").is_not_null())
        .group_by("subpartida_id", maintain_order=True)
        .agg(pl.col("subpartida_code").last())
    )

    return df.join(codes, on="subpartida_id", how="left")


def _extract_rows(words_df: pl.DataFrame) -> pl.DataFrame:
    platform_words_df = chunk_words_subpartidas_hasta_anexos(words_df)
    rows_df = build_rows(platform_words_df, y_tolerance=2)

    header_mercancia_1 = HEADER_MERCANCIA[:-1]
    header_mercancia_2 = HEADER_MERCANCIA[-2:]
    mercancia_header_rows = find_header_rows(rows_df, " ".join(header_mercancia_1))
    mercancia_header_rows += find_header_rows(rows_df, " ".join(header_mercancia_2))

    mercancia_header_ranges = build_mercancia_header_ranges(mercancia_header_rows, HEADER_MERCANCIA)
    rows_with_subpartida_id = add_subpartida_id(rows_df)
    rows_with_subpartida_code = add_subpartida_code(rows_with_subpartida_id)
    columns_df = build_columns(rows_with_subpartida_code, mercancia_header_ranges)
    numeric_columns_df = select_numeric_merchandise_columns(columns_df)
    platform_values_contract_df = build_platform_values_contract(numeric_columns_df)
    return platform_df_adapter(platform_values_contract_df)


def run(words_df: pl.DataFrame) -> dict[str, object]:
    return {
        "rows": _extract_rows(words_df),
        "totals": _extract_page_one_summary_values(words_df, _TOTAL_LABELS),
        "informative_fields": _extract_page_one_summary_values(words_df, _INFORMATIVE_LABELS),
    }
