import fitz
import polars as pl

from services import pdf_handler
from services.pdf_dian.extractor import get_value_by_geometric, run


def _make_df(rows: list[dict]) -> pl.DataFrame:
    """Build a words DataFrame matching the schema emitted by pdf_handler."""
    schema = {
        "page": pl.Int64,
        "x0": pl.Int64,
        "y0": pl.Int64,
        "x1": pl.Int64,
        "y1": pl.Int64,
        "text": pl.String,
        "block_no": pl.Int64,
        "line_no": pl.Int64,
        "word_no": pl.Int64,
    }
    return pl.DataFrame(rows, schema=schema)


def _row(
    page: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    text: str,
    block_no: int,
    line_no: int,
    word_no: int,
) -> dict:
    return {
        "page": page,
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
        "text": text,
        "block_no": block_no,
        "line_no": line_no,
        "word_no": word_no,
    }


def test_get_value_by_geometric_finds_value_next_to_label():
    """Regression: extractor must work with 'page' column from pdf_handler."""
    df = _make_df(
        [
            _row(1, 10, 10, 50, 20, "59.", 1, 1, 1),
            _row(1, 55, 10, 150, 20, "Subpartida", 1, 1, 2),
            _row(1, 155, 10, 250, 20, "arancelaria", 1, 1, 3),
            # value sits below the label, slightly indented so cand_x0 > label_x0_min
            _row(1, 15, 25, 85, 35, "1234.56", 1, 2, 1),
        ]
    )

    result = get_value_by_geometric(df, "59. Subpartida arancelaria")

    assert result.shape[0] == 1
    assert result["text"][0] == "1234.56"
    assert result["page"][0] == 1


def test_get_value_by_geometric_no_match_returns_empty():
    df = _make_df(
        [
            _row(1, 10, 10, 50, 20, "Other", 1, 1, 1),
        ]
    )

    result = get_value_by_geometric(df, "59. Subpartida arancelaria")

    assert result.shape[0] == 0


def test_get_value_by_geometric_with_x1_tolerance():
    """Value to the right of the label (outside default x1) is found when tolerance is given."""
    df = _make_df(
        [
            _row(1, 10, 10, 50, 20, "78.", 1, 1, 1),
            _row(1, 55, 10, 100, 20, "Valor", 1, 1, 2),
            _row(1, 105, 10, 130, 20, "FOB", 1, 1, 3),
            _row(1, 135, 10, 160, 20, "USD", 1, 1, 4),
            # value is far to the right, needs x1_tolerance=50 (as used by fob in run)
            _row(1, 180, 25, 250, 35, "5000", 1, 2, 1),
        ]
    )

    result = get_value_by_geometric(df, "78. Valor FOB USD", x1_tolerance=50)

    assert result.shape[0] == 1
    assert result["text"][0] == "5000"


def test_run_with_multiple_pages():
    """run() should return one row per page when labels exist on different pages."""
    df = _make_df(
        [
            # Page 1: subpartida only
            _row(1, 10, 10, 50, 20, "59.", 1, 1, 1),
            _row(1, 55, 10, 150, 20, "Subpartida", 1, 1, 2),
            _row(1, 155, 10, 250, 20, "arancelaria", 1, 1, 3),
            _row(1, 15, 25, 85, 35, "1111", 1, 2, 1),
            # Page 2: cantidad only
            _row(2, 10, 10, 50, 20, "77.", 1, 1, 1),
            _row(2, 55, 10, 100, 20, "Cantidad", 1, 1, 2),
            _row(2, 105, 10, 140, 20, "dcms.", 1, 1, 3),
            _row(2, 15, 25, 80, 35, "2222", 1, 2, 1),
        ]
    )

    result = run(df)["rows"]

    assert result.shape[0] == 2
    pages = sorted(result["page"].to_list())
    assert pages == [1, 2]
    # Page 1 has subpartida but no cantidad
    row_p1 = result.filter(pl.col("page") == 1).to_dicts()[0]
    assert row_p1["subpartida"] == "1111"
    assert row_p1["cantidad"] is None
    # Page 2 has cantidad but no subpartida
    row_p2 = result.filter(pl.col("page") == 2).to_dicts()[0]
    assert row_p2["subpartida"] is None
    assert row_p2["cantidad"] == 2222.0


def test_run_combines_multiple_fields_with_fob_total_contract():
    """End-to-end: run() should join subpartida, cantidad, peso, and fob_total by page."""
    df = _make_df(
        [
            # Label + value for subpartida
            _row(1, 10, 10, 50, 20, "59.", 1, 1, 1),
            _row(1, 55, 10, 150, 20, "Subpartida", 1, 1, 2),
            _row(1, 155, 10, 250, 20, "arancelaria", 1, 1, 3),
            _row(1, 15, 25, 85, 35, "1234.56", 1, 2, 1),
            # Label + value for cantidad
            _row(1, 10, 50, 50, 60, "77.", 1, 3, 1),
            _row(1, 55, 50, 100, 60, "Cantidad", 1, 3, 2),
            _row(1, 105, 50, 140, 60, "dcms.", 1, 3, 3),
            _row(1, 15, 65, 80, 75, "99", 1, 4, 1),
            # Label + value for FOB total
            _row(1, 10, 90, 100, 100, "78.Valor", 1, 5, 1),
            _row(1, 105, 90, 130, 100, "FOB", 1, 5, 2),
            _row(1, 135, 90, 160, 100, "USD", 1, 5, 3),
            _row(1, 180, 105, 250, 115, "5000", 1, 6, 1),
        ]
    )

    result = run(df)["rows"]

    assert result.shape[0] == 1
    assert result["page"][0] == 1
    assert result["subpartida"][0] == "1234.56"
    assert result["cantidad"][0] == 99.0
    assert result["fob_total"][0] == 5000.0
    assert result["valor_flete"][0] is None
    assert result["codigo_acuerdo"][0] is None
    assert "fob_total" in result.columns
    assert "fob" not in result.columns


def test_run_returns_row_level_totals_and_informative_fields_contract():
    df = _make_df(
        [
            _row(1, 10, 10, 50, 20, "59.", 1, 1, 1),
            _row(1, 55, 10, 150, 20, "Subpartida", 1, 1, 2),
            _row(1, 155, 10, 250, 20, "arancelaria", 1, 1, 3),
            _row(1, 15, 25, 85, 35, "1234", 1, 2, 1),
            _row(1, 10, 50, 50, 60, "79.", 1, 3, 1),
            _row(1, 55, 50, 100, 60, "Valor", 1, 3, 2),
            _row(1, 105, 50, 150, 60, "fletes", 1, 3, 3),
            _row(1, 155, 50, 180, 60, "USD", 1, 3, 4),
            _row(1, 15, 65, 80, 75, "12.5", 1, 4, 1),
            _row(1, 10, 90, 50, 100, "80.", 1, 5, 1),
            _row(1, 55, 90, 100, 100, "Valor", 1, 5, 2),
            _row(1, 105, 90, 160, 100, "Seguros", 1, 5, 3),
            _row(1, 165, 90, 190, 100, "USD", 1, 5, 4),
            _row(1, 15, 105, 80, 115, "7.5", 1, 6, 1),
            _row(1, 10, 130, 50, 140, "81.", 1, 7, 1),
            _row(1, 55, 130, 100, 140, "Valor", 1, 7, 2),
            _row(1, 105, 130, 150, 140, "Otros", 1, 7, 3),
            _row(1, 155, 130, 200, 140, "Gastos", 1, 7, 4),
            _row(1, 205, 130, 230, 140, "USD", 1, 7, 5),
            _row(1, 15, 145, 80, 155, "3", 1, 8, 1),
            _row(1, 250, 10, 290, 20, "67.", 2, 1, 1),
            _row(1, 295, 10, 330, 20, "Cod.", 2, 1, 2),
            _row(1, 335, 10, 390, 20, "Acuerdo", 2, 1, 3),
            _row(1, 255, 25, 305, 35, "XXX", 2, 2, 1),
            _row(1, 250, 50, 260, 60, "4.", 2, 3, 1),
            _row(1, 265, 50, 320, 60, "Numero", 2, 3, 2),
            _row(1, 325, 50, 355, 60, "de", 2, 3, 3),
            _row(1, 360, 50, 450, 60, "formulario", 2, 3, 4),
            _row(1, 255, 65, 360, 75, "482026000170219-1", 2, 4, 1),
        ]
    )

    result = run(df)

    assert result["rows"].shape[0] == 1
    row = result["rows"].to_dicts()[0]
    assert row["valor_flete"] == 12.5
    assert row["valor_seguro"] == 7.5
    assert row["otros_gastos"] == 3.0
    assert row["codigo_acuerdo"] == "XXX"
    assert row["numero_formulario"] == "482026000170219-1"
    assert row["numero_levante"] is None
    assert row["numero"] is None
    assert result["totals"] == {
        "valor_flete": 12.5,
        "valor_seguro": 7.5,
        "otros_gastos": 3.0,
    }
    assert result["informative_fields"]["codigo_acuerdo"] == "XXX"
    assert result["informative_fields"]["numero_formulario"] == "482026000170219-1"
    assert result["informative_fields"]["numero_levante"] is None


def test_run_extracts_numero_levante_without_capturing_title_below():
    df = _make_df(
        [
            _row(1, 250, 10, 285, 20, "134.", 2, 1, 1),
            _row(1, 290, 10, 350, 20, "Levante", 2, 1, 2),
            _row(1, 355, 10, 385, 20, "No.", 2, 1, 3),
            _row(1, 430, 8, 520, 18, "LV-9001", 2, 2, 1),
            _row(1, 250, 35, 370, 45, "Firma", 2, 3, 1),
            _row(1, 375, 35, 560, 45, "declarante", 2, 3, 2),
        ]
    )

    result = run(df)

    assert result["informative_fields"]["numero_levante"] == "LV-9001"


def test_words_dataframe_from_bytes_can_bypass_footer_filter():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "encabezado")
    page.insert_text((72, 695), "numero_levante")

    try:
        pdf_bytes = doc.tobytes()
    finally:
        doc.close()

    default_df = pdf_handler.words_dataframe_from_bytes(pdf_bytes)
    unfiltered_df = pdf_handler.words_dataframe_from_bytes(pdf_bytes, filter_footer=False)

    assert "encabezado" in default_df["text"].to_list()
    assert "numero_levante" not in default_df["text"].to_list()
    assert "numero_levante" in unfiltered_df["text"].to_list()


def test_run_extracts_numero_as_full_text_from_nearest_lower_line():
    df = _make_df(
        [
            _row(1, 250, 10, 285, 20, "86.", 2, 1, 1),
            _row(1, 290, 10, 360, 20, "Número", 2, 1, 2),
            _row(1, 365, 35, 390, 45, "XXXX", 2, 2, 1),
            _row(1, 395, 35, 420, 45, "YYYY", 2, 2, 2),
            _row(1, 425, 35, 430, 45, "ZZZZ", 2, 2, 3),
        ]
    )

    result = run(df)

    assert result["informative_fields"]["numero"] == "XXXX YYYY ZZZZ"


def test_run_returns_row_level_fields_for_multiple_pages_without_global_copy():
    df = _make_df(
        [
            _row(1, 10, 10, 50, 20, "59.", 1, 1, 1),
            _row(1, 55, 10, 150, 20, "Subpartida", 1, 1, 2),
            _row(1, 155, 10, 250, 20, "arancelaria", 1, 1, 3),
            _row(1, 15, 25, 85, 35, "1111", 1, 2, 1),
            _row(1, 250, 10, 290, 20, "67.", 2, 1, 1),
            _row(1, 295, 10, 330, 20, "Cod.", 2, 1, 2),
            _row(1, 335, 10, 390, 20, "Acuerdo", 2, 1, 3),
            _row(1, 255, 25, 305, 35, "AAA", 2, 2, 1),
            _row(2, 10, 10, 50, 20, "59.", 1, 1, 1),
            _row(2, 55, 10, 150, 20, "Subpartida", 1, 1, 2),
            _row(2, 155, 10, 250, 20, "arancelaria", 1, 1, 3),
            _row(2, 15, 25, 85, 35, "2222", 1, 2, 1),
        ]
    )

    result = run(df)["rows"].sort("page").to_dicts()

    assert result[0]["subpartida"] == "1111"
    assert result[0]["codigo_acuerdo"] == "AAA"
    assert result[1]["subpartida"] == "2222"
    assert result[1]["codigo_acuerdo"] is None
