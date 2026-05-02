import sys
from pathlib import Path

# Al ejecutar `python scripts/debug.py`, sys.path incluye `scripts/`, no la raíz del repo.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import fitz  # noqa: E402
import polars as pl  # noqa: E402

from services.pdf_platform import (  # noqa: E402
    extractor as platform_extractor,
)

pl.Config.set_tbl_rows(-1)  # todas las filas
pl.Config.set_tbl_cols(-1)  # todas las columnas
pl.Config.set_fmt_str_lengths(10_000)  # no recortar strings
pl.Config.set_tbl_width_chars(100)  # ancho grande para evitar "…"


RES_DIR = Path("/home/luijo/personal/jose-reyes/dian-declaracion-importacion/deim/res")
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


if __name__ == "__main__":
    file_name = sys.argv[1]
    words_df = words_dataframe(file_name)
    platform_df = platform_extractor.run(words_df)
    print(platform_df)
    platform_df.write_csv("./res/platform_df.csv")
