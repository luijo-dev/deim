import streamlit as st

COLUMN_LABELS = {
    "Estado": "Estado",
    "subpartida": "Subpartida",
    "cantidad": "DIAN - Cantidad",
    "peso_neto": "DIAN - Peso neto",
    "peso_bruto": "DIAN - Peso bruto",
    "fob_total": "DIAN - FOB total",
    "Plat - cantidad": "Cliente - Cantidad",
    "Plat - peso_neto": "Cliente - Peso neto",
    "Plat - peso_bruto": "Cliente - Peso bruto",
    "Plat - fob_total": "Cliente - FOB total",
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
