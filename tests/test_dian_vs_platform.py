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

    def fake_words_dataframe_from_bytes(pdf_bytes: bytes, filter_footer: bool = True) -> str:
        calls.append(("words", pdf_bytes, filter_footer))
        return f"words:{pdf_bytes.decode()}"

    def fake_dian_run(words_df: str) -> pl.DataFrame:
        assert words_df == "words:dian"
        return {
            "rows": pl.DataFrame(
                {
                    "subpartida": ["1234567890", "1234567890"],
                    "cantidad": [5.0, 1.0],
                    "peso_neto": [90.0, 10.0],
                    "peso_bruto": [100.0, 20.0],
                    "fob_total": [2500.0, 500.0],
                    "valor_flete": [10.0, 2.0],
                    "valor_seguro": [5.0, 1.0],
                    "otros_gastos": [1.0, 0.5],
                    "codigo_acuerdo": ["XXX", "XXX"],
                    "numero_formulario": ["F-1", None],
                    "numero_levante": [None, "LV-9"],
                    "numero": ["AAAA", "BBBB"],
                }
            ),
            "totals": {
                "valor_flete": 999.0,
                "valor_seguro": 999.0,
                "otros_gastos": 999.0,
            },
            "informative_fields": {
                "codigo_acuerdo": "XXX",
                "numero_formulario": "F-1",
                "numero": "AAAA, BBBB",
            },
        }

    def fake_platform_run(words_df: str) -> dict:
        assert words_df == "words:platform"
        calls.append(("platform_run", words_df))
        return {
            "rows": pl.DataFrame(
                {
                    "subpartida": ["1234567890"],
                    "cantidad": [5.0],
                    "peso_neto": [90.0],
                    "peso_bruto": [100.0],
                    "fob_total": [2500.0],
                }
            ),
            "totals": {
                "valor_flete": 10.0,
                "valor_seguro": 5.0,
                "otros_gastos": 1.0,
            },
            "informative_fields": {"valor_cif_us": 68816.17},
        }

    monkeypatch.setattr(
        dian_vs_platform, "words_dataframe_from_bytes", fake_words_dataframe_from_bytes
    )
    monkeypatch.setattr(dian_vs_platform.dian_extractor, "run", fake_dian_run)
    monkeypatch.setattr(dian_vs_platform.platform_extractor, "run", fake_platform_run)

    result = dian_vs_platform.run(b"dian", b"platform")

    assert calls == [
        ("words", b"dian", False),
        ("words", b"platform", True),
        ("platform_run", "words:platform"),
    ]
    assert result["counters"] == {
        "total": 1,
        "Sin match": 0,
        "Todo bien": 0,
        "Con diferencias": 1,
    }
    assert result["columns"] == dian_vs_platform.RESULT_COLUMNS
    assert result["rows"] == [
        {
            "Estado": "Con diferencias",
            "subpartida": "1234567890",
            "codigo_acuerdo": "XXX",
            "numero_formulario": "F-1",
            "numero_levante": "LV-9",
            "numero": "AAAA, BBBB",
            "dian_cantidad": 6.0,
            "dian_peso_neto": 100.0,
            "dian_peso_bruto": 120.0,
            "dian_fob_total": 3000.0,
            "dian_valor_flete": 12.0,
            "dian_valor_seguro": 6.0,
            "dian_otros_gastos": 1.5,
            "cliente_cantidad": 5.0,
            "cliente_peso_neto": 90.0,
            "cliente_peso_bruto": 100.0,
            "cliente_fob_total": 2500.0,
        }
    ]
    assert result["totals"] == [
        {
            "key": "valor_flete",
            "label": "Valor flete",
            "dian_value": 12.0,
            "platform_value": 10.0,
            "dian_missing": False,
            "platform_missing": False,
            "status": "Con diferencias",
        },
        {
            "key": "valor_seguro",
            "label": "Valor seguro",
            "dian_value": 6.0,
            "platform_value": 5.0,
            "dian_missing": False,
            "platform_missing": False,
            "status": "Con diferencias",
        },
        {
            "key": "otros_gastos",
            "label": "Otros gastos",
            "dian_value": 1.5,
            "platform_value": 1.0,
            "dian_missing": False,
            "platform_missing": False,
            "status": "Con diferencias",
        },
    ]
    assert result["informative_fields"] == [
        {
            "key": "valor_cif_us",
            "label": "Valor CIF US",
            "dian_value": None,
            "platform_value": 68816.17,
            "dian_missing": True,
            "platform_missing": False,
        },
    ]


def test_run_uses_empty_platform_dataframe_when_bytes_are_missing(monkeypatch):
    calls = []

    def fake_words_dataframe_from_bytes(pdf_bytes: bytes, filter_footer: bool = True) -> str:
        calls.append(("words", pdf_bytes, filter_footer))
        return "words:dian"

    def fake_dian_run(words_df: str) -> dict:
        assert words_df == "words:dian"
        return {
            "rows": pl.DataFrame(
                {
                    "subpartida": ["1234567890"],
                    "cantidad": [5.0],
                    "peso_neto": [90.0],
                    "peso_bruto": [100.0],
                    "fob_total": [2500.0],
                    "valor_flete": [10.0],
                    "valor_seguro": [5.0],
                    "otros_gastos": [1.0],
                    "codigo_acuerdo": ["XXX"],
                }
            ),
            "totals": {"valor_flete": 999.0, "valor_seguro": 999.0, "otros_gastos": 999.0},
            "informative_fields": {"codigo_acuerdo": "XXX"},
        }

    def fake_platform_run(words_df: str) -> dict:
        calls.append(("platform_run", words_df))
        return {"rows": pl.DataFrame(), "totals": {}, "informative_fields": {}}

    monkeypatch.setattr(
        dian_vs_platform, "words_dataframe_from_bytes", fake_words_dataframe_from_bytes
    )
    monkeypatch.setattr(dian_vs_platform.dian_extractor, "run", fake_dian_run)
    monkeypatch.setattr(dian_vs_platform.platform_extractor, "run", fake_platform_run)

    result = dian_vs_platform.run(b"dian")

    assert calls == [("words", b"dian", False)]
    assert result["counters"] == {
        "total": 1,
        "Sin match": 1,
        "Todo bien": 0,
        "Con diferencias": 0,
    }
    assert result["rows"] == [
        {
            "Estado": "Sin match",
            "subpartida": "1234567890",
            "codigo_acuerdo": "XXX",
            "numero_formulario": None,
            "numero_levante": None,
            "numero": None,
            "dian_cantidad": 5.0,
            "dian_peso_neto": 90.0,
            "dian_peso_bruto": 100.0,
            "dian_fob_total": 2500.0,
            "dian_valor_flete": 10.0,
            "dian_valor_seguro": 5.0,
            "dian_otros_gastos": 1.0,
            "cliente_cantidad": None,
            "cliente_peso_neto": None,
            "cliente_peso_bruto": None,
            "cliente_fob_total": None,
        }
    ]
    assert result["totals"] == [
        {
            "key": "valor_flete",
            "label": "Valor flete",
            "dian_value": 10.0,
            "platform_value": None,
            "dian_missing": False,
            "platform_missing": True,
            "status": "Sin match",
        },
        {
            "key": "valor_seguro",
            "label": "Valor seguro",
            "dian_value": 5.0,
            "platform_value": None,
            "dian_missing": False,
            "platform_missing": True,
            "status": "Sin match",
        },
        {
            "key": "otros_gastos",
            "label": "Otros gastos",
            "dian_value": 1.0,
            "platform_value": None,
            "dian_missing": False,
            "platform_missing": True,
            "status": "Sin match",
        },
    ]
    assert result["informative_fields"] == [
        {
            "key": "valor_cif_us",
            "label": "Valor CIF US",
            "dian_value": None,
            "platform_value": None,
            "dian_missing": True,
            "platform_missing": True,
        },
    ]
