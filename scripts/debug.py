import json
import re
import sys
import time
import unicodedata
from pathlib import Path

# Al ejecutar `python scripts/debug.py`, sys.path incluye `scripts/`, no la raíz del repo.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import fitz  # noqa: E402
import polars as pl  # noqa: E402

from services.pdf_platform import (  # noqa: E402
    build_rows,
    chunk_words_subpartidas_hasta_anexos,
    summary_by_row,
)

pl.Config.set_tbl_rows(-1)  # todas las filas
pl.Config.set_tbl_cols(-1)  # todas las columnas
pl.Config.set_fmt_str_lengths(10_000)  # no recortar strings
pl.Config.set_tbl_width_chars(100)  # ancho grande para evitar "…"


RES_DIR = Path("/home/luijo/personal/jose-reyes/dian-declaracion-importacion/deim/res")
FOOTER_Y0_THRESHOLD = 630
_NUMERIC_MERCHANDISE_COLUMN_IDS = [
    "p_bruto",
    "p_neto",
    "cantidad",
    "valor_fob_total",
]
_NUMERIC_TEXT_REGEX = r"^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$"


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

_MERCANCIA_HEADER_CONFIG = [
    {"name": "Ref.", "x0_tolerance": 0, "x1_tolerance": 0, "is_align_left": True},
    {"name": "Embalaje", "x0_tolerance": 0, "x1_tolerance": 0, "is_align_left": True},
    {"name": "Descripción", "x0_tolerance": 0, "x1_tolerance": 0, "is_align_left": True},
    {"name": "P. Bruto", "x0_tolerance": 0, "x1_tolerance": 10, "is_align_left": False},
    {"name": "P. Neto", "x0_tolerance": 0, "x1_tolerance": 10, "is_align_left": False},
    {"name": "Cantidad", "x0_tolerance": 0, "x1_tolerance": 10, "is_align_left": False},
    {"name": "Valor FOB Total", "x0_tolerance": 0, "x1_tolerance": 10, "is_align_left": False},
    {"name": "Valor FOB Real", "x0_tolerance": 0, "x1_tolerance": 10, "is_align_left": False},
]

header_mercancia = [config["name"] for config in _MERCANCIA_HEADER_CONFIG]


def _normalize_header_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", normalized.lower())
    return normalized.strip("_")


def build_mercancia_header_ranges(
    mercancia_header_rows: list[dict[str, object]], header_mercancia: list[str]
) -> list[dict[str, object]]:
    config_by_name = {config["name"]: config for config in _MERCANCIA_HEADER_CONFIG}
    rows = sorted(
        mercancia_header_rows,
        key=lambda row: (
            int(row.get("page", 0)),
            int(row.get("row_id", 0)),
            float(row["x0"]),
        ),
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
            print(
                "Advertencia: no se pudo reconstruir la cabecera de mercancía "
                f"{header_name!r} desde la posición {cursor}."
            )
            continue

        window = rows[match_start : match_start + len(target_words)]

        header_config = config_by_name[header_name]
        header_range = {
            "name": header_name,
            "column_id": _normalize_header_name(header_name),
            "x0": min(float(row["x0"]) for row in window),
            "x1": max(float(row["x1"]) for row in window),
            "x0_tolerance": header_config["x0_tolerance"],
            "x1_tolerance": header_config["x1_tolerance"],
            "is_align_left": header_config["is_align_left"],
        }

        header_ranges.append(header_range)
        cursor = match_start + len(target_words)

    return header_ranges


def build_columns(
    df: pl.DataFrame, header_config: list[dict[str, object]]
) -> pl.DataFrame:
    """Asigna ``column_id`` y ``column_name`` por palabra usando rangos en X.

    Es la contraparte horizontal de ``build_rows``:
    - ``build_rows`` agrupa palabras por cercanía en ``y0`` para obtener ``row_id``.
    - ``build_columns`` toma rangos de cabecera ya reconstruidos y clasifica cada
      palabra por su posición horizontal.

    La transposición es intencional: en vez de decidir "a qué fila pertenece" una
    palabra mirando Y, decidimos "a qué columna pertenece" mirando X.

    Cada entrada de ``header_config`` define un rango base ``x0`` → ``x1`` y sus
    tolerancias. El rango efectivo queda así:
    - ``lower = x0 - x0_tolerance``
    - ``upper = x1 + x1_tolerance``

    La comparación depende de ``is_align_left``:
    - ``True``  → se compara ``x0`` de la palabra candidata contra el rango expandido.
      Esto sirve para columnas cuyo texto se alinea hacia la izquierda y conviene
      anclar la coincidencia en su borde izquierdo.
    - ``False`` → se compara ``x1`` de la palabra candidata contra el rango expandido.
      Esto sirve para columnas cuyo texto se alinea hacia la derecha y conviene
      anclar la coincidencia en su borde derecho.

    Si una palabra cae en más de un rango, gana la primera cabecera según el orden de
    ``header_config``. La función preserva cantidad de filas, columnas originales y
    orden original del DataFrame.
    """
    required = {"page", "x0", "x1", "text"}
    missing = required - set(df.columns)
    if missing:
        msg = f"df falta columnas requeridas para build_columns: {sorted(missing)}"
        raise ValueError(msg)

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

    return (
        result.sort("_original_order").drop("_original_order")
    )


def _clean_numeric_text_expr(column_name: str = "text") -> pl.Expr:
    return (
        pl.col(column_name)
        .str.strip_chars()
        .str.replace(r"^\$", "")
        .str.replace_all(r"^[\.\-–—'\"“”‘’`:;\s]+", "")
        .str.replace_all(r"[\.\-–—'\"“”‘’`:;\s]+$", "")
    )


def select_numeric_merchandise_columns(df: pl.DataFrame) -> pl.DataFrame:
    return (
        df.filter(pl.col("column_id").is_in(_NUMERIC_MERCHANDISE_COLUMN_IDS))
        .with_columns(
            _clean_numeric_text_expr().alias("text_numeric_cleaned")
        )
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
    """Contrato base debug para valores de plataforma consumible luego por dian_vs_platform."""
    required = {"page", "row_id", "column_id", "column_value", "subpartida_code"}
    missing = required - set(df.columns)
    if missing:
        msg = (
            "df falta columnas requeridas para build_platform_values_contract: "
            f"{sorted(missing)}"
        )
        raise ValueError(msg)

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
    """Adapta el contrato largo debug a la forma ancha comparable de plataforma."""
    required = {"page", "row_id", "column_id", "value", "subpartida"}
    missing = required - set(df.columns)
    if missing:
        msg = f"df falta columnas requeridas para platform_df_adapter: {sorted(missing)}"
        raise ValueError(msg)

    required_column_ids = ["p_bruto", "p_neto", "cantidad", "valor_fob_total"]

    return (
        df.filter(pl.col("column_id").is_in(required_column_ids))
        .group_by(["page", "row_id", "subpartida"], maintain_order=True)
        .agg(
            [
                pl.col("value")
                .filter(pl.col("column_id") == column_id)
                .first()
                .alias(column_id)
                for column_id in required_column_ids
            ]
        )
        .filter(pl.all_horizontal(pl.col(required_column_ids).is_not_null()))
        .select(["subpartida", *required_column_ids])
    )


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
        .filter(pl.col("text").str.strip_chars().str.contains(header_text))
        .unique(subset=["page", "row_id"], maintain_order=True)
        .head(1)
    )

    if header_line.is_empty():
        return []

    header = header_line.row(0, named=True)

    return (
        df.filter(
            (pl.col("page") == header["page"])
            & (pl.col("row_id") == header["row_id"])
        )
        .sort("x0")
        .select(["page", "row_id", "x0", "x1", "text"])
        .to_dicts()
    )


if __name__ == "__main__":
    t0_total = time.perf_counter()
    file_name = sys.argv[1]

    t0_words = time.perf_counter()
    words_df = words_dataframe(file_name, [1])
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
        #print("--- primeras 30 filas del chunk (orden lectura) ---")
        #print(chunk_sorted.head(30))
        #print("--- últimas 15 filas del chunk ---")
        #print(chunk_sorted.tail(15))

        #print("============ build_rows (página × y0 tolerancia): =============")
        rows_df = build_rows(platform_words_df, y_tolerance=2)
        print(rows_df.head(1000))
        #print("============ summary_by_row (concat por row_id): =============")
        summary_df = summary_by_row(rows_df)
        print(summary_df.head(1000))
        
        ############################################################################
        
        print("============ header rows: subpartida =============")
        
        header_subpartida = ["Subpartida", "Descripción", "Unidad", "Comercial", "Cantidad"]
        header_subpartida_str = " ".join(header_subpartida)
        print(header_subpartida_str)
        
        subpartida_header_rows = find_header_rows(
            rows_df, header_subpartida_str
        )
        print(subpartida_header_rows)
        print("============ header rows: mercancía =============")
        
        # Defibi la primera parte de la cabecera de la mercancía
        header_mercancia_1 = header_mercancia[:-1]
        header_mercancia_str_1 = " ".join(header_mercancia_1)
        print("header_mercancia_str_1: ", header_mercancia_str_1)
        
        # Busca la primera parte de la cabecera de la mercancía
        mercancia_header_rows_1 = find_header_rows(
            rows_df, header_mercancia_str_1
        )
        
        # Define la segunda parte de la cabecera de la mercancía
        header_mercancia_2 = header_mercancia[-2:]
        header_mercancia_str_2 = " ".join(header_mercancia_2)
        print("mercancia_header_rows_2: ", header_mercancia_str_2)
        
        # Busca la segunda parte de la cabecera de la mercancía
        mercancia_header_rows_2 = find_header_rows(
            rows_df, header_mercancia_str_2
        )
        
        # Combina las dos partes de la cabecera de la mercancía
        mercancia_header_rows = mercancia_header_rows_1 + mercancia_header_rows_2
         
        print(mercancia_header_rows)
        
        mercancia_header_ranges = build_mercancia_header_ranges(
            mercancia_header_rows, header_mercancia
        )
        print(json.dumps(mercancia_header_ranges, indent=4))

        print("============ build_columns (asignación por X): =============")
        rows_with_subpartida_id = add_subpartida_id(rows_df)
        print("============ add_subpartida_id (chunk por Subpartidas): =============")
        print(rows_with_subpartida_id.head(30))

        print("============ add_subpartida_code (código por subpartida): =============")
        rows_with_subpartida_code = add_subpartida_code(rows_with_subpartida_id)
        print(rows_with_subpartida_code.head(1000))

        columns_df = build_columns(rows_with_subpartida_code, mercancia_header_ranges)
        numeric_columns_df = select_numeric_merchandise_columns(columns_df)
        print(
            numeric_columns_df.select(
                [
                    "page",
                    "row_id",
                    "x0",
                    "x1",
                    "text",
                    "column_id",
                    "column_name",
                    "column_value",
                    "subpartida_code",
                ]
            )
        )

        platform_values_contract_df = build_platform_values_contract(numeric_columns_df)
        print("============ platform values contract (base debug): =============")
        print(platform_values_contract_df)

        platform_df = platform_df_adapter(platform_values_contract_df)
        print("============ platform df (wide comparable shape): =============")
        print(platform_df)
        
        rows_df.write_csv("./res/rows_df.csv")
        rows_with_subpartida_code.write_csv("./res/rows_with_subpartida_code.csv")
        numeric_columns_df.write_csv("./res/numeric_columns_df.csv")
        platform_values_contract_df.write_csv("./res/platform_values_contract.csv")
        platform_df.write_csv("./res/platform_df.csv")
