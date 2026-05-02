import streamlit as st

COLUMN_LABELS = {
    "Estado": "Estado",
    "subpartida": "Subpartida",
    "dian_cantidad": "DIAN - Cantidad",
    "dian_peso_neto": "DIAN - Peso neto",
    "dian_peso_bruto": "DIAN - Peso bruto",
    "dian_fob_total": "DIAN - FOB total",
    "cliente_cantidad": "Cliente - Cantidad",
    "cliente_peso_neto": "Cliente - Peso neto",
    "cliente_peso_bruto": "Cliente - Peso bruto",
    "cliente_fob_total": "Cliente - FOB total",
}


def results_table(rows: list[dict] | None) -> None:
    if not rows:
        st.caption("Sin resultados para mostrar.")
        return

    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
        column_config={
            column: st.column_config.TextColumn(label)
            for column, label in COLUMN_LABELS.items()
        },
    )
