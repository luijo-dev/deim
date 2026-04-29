import sys
import time
from pathlib import Path

import fitz
import polars as pl

pl.Config.set_tbl_rows(-1)  # todas las filas
pl.Config.set_tbl_cols(-1)  # todas las columnas
pl.Config.set_fmt_str_lengths(10_000)  # no recortar strings
pl.Config.set_tbl_width_chars(10_000)  # ancho grande para evitar "…"


RES_DIR = Path("/home/luijo/personal/jose-reyes/dian-declaracion-importacion/res")


def _resolve_pdf_path(pdf_name: str) -> Path:
    return RES_DIR / pdf_name


def _available_pages(doc: fitz.Document, pages: list[int] | None = None) -> list[int]:
    if not pages:
        return list(range(doc.page_count))
    return [p - 1 for p in pages if 1 <= p <= doc.page_count]


def words_dataframe(pdf_name: str, pages: list[int] | None = None) -> pl.DataFrame:
    pdf_path = _resolve_pdf_path(pdf_name)
    rows: list[dict[str, int | float | str]] = []

    with fitz.open(pdf_path) as doc:
        for page_idx in _available_pages(doc, pages):
            page = doc[page_idx]
            for word in page.get_text("words"):
                if len(word) < 8:
                    continue
                rows.append(
                    {
                        "page_number": page_idx + 1,
                        "x0": float(word[0]),
                        "y0": float(word[1]),
                        "x1": float(word[2]),
                        "y1": float(word[3]),
                        "text": str(word[4]),
                        "block_no": int(word[5]),
                        "line_no": int(word[6]),
                        "word_no": int(word[7]),
                    }
                )

    return pl.DataFrame(rows).with_columns(
        pl.col("x0").floor().cast(pl.Int64),
        pl.col("y0").floor().cast(pl.Int64),
        pl.col("x1").floor().cast(pl.Int64),
        pl.col("y1").floor().cast(pl.Int64),
    )


def text_dataframe(pdf_name: str, pages: list[int] | None = None) -> pl.DataFrame:
    pdf_path = _resolve_pdf_path(pdf_name)
    rows: list[dict[str, int | str]] = []

    with fitz.open(pdf_path) as doc:
        for page_idx in _available_pages(doc, pages):
            page = doc[page_idx]
            rows.append(
                {
                    "page_number": page_idx + 1,
                    "text": str(page.get_text("text")),
                }
            )

    return pl.DataFrame(rows)


def text_series(pdf_name: str, pages: list[int] | None = None) -> pl.Series:
    return text_dataframe(pdf_name, pages)["text"]


def get_value_by_gemetri(
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

    keys = ["page_number", "block_no", "line_no"]

    line_matches = (
        df.sort(keys + ["word_no"])
        .group_by(keys)
        .agg(pl.col("text").str.join(" ").alias("line_text"))
        .filter(pl.col("line_text").str.starts_with(target_line))
        .select(keys)
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
        pl.col("y1").max().alias("label_y1_max"),
    )

    candidate_words = df.select(
        [
            pl.col("page_number"),
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

    value_candidates = (
        candidate_words.join(label_bounds, on=["page_number"], how="inner")
        .filter(
            (pl.col("cand_x0") > (pl.col("label_x0_min") - x0_tolerance))
            & (pl.col("cand_x0") < (pl.col("label_x1_max") + x1_tolerance))
            & (pl.col("cand_y0") > pl.col("label_y1_max"))
        )
        .sort(["page_number", "block_no", "line_no", "cand_y0", "cand_x0", "cand_word_no"])
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

    result_df = pl.concat([label_df, value_candidates], how="vertical").sort(
        keys + ["kind", "word_no"]
    )
    return (
        result_df.filter(pl.col("kind") == "value")
        .select(pl.col("page_number").alias("page"), pl.col("text"))
        .sort("page")
    )


if __name__ == "__main__":
    t0_total = time.perf_counter()
    file_name = sys.argv[1]

    t0_words = time.perf_counter()
    words_df = words_dataframe(file_name)
    t1_words = time.perf_counter()

    t0_subpartida = time.perf_counter()

    subpartida_df = get_value_by_gemetri(words_df, "59. Subpartida arancelaria")
    cantidad_df = get_value_by_gemetri(words_df, "77. Cantidad dcms.", x1_tolerance=20)
    peso_neto_df = get_value_by_gemetri(words_df, "72. Peso neto kgs.", x1_tolerance=20)
    peso_bruto_df = get_value_by_gemetri(words_df, "71. Peso bruto kgs.", x1_tolerance=20)
    fob_df = get_value_by_gemetri(words_df, "78.Valor FOB USD", x1_tolerance=50)

    t1_subpartida = time.perf_counter()

    t1_total = time.perf_counter()
    print("============ timings (s): =============")
    print(f"words_dataframe: {t1_words - t0_words:.4f}")
    print(f"get_subpartida: {t1_subpartida - t0_subpartida:.4f}")
    print(f"total: {t1_total - t0_total:.4f}")

    print("============ All_df: =============")
    # Hacer un join de los tres dataframes
    subpartida_df = subpartida_df.rename({"text": "subpartida"})
    cantidad_df = cantidad_df.rename({"text": "cantidad"})
    peso_neto_df = peso_neto_df.rename({"text": "peso_neto"})
    peso_bruto_df = peso_bruto_df.rename({"text": "peso_bruto_df"})
    fob_df = fob_df.rename({"text": "fob"})

    all_df = (
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
        .sort("page")
    )
    print(all_df)

    # filtered_df.write_csv("filtered_df.csv")
