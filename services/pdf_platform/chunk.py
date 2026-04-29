from __future__ import annotations

import polars as pl

_SUBPARTIDAS = "Subpartidas"
_ANEXOS = "Anexos"


def chunk_words_subpartidas_hasta_anexos(df: pl.DataFrame) -> pl.DataFrame:
    """Recorta ``words_df`` al tramo útil entre la primera ``Subpartidas`` y ``Anexos``.

    Orden de lectura: ``page``, luego ``y0`` (más confiable que ``block_no``),
    y desempate con ``x0``, ``block_no``, ``line_no``, ``word_no``.

    - Se eliminan todas las palabras **antes** de la primera aparición de ``Subpartidas``.
    - Se eliminan la palabra ``Anexos`` y todo lo que venga **después** en ese orden.

    Si no hay ``Subpartidas``, devuelve un DataFrame vacío con el mismo esquema.
    Si no hay ``Anexos`` después de la primera ``Subpartidas``, se conserva desde
    ``Subpartidas`` hasta el final del documento ordenado.
    """
    required = {
        "page",
        "y0",
        "x0",
        "text",
        "block_no",
        "line_no",
        "word_no",
    }
    missing = required - set(df.columns)
    if missing:
        msg = f"df falta columnas requeridas: {sorted(missing)}"
        raise ValueError(msg)

    sort_cols = ["page", "y0", "x0", "block_no", "line_no", "word_no"]
    ordered = df.sort(sort_cols)
    with_idx = ordered.with_row_index("_idx")

    first_sub = with_idx.filter(pl.col("text") == _SUBPARTIDAS).select("_idx")
    if first_sub.is_empty():
        return df.head(0)

    first_sub_idx = int(first_sub.min().item())

    after_sub = with_idx.filter(pl.col("_idx") >= first_sub_idx)
    anexos_rows = after_sub.filter(pl.col("text") == _ANEXOS).select("_idx")

    if anexos_rows.is_empty():
        return after_sub.drop("_idx")

    first_anex_idx = int(anexos_rows.min().item())
    return with_idx.filter(
        (pl.col("_idx") >= first_sub_idx) & (pl.col("_idx") < first_anex_idx)
    ).drop("_idx")
