from __future__ import annotations

import polars as pl


def build_rows(df: pl.DataFrame, y_tolerance: int = 2) -> pl.DataFrame:
    """Asigna ``row_id`` por palabra, agrupando por cercanía en ``y0``.

    - ordena por ``page``, ``y0``, ``x0``, ``line_no``, ``word_no``.
    - crea grupos de línea cuando el salto vertical supera ``y_tolerance``.
    - agrega ``row_id`` usando solo el grupo de línea dentro de cada página.

    Devuelve solo columnas útiles para depuración: ``page``, coordenadas, ``text`` y ``row_id``.
    """
    if y_tolerance < 0:
        raise ValueError("y_tolerance debe ser >= 0")

    required = {"page", "x0", "y0", "x1", "y1", "text", "line_no", "word_no"}
    missing = required - set(df.columns)
    if missing:
        msg = f"df falta columnas requeridas: {sorted(missing)}"
        raise ValueError(msg)

    sort_cols = ["page", "y0", "x0", "line_no", "word_no"]
    return (
        df.sort(sort_cols)
        .with_columns(
            (
                pl.col("y0")
                .diff()
                .over("page")
                .fill_null(y_tolerance + 1)
                .abs()
                .gt(y_tolerance)
                .cast(pl.Int64)
                .cum_sum()
                .over("page")
            ).alias("line_group")
        )
        .with_columns(pl.col("line_group").alias("row_id"))
        .select(["page", "x0", "y0", "x1", "y1", "text", "row_id"])
    )


def summary_by_row(df: pl.DataFrame) -> pl.DataFrame:
    """Concatena ``text`` por ``row_id`` para obtener una fila legible."""
    required = {"page", "row_id", "y0", "x0", "text"}
    missing = required - set(df.columns)
    if missing:
        msg = f"df falta columnas requeridas para summary_by_row: {sorted(missing)}"
        raise ValueError(msg)

    return (
        df.sort(["page", "row_id", "y0", "x0"])
        .group_by(["page", "row_id"], maintain_order=True)
        .agg(
            pl.col("y0").min().alias("y0_min"),
            pl.col("text").str.join(" ").alias("line_text"),
        )
        .select(["page", "row_id", "y0_min", "line_text"])
    )
