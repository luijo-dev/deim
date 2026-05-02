import polars as pl

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

    result = run(df)

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
    assert row_p2["cantidad"] == "2222"


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

    result = run(df)

    assert result.shape[0] == 1
    assert result["page"][0] == 1
    assert result["subpartida"][0] == "1234.56"
    assert result["cantidad"][0] == "99"
    assert result["fob_total"][0] == "5000"
    assert "fob_total" in result.columns
    assert "fob" not in result.columns
