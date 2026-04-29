import sys
import time
from pathlib import Path

# Al ejecutar `python scripts/debug.py`, sys.path incluye `scripts/`, no la raíz del repo.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import fitz
import polars as pl

from services.pdf_platform import chunk_words_subpartidas_hasta_anexos

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


_READ_ORDER = ["page_number", "y0", "x0", "block_no", "line_no", "word_no"]


if __name__ == "__main__":
    t0_total = time.perf_counter()
    file_name = sys.argv[1]

    t0_words = time.perf_counter()
    words_df = words_dataframe(file_name)
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
