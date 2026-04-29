"""Extracción y utilidades para PDFs tipo plataforma (tablas)."""

from .chunk import chunk_words_subpartidas_hasta_anexos
from .summary import build_rows, summary_by_row

__all__ = ["chunk_words_subpartidas_hasta_anexos", "build_rows", "summary_by_row"]
