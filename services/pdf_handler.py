from pathlib import Path

import fitz
import polars as pl

pl.Config.set_tbl_rows(-1)  # todas las filas
pl.Config.set_tbl_cols(-1)  # todas las columnas
pl.Config.set_fmt_str_lengths(10_000)  # no recortar strings
pl.Config.set_tbl_width_chars(10_000)  # ancho grande para evitar "…"


RES_DIR = Path("/home/luijo/personal/jose-reyes/dian-declaracion-importacion/res")
WORDS_SCHEMA = {
    "page_number": pl.Int64,
    "x0": pl.Int64,
    "y0": pl.Int64,
    "x1": pl.Int64,
    "y1": pl.Int64,
    "text": pl.String,
    "block_no": pl.Int64,
    "line_no": pl.Int64,
    "word_no": pl.Int64,
}


def _resolve_pdf_path(pdf_name: str) -> Path:
    return RES_DIR / pdf_name


def _available_pages(doc: fitz.Document, pages: list[int] | None = None) -> list[int]:
    if not pages:
        return list(range(doc.page_count))
    return [p - 1 for p in pages if 1 <= p <= doc.page_count]


def _words_dataframe_from_document(
    doc: fitz.Document, pages: list[int] | None = None
) -> pl.DataFrame:
    rows: list[dict[str, int | float | str]] = []

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

    if not rows:
        return pl.DataFrame(schema=WORDS_SCHEMA)

    return pl.DataFrame(rows).with_columns(
        pl.col("x0").floor().cast(pl.Int64),
        pl.col("y0").floor().cast(pl.Int64),
        pl.col("x1").floor().cast(pl.Int64),
        pl.col("y1").floor().cast(pl.Int64),
    )


def words_dataframe_from_bytes(
    pdf_bytes: bytes, pages: list[int] | None = None
) -> pl.DataFrame:
    if not pdf_bytes:
        raise ValueError("El PDF cargado está vacío o no contiene bytes legibles.")

    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            return _words_dataframe_from_document(doc, pages)
    except Exception as exc:
        raise ValueError("No fue posible leer el PDF cargado.") from exc


def words_dataframe(pdf_name: str, pages: list[int] | None = None) -> pl.DataFrame:
    pdf_path = _resolve_pdf_path(pdf_name)

    with fitz.open(pdf_path) as doc:
        return _words_dataframe_from_document(doc, pages)
