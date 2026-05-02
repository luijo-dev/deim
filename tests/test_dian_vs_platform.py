import polars as pl

from services import dian_vs_platform
from services.pdf_platform.extractor import platform_df_adapter


def test_platform_df_adapter_returns_comparable_contract_columns():
    df = pl.DataFrame(
        {
            "page": [1, 1, 1, 1],
            "row_id": [10, 10, 10, 10],
            "column_id": ["p_bruto", "p_neto", "cantidad", "valor_fob_total"],
            "value": [100.0, 90.0, 5.0, 2500.0],
            "subpartida": ["1234567890", "1234567890", "1234567890", "1234567890"],
        }
    )

    result = platform_df_adapter(df)

    assert result.columns == [
        "subpartida",
        "peso_bruto",
        "peso_neto",
        "cantidad",
        "fob_total",
    ]
    assert result.to_dicts() == [
        {
            "subpartida": "1234567890",
            "peso_bruto": 100.0,
            "peso_neto": 90.0,
            "cantidad": 5.0,
            "fob_total": 2500.0,
        }
    ]


def test_platform_df_adapter_excludes_legacy_fob_real_field():
    df = pl.DataFrame(
        {
            "page": [1, 1, 1, 1, 1],
            "row_id": [10, 10, 10, 10, 10],
            "column_id": [
                "p_bruto",
                "p_neto",
                "cantidad",
                "valor_fob_total",
                "valor_fob_real",
            ],
            "value": [100.0, 90.0, 5.0, 2500.0, 2600.0],
            "subpartida": ["1234567890", "1234567890", "1234567890", "1234567890", "1234567890"],
        }
    )

    result = platform_df_adapter(df)

    assert "valor_fob_real" not in result.columns
    assert "fob_real" not in result.columns
    assert result["fob_total"][0] == 2500.0


def test_run_uses_uploaded_platform_pdf_bytes(monkeypatch):
    calls = []

    def fake_words_dataframe_from_bytes(pdf_bytes: bytes) -> str:
        calls.append(("words", pdf_bytes))
        return f"words:{pdf_bytes.decode()}"

    def fake_dian_run(words_df: str) -> pl.DataFrame:
        assert words_df == "words:dian"
        return pl.DataFrame(
            {
                "subpartida": ["1234567890"],
                "cantidad": [5.0],
                "peso_neto": [90.0],
                "peso_bruto": [100.0],
                "fob_total": [2500.0],
            }
        )

    def fake_platform_run(words_df: str) -> pl.DataFrame:
        assert words_df == "words:platform"
        calls.append(("platform_run", words_df))
        return pl.DataFrame(
            {
                "subpartida": ["1234567890"],
                "cantidad": [5.0],
                "peso_neto": [90.0],
                "peso_bruto": [100.0],
                "fob_total": [2500.0],
            }
        )

    monkeypatch.setattr(
        dian_vs_platform, "words_dataframe_from_bytes", fake_words_dataframe_from_bytes
    )
    monkeypatch.setattr(dian_vs_platform.dian_extractor, "run", fake_dian_run)
    monkeypatch.setattr(dian_vs_platform.platform_extractor, "run", fake_platform_run)

    result = dian_vs_platform.run(b"dian", b"platform")

    assert calls == [
        ("words", b"dian"),
        ("words", b"platform"),
        ("platform_run", "words:platform"),
    ]
    assert result["counters"] == {
        "total": 1,
        "Sin match": 0,
        "Todo bien": 1,
        "Con diferencias": 0,
    }
    assert result["columns"] == [
        "Estado",
        "subpartida",
        "cantidad",
        "peso_neto",
        "peso_bruto",
        "fob_total",
        "Platform",
    ]


def test_run_uses_empty_platform_dataframe_when_bytes_are_missing(monkeypatch):
    calls = []

    def fake_words_dataframe_from_bytes(pdf_bytes: bytes) -> str:
        calls.append(("words", pdf_bytes))
        return "words:dian"

    def fake_dian_run(words_df: str) -> pl.DataFrame:
        assert words_df == "words:dian"
        return pl.DataFrame(
            {
                "subpartida": ["1234567890"],
                "cantidad": [5.0],
                "peso_neto": [90.0],
                "peso_bruto": [100.0],
                "fob_total": [2500.0],
            }
        )

    def fake_platform_run(words_df: str) -> pl.DataFrame:
        calls.append(("platform_run", words_df))
        return pl.DataFrame()

    monkeypatch.setattr(
        dian_vs_platform, "words_dataframe_from_bytes", fake_words_dataframe_from_bytes
    )
    monkeypatch.setattr(dian_vs_platform.dian_extractor, "run", fake_dian_run)
    monkeypatch.setattr(dian_vs_platform.platform_extractor, "run", fake_platform_run)

    result = dian_vs_platform.run(b"dian")

    assert calls == [("words", b"dian")]
    assert result["counters"] == {
        "total": 1,
        "Sin match": 1,
        "Todo bien": 0,
        "Con diferencias": 0,
    }
