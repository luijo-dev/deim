import streamlit as st

COLUMN_LABELS = {
    "Estado": "Estado",
    "subpartida": "Subpartida",
    "codigo_acuerdo": "Codigo de acuerdo",
    "numero_formulario": "Numero de formulario",
    "numero_levante": "Numero de levante",
    "numero": "Numero",
    "dian_cantidad": "DIAN - Cantidad",
    "dian_peso_neto": "DIAN - Peso neto",
    "dian_peso_bruto": "DIAN - Peso bruto",
    "dian_fob_total": "DIAN - FOB total",
    "dian_valor_flete": "DIAN - Valor flete",
    "dian_valor_seguro": "DIAN - Valor seguro",
    "dian_otros_gastos": "DIAN - Otros gastos",
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
        width="stretch",
        hide_index=True,
        column_config={
            column: st.column_config.TextColumn(label)
            for column, label in COLUMN_LABELS.items()
        },
    )
