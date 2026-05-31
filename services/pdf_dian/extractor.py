import logging
import re

import polars as pl

logger = logging.getLogger(__name__)

_ROW_NUMERIC_COLUMNS = [
    "cantidad",
    "peso_neto",
    "peso_bruto",
    "fob_total",
    "valor_flete",
    "valor_seguro",
    "otros_gastos",
]
_TOTAL_FIELDS = {
    "valor_flete": "79. Valor fletes USD",
    "valor_seguro": "80. Valor Seguros USD",
    "otros_gastos": "81. Valor Otros Gastos USD",
}
_INFORMATIVE_FIELDS = {
    "codigo_acuerdo": "67. Cod. Acuerdo",
    "numero_formulario": "4. Numero de formulario",
    "numero_levante": "134. Levante No.",
}
_ROW_TEXT_COLUMNS = ["codigo_acuerdo", "numero_formulario", "numero_levante", "numero"]
_NUMERO_LEVANTE_X0_TOLERANCE = -40
_NUMERO_LEVANTE_X1_TOLERANCE = 80
_NUMERO_LEVANTE_Y0_TOLERANCE = -3
_NUMERO_LEVANTE_MAX_Y_GAP = 12
_NUMERO_X1_TOLERANCE = 70
_NUMERO_MAX_Y_GAP = 60


def _target_line_regex(target_line: str) -> str:
    """Build a tolerant regex for DIAN labels with variable spacing around dots."""
    words = []
    for word in target_line.split():
        escaped = re.escape(word)
        escaped = escaped.replace(r"\.", r"\s*\.\s*")
        words.append(escaped)
    return r"^" + r"\s+".join(words)


def _clean_dian_numeric_text(column_name: str = "text") -> pl.Expr:
    return (
        pl.col(column_name)
        .str.strip_chars()
        .str.replace(r"^\$", "")
        .str.replace_all(r"^[\.\-–—'\"\"''`:;\s]+", "")
        .str.replace_all(r"[\.\-–—'\"\"''`:;\s]+$", "")
        .str.reverse()
        .str.replace(r"\.", "@", n=1)
        .str.reverse()
        .str.replace_all(r"\.", "")
        .str.replace("@", ".")
        .cast(pl.Float64, strict=False)
        .round(2)
    )


def get_value_by_geometric(
    df: pl.DataFrame,
    target_line: str,
    x0_tolerance: int = 0,
    x1_tolerance: int = 0,
    y0_tolerance: int = 0,
    max_y_gap: int | None = None,
) -> pl.DataFrame:

    if not isinstance(df, pl.DataFrame):
        raise TypeError("df must be a polars DataFrame")

    if not isinstance(target_line, str):
        raise ValueError("target_line must be a non-empty string")

    if not isinstance(x0_tolerance, int):
        raise TypeError("x0_tolerance must be an int")

    if not isinstance(x1_tolerance, int):
        raise TypeError("x1_tolerance must be an int")

    if not isinstance(y0_tolerance, int):
        raise TypeError("y0_tolerance must be an int")

    if max_y_gap is not None and not isinstance(max_y_gap, int):
        raise TypeError("max_y_gap must be an int or None")

    keys = ["page", "block_no", "line_no"]

    lines_df = (
        df.sort(keys + ["word_no"])
        .group_by(keys)
        .agg(pl.col("text").str.join(" ").alias("line_text"))
    )

    target_line_regex = _target_line_regex(target_line)
    line_matches = (
        lines_df
        .filter(pl.col("line_text").str.contains(target_line_regex))
        .select(keys)
    )

    if line_matches.is_empty():
        target_number = target_line.split(".", maxsplit=1)[0]
        nearby_lines = (
            lines_df
            .filter(pl.col("line_text").str.contains(target_number))
            .select([*keys, "line_text"])
            .head(10)
        )
        logger.warning(
            "DIAN target=%r line_matches=0. Nearby lines containing %r:\n%s",
            target_line,
            target_number,
            nearby_lines,
        )

    target_line_list = target_line.split()

    label_df = (
        df.join(line_matches, on=keys, how="inner")
        .filter(pl.col("text").is_in(target_line_list))
        .sort(keys + ["word_no"])
        .with_columns(pl.lit("label").alias("kind"))
    )

    label_bounds = label_df.group_by(keys).agg(
        pl.col("x0").min().alias("label_x0_min"),
        pl.col("x1").max().alias("label_x1_max"),
        pl.col("y0").max().alias("label_y0_max"),
    )

    logger.info(
        "DIAN target=%r line_matches=%s label_words=%s label_bounds:\n%s",
        target_line,
        line_matches.height,
        label_df.height,
        label_bounds.head(5),
    )

    candidate_words = df.select(
        [
            pl.col("page"),
            pl.col("x0").alias("cand_x0"),
            pl.col("y0").alias("cand_y0"),
            pl.col("x1").alias("cand_x1"),
            pl.col("y1").alias("cand_y1"),
            pl.col("text").alias("cand_text"),
            pl.col("block_no").alias("cand_block_no"),
            pl.col("line_no").alias("cand_line_no"),
            pl.col("word_no").alias("cand_word_no"),
        ]
    )

    candidate_filter = (
        (pl.col("cand_x0") > (pl.col("label_x0_min") - x0_tolerance))
        & (pl.col("cand_x0") < (pl.col("label_x1_max") + x1_tolerance))
        & (pl.col("cand_y0") > (pl.col("label_y0_max") + y0_tolerance))
    )
    if max_y_gap is not None:
        candidate_filter = candidate_filter & (
            pl.col("cand_y0") <= (pl.col("label_y0_max") + max_y_gap)
        )

    filtered_candidates = candidate_words.join(label_bounds, on=["page"], how="inner").filter(
        candidate_filter
    )

    logger.info(
        "DIAN target=%r filtered_candidates=%s sample:\n%s",
        target_line,
        filtered_candidates.height,
        filtered_candidates.select(
            [
                "page",
                "cand_text",
                "cand_x0",
                "cand_y0",
                "cand_y1",
                "label_x0_min",
                "label_x1_max",
                "label_y0_max",
            ]
        ).head(15),
    )

    value_candidates = (
        filtered_candidates
        .sort(["page", "block_no", "line_no", "cand_y0", "cand_x0", "cand_word_no"])
        .group_by(keys)
        .agg(
            pl.col("cand_x0").first().alias("x0"),
            pl.col("cand_y0").first().alias("y0"),
            pl.col("cand_x1").first().alias("x1"),
            pl.col("cand_y1").first().alias("y1"),
            pl.col("cand_text").first().alias("text"),
            pl.col("cand_word_no").first().alias("word_no"),
        )
        .with_columns(pl.lit("value").alias("kind"))
        .select(label_df.columns)
    )

    logger.info(
        "DIAN target=%r value_candidates=%s selected:\n%s",
        target_line,
        value_candidates.height,
        value_candidates.select(["page", "text", "x0", "y0", "y1"]).head(15),
    )

    result_df = pl.concat([label_df, value_candidates], how="vertical").sort(
        keys + ["kind", "word_no"]
    )
    return (
        result_df.filter(pl.col("kind") == "value")
        .select(pl.col("page"), pl.col("text"))
        .sort("page")
    )


def get_nearest_value_by_geometric(
    df: pl.DataFrame,
    target_line: str,
    x0_tolerance: int = 0,
    x1_tolerance: int = 0,
    max_y_gap: int | None = None,
) -> pl.DataFrame:
    keys = ["page", "block_no", "line_no"]
    lines_df = (
        df.sort(keys + ["word_no"])
        .group_by(keys)
        .agg(pl.col("text").str.join(" ").alias("line_text"))
    )

    line_matches = (
        lines_df.filter(pl.col("line_text").str.contains(_target_line_regex(target_line))).select(keys)
    )
    if line_matches.is_empty():
        return pl.DataFrame(schema={"page": pl.Int64, "text": pl.String})

    label_bounds = df.join(line_matches, on=keys, how="inner").group_by(keys).agg(
        pl.col("x0").min().alias("label_x0_min"),
        pl.col("x1").max().alias("label_x1_max"),
        pl.col("y0").max().alias("label_y0_max"),
    )

    line_candidates = (
        df.sort(keys + ["word_no"])
        .group_by(keys)
        .agg(
            pl.col("x0").min().alias("line_x0_min"),
            pl.col("x1").max().alias("line_x1_max"),
            pl.col("y0").max().alias("line_y0_max"),
            pl.col("text").str.join(" ").alias("text"),
        )
        .join(label_bounds, on="page", how="inner")
    )

    filters = (
        (pl.col("line_x0_min") >= (pl.col("label_x0_min") - x0_tolerance))
        & (pl.col("line_x1_max") <= (pl.col("label_x1_max") + x1_tolerance))
        & (pl.col("line_y0_max") > pl.col("label_y0_max"))
        & (
            (pl.col("block_no") != pl.col("block_no_right"))
            | (pl.col("line_no") != pl.col("line_no_right"))
        )
    )
    if max_y_gap is not None:
        filters = filters & (pl.col("line_y0_max") <= (pl.col("label_y0_max") + max_y_gap))

    return (
        line_candidates.filter(filters)
        .with_columns((pl.col("line_y0_max") - pl.col("label_y0_max")).alias("y_gap"))
        .sort(["page", "block_no_right", "line_no_right", "y_gap", "line_x0_min"])
        .group_by(["page", "block_no_right", "line_no_right"])
        .agg(pl.col("text").first().alias("text"))
        .select(["page", "text"])
        .sort("page")
    )


def _collapse_series_values(series: pl.Series) -> str | None:
    values = [str(value).strip() for value in series.to_list() if value is not None]
    values = [value for value in values if value]
    if not values:
        return None

    unique_values = list(dict.fromkeys(values))
    return ", ".join(unique_values)


def _full_join_on_page(left: pl.DataFrame, right: pl.DataFrame) -> pl.DataFrame:
    return (
        left.join(right, on="page", how="full")
        .with_columns(pl.coalesce(["page", "page_right"]).alias("page"))
        .drop("page_right")
    )


def _extract_rows(words_df: pl.DataFrame) -> pl.DataFrame:
    fields = [
        get_value_by_geometric(words_df, "59. Subpartida arancelaria").rename(
            {"text": "subpartida"}
        ),
        get_value_by_geometric(words_df, "77. Cantidad dcms.", x1_tolerance=35).rename(
            {"text": "cantidad"}
        ),
        get_value_by_geometric(words_df, "72. Peso neto kgs. dcms.", x1_tolerance=20).rename(
            {"text": "peso_neto"}
        ),
        get_value_by_geometric(words_df, "71. Peso bruto kgs. dcms.", x1_tolerance=20).rename(
            {"text": "peso_bruto"}
        ),
        get_value_by_geometric(words_df, "78.Valor FOB USD", x1_tolerance=35).rename(
            {"text": "fob_total"}
        ),
        get_value_by_geometric(words_df, _TOTAL_FIELDS["valor_flete"], x1_tolerance=60).rename(
            {"text": "valor_flete"}
        ),
        get_value_by_geometric(words_df, _TOTAL_FIELDS["valor_seguro"], x1_tolerance=40).rename(
            {"text": "valor_seguro"}
        ),
        get_value_by_geometric(words_df, _TOTAL_FIELDS["otros_gastos"], x1_tolerance=40).rename(
            {"text": "otros_gastos"}
        ),
        get_value_by_geometric(
            words_df,
            _INFORMATIVE_FIELDS["codigo_acuerdo"],
            x1_tolerance=80,
        ).rename({"text": "codigo_acuerdo"}),
        get_value_by_geometric(
            words_df, _INFORMATIVE_FIELDS["numero_formulario"], x1_tolerance=80
        ).rename({"text": "numero_formulario"}),
        get_value_by_geometric(
            words_df,
            _INFORMATIVE_FIELDS["numero_levante"],
            x0_tolerance=_NUMERO_LEVANTE_X0_TOLERANCE,
            x1_tolerance=_NUMERO_LEVANTE_X1_TOLERANCE,
            y0_tolerance=_NUMERO_LEVANTE_Y0_TOLERANCE,
            max_y_gap=_NUMERO_LEVANTE_MAX_Y_GAP,
        ).rename({"text": "numero_levante"}),
        get_nearest_value_by_geometric(
            words_df,
            "86. Número",
            x1_tolerance=_NUMERO_X1_TOLERANCE,
            max_y_gap=_NUMERO_MAX_Y_GAP,
        ).rename({"text": "numero"}),
    ]

    result = fields[0]
    for field_df in fields[1:]:
        result = _full_join_on_page(result, field_df)

    return result.with_columns(
        [_clean_dian_numeric_text(column).alias(column) for column in _ROW_NUMERIC_COLUMNS]
    ).sort("page")


def _extract_totals(rows_df: pl.DataFrame) -> dict[str, float | None]:
    totals: dict[str, float | None] = {}
    for key in _TOTAL_FIELDS:
        if key not in rows_df.columns:
            totals[key] = None
            continue

        values = rows_df.get_column(key).drop_nulls()
        totals[key] = None if values.is_empty() else round(float(values.sum()), 2)

    return totals


def _extract_informative_fields(rows_df: pl.DataFrame) -> dict[str, str | None]:
    informative_fields: dict[str, str | None] = {}
    for key in _ROW_TEXT_COLUMNS:
        if key not in rows_df.columns:
            informative_fields[key] = None
            continue
        informative_fields[key] = _collapse_series_values(rows_df.get_column(key))
    return informative_fields


def run(words_df: pl.DataFrame) -> dict[str, object]:
    rows_df = _extract_rows(words_df)
    return {
        "rows": rows_df,
        "totals": _extract_totals(rows_df),
        "informative_fields": _extract_informative_fields(rows_df),
    }
