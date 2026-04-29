import streamlit as st

from app.components.input_pdf import input_pdf as input_pdf_component
from app.components.message_box import message_box as message_box_component
from app.components.primary_button import primary_button as primary_button_component
from app.components.results_table import results_table as results_table_component
from app.components.summary_counters import (
    summary_counters as summary_counters_component,
)
from services import dian_vs_platform


def render_page() -> None:
    st.title("Comparador DEIM - MVP")
    st.caption(
        "Carga el PDF DIAN para revisar la comparación básica. "
        "Platform es opcional temporalmente."
    )

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
        if not dian_pdf:
            message = "Carga el documento DIAN (PDF) para ejecutar la comparación."
            message_kind = "warning"
        else:
            try:
                platform_pdf_bytes = client_pdf.getvalue() if client_pdf else None
                result = dian_vs_platform.run(dian_pdf.getvalue(), platform_pdf_bytes)
            except Exception as exc:
                message = f"No fue posible ejecutar la comparación: {exc}"
                message_kind = "error"
            else:
                message = result.get("message")
                message_kind = result.get("message_kind", "info")
                if not client_pdf:
                    message = (
                        f"{message} Platform no se cargó; comparación contra "
                        "Platform vacío temporal."
                    )
                counters = result.get("counters")
                rows = result.get("rows")

    message_box_component(message, message_kind)
    summary_counters_component(counters)
    results_table_component(rows)
