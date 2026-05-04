import logging
import re

import polars as pl

logger = logging.getLogger(__name__)

_NUMERIC_COLUMNS = ["cantidad", "peso_neto", "peso_bruto", "fob_total"]


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
    df: pl.DataFrame, target_line: str, x0_tolerance: int = 0, x1_tolerance: int = 0
) -> pl.DataFrame:

    if not isinstance(df, pl.DataFrame):
        raise TypeError("df must be a polars DataFrame")

    if not isinstance(target_line, str):
        raise ValueError("target_line must be a non-empty string")

    if not isinstance(x0_tolerance, int):
        raise TypeError("x0_tolerance must be an int")

    if not isinstance(x1_tolerance, int):
        raise TypeError("x1_tolerance must be an int")

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

    filtered_candidates = (
        candidate_words.join(label_bounds, on=["page"], how="inner")
        .filter(
            (pl.col("cand_x0") > (pl.col("label_x0_min") - x0_tolerance))
            & (pl.col("cand_x0") < (pl.col("label_x1_max") + x1_tolerance))
            & (pl.col("cand_y0") > (pl.col("label_y0_max")))
        )
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


def run(words_df: pl.DataFrame) -> pl.DataFrame:

    subpartida_df = get_value_by_geometric(words_df, "59. Subpartida arancelaria")
    cantidad_df = get_value_by_geometric(words_df, "77. Cantidad dcms.", x1_tolerance=35)
    peso_neto_df = get_value_by_geometric(words_df, "72. Peso neto kgs. dcms.", x1_tolerance=20)
    peso_bruto_df = get_value_by_geometric(words_df, "71. Peso bruto kgs. dcms.", x1_tolerance=20)
    fob_df = get_value_by_geometric(words_df, "78.Valor FOB USD", x1_tolerance=35)

    subpartida_df = subpartida_df.rename({"text": "subpartida"})
    cantidad_df = cantidad_df.rename({"text": "cantidad"})
    peso_neto_df = peso_neto_df.rename({"text": "peso_neto"})
    peso_bruto_df = peso_bruto_df.rename({"text": "peso_bruto"})
    fob_df = fob_df.rename({"text": "fob_total"})

    result = (
        subpartida_df.join(cantidad_df, on="page", how="full")
        .with_columns(pl.coalesce(["page", "page_right"]).alias("page"))
        .drop("page_right")
        .join(peso_neto_df, on="page", how="full")
        .with_columns(pl.coalesce(["page", "page_right"]).alias("page"))
        .drop("page_right")
        .join(peso_bruto_df, on="page", how="full")
        .with_columns(pl.coalesce(["page", "page_right"]).alias("page"))
        .drop("page_right")
        .join(fob_df, on="page", how="full")
        .with_columns(pl.coalesce(["page", "page_right"]).alias("page"))
        .drop("page_right")
    )

    result = result.with_columns(
        [_clean_dian_numeric_text(column).alias(column) for column in _NUMERIC_COLUMNS]
    )

    return result.sort("page")
