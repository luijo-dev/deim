import sys
import time
from pathlib import Path

# Al ejecutar `python scripts/debug.py`, sys.path incluye `scripts/`, no la raíz del repo.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import fitz
import polars as pl

from services.pdf_platform import build_rows, chunk_words_subpartidas_hasta_anexos, summary_by_row

pl.Config.set_tbl_rows(-1)  # todas las filas
pl.Config.set_tbl_cols(-1)  # todas las columnas
pl.Config.set_fmt_str_lengths(10_000)  # no recortar strings
pl.Config.set_tbl_width_chars(100)  # ancho grande para evitar "…"


RES_DIR = Path("/home/luijo/personal/jose-reyes/dian-declaracion-importacion/res")
FOOTER_Y0_THRESHOLD = 630


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
                        "page": page_idx + 1,
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

    return (
        pl.DataFrame(rows)
        .with_columns(
            pl.col("x0").floor().cast(pl.Int64),
            pl.col("y0").floor().cast(pl.Int64),
            pl.col("x1").floor().cast(pl.Int64),
            pl.col("y1").floor().cast(pl.Int64),
        )
        .filter(pl.col("y0") <= FOOTER_Y0_THRESHOLD)
    )


_READ_ORDER = ["page", "y0", "x0", "block_no", "line_no", "word_no"]


def add_subpartida_id(df: pl.DataFrame) -> pl.DataFrame:
    required = {"page", "x0", "y0", "x1", "y1", "text", "row_id"}
    missing = required - set(df.columns)
    if missing:
        msg = f"df falta columnas requeridas para add_subpartida_id: {sorted(missing)}"
        raise ValueError(msg)

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
        msg = f"df falta columnas requeridas para add_subpartida_code: {sorted(missing)}"
        raise ValueError(msg)

    row_texts = (
        df.sort(["subpartida_id", "page", "row_id", "x0"])
        .group_by(["subpartida_id", "page", "row_id"], maintain_order=True)
        .agg(pl.col("text").str.join(" ").alias("line_text"))
        .with_columns(pl.int_range(pl.len()).over("subpartida_id").alias("row_pos"))
    )

    description_rows = (
        row_texts.filter(
            pl.col("line_text")
            .str.strip_chars()
            .str.starts_with("Descripción de la Mercancía")
        )
        .group_by("subpartida_id")
        .agg(pl.col("row_pos").min().alias("description_row_pos"))
    )

    codes = (
        row_texts.join(description_rows, on="subpartida_id", how="inner")
        .filter(pl.col("row_pos") < pl.col("description_row_pos"))
        .with_columns(
            pl.col("line_text").str.extract(r"^(\d{10})\s", 1).alias("subpartida_code")
        )
        .filter(pl.col("subpartida_code").is_not_null())
        .group_by("subpartida_id", maintain_order=True)
        .agg(pl.col("subpartida_code").last())
    )

    return df.join(codes, on="subpartida_id", how="left")


def find_header_rows(df: pl.DataFrame, header_text: str) -> list[dict[str, object]]:
    header_line = (
        df.sort(["page", "row_id", "x0"])
        .group_by(["page", "row_id"], maintain_order=True)
        .agg(
            pl.col("text").str.join(" ").alias("text"),
        )
        .filter(pl.col("text").str.strip_chars().str.starts_with(header_text))
        .unique(subset=["page", "row_id"], maintain_order=True)
        .head(1)
    )

    if header_line.is_empty():
        return []

    header = header_line.row(0, named=True)
    header_words = header_text.split()

    return (
        df.filter(
            (pl.col("page") == header["page"])
            & (pl.col("row_id") == header["row_id"])
            & (pl.col("text").is_in(header_words))
        )
        .sort("x0")
        .select(["x0", "x1", "text"])
        .to_dicts()
    )


if __name__ == "__main__":
    t0_total = time.perf_counter()
    file_name = sys.argv[1]

    t0_words = time.perf_counter()
    words_df = words_dataframe(file_name, [1, 2])
    t1_words = time.perf_counter()

    t0_platform_chunk = time.perf_counter()
    platform_words_df = chunk_words_subpartidas_hasta_anexos(words_df)
    t1_platform_chunk = time.perf_counter()

    t1_total = time.perf_counter()
    print("============ timings (s): =============")
    print(f"words_dataframe: {t1_words - t0_words:.4f}")
    print(f"chunk_words_subpartidas_hasta_anexos: {t1_platform_chunk - t0_platform_chunk:.4f}")
    print(f"total: {t1_total - t0_total:.4f}")

    print("============ pdf_platform chunk (Subpartidas → Anexos): =============")
    print(f"words_df rows: {words_df.height} | platform_words_df rows: {platform_words_df.height}")
    if platform_words_df.is_empty():
        print("(vacío: no hubo 'Subpartidas' o no hay tramo antes de 'Anexos')")
    else:
        chunk_sorted = platform_words_df.sort(_READ_ORDER)
        print("--- primeras 30 filas del chunk (orden lectura) ---")
        print(chunk_sorted.head(30))
        print("--- últimas 15 filas del chunk ---")
        print(chunk_sorted.tail(15))

        print("============ build_rows (página × y0 tolerancia): =============")
        rows_df = build_rows(platform_words_df, y_tolerance=2)
        print(rows_df.head(30))
        print("============ summary_by_row (concat por row_id): =============")
        summary_df = summary_by_row(rows_df)
        print(summary_df.head(30))
        print("============ header rows: subpartida =============")
        subpartida_header_rows = find_header_rows(
            rows_df, "Subpartida Descripción Unidad Comercial Cantidad"
        )
        print(subpartida_header_rows)
        print("============ header rows: mercancía =============")
        mercancia_header_rows = find_header_rows(
            rows_df, "Ref. Embalaje Descripción P. Bruto P. Neto Cantidad"
        )
        print(mercancia_header_rows)
        print("============ add_subpartida_id (chunk por Subpartidas): =============")
        rows_with_subpartida_id = add_subpartida_id(rows_df)
        print(rows_with_subpartida_id.head(30))
        print("============ add_subpartida_code (código por subpartida): =============")
        rows_with_subpartida_code = add_subpartida_code(rows_with_subpartida_id)
        print(rows_with_subpartida_code.head(60))
