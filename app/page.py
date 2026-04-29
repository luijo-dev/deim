import streamlit as st

from app.components.input_pdf import input_pdf as input_pdf_component
from app.components.message_box import message_box as message_box_component
from app.components.primary_button import primary_button as primary_button_component
from app.components.results_table import results_table as results_table_component
from app.components.summary_counters import (
    summary_counters as summary_counters_component,
)


def render_page() -> None:
    st.title("Comparador DEIM - MVP")
    st.caption("Carga dos documentos PDF para revisar la comparación básica.")

    left, right = st.columns(2)
    with left:
        dian_pdf = input_pdf_component("Documento DIAN (PDF)", key="dian_pdf")
    with right:
        client_pdf = input_pdf_component(
            "Documento plataforma/cliente (PDF)", key="client_pdf"
        )

    message = None
    message_kind = "info"
    counters: dict[str, int] | None = None
    rows: list[dict] | None = None

    if primary_button_component("Ejecutar comparación", key="run_comparison"):
        if not dian_pdf or not client_pdf:
            message = "Carga ambos documentos PDF para ejecutar la comparación."
            message_kind = "warning"
        else:
            message = (
                "La comparación visual está lista; "
                "el flujo de extracción queda pendiente de conexión."
            )
            counters = {"total": 0, "matches": 0, "differences": 0}
            rows = []

    message_box_component(message, message_kind)
    summary_counters_component(counters)
    results_table_component(rows)
