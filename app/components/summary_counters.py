import streamlit as st


def summary_counters(counters: dict[str, int] | None) -> None:
    values = counters or {}

    total, matches, differences = st.columns(3)
    total.metric("Total", values.get("total", 0))
    matches.metric("Coincidencias", values.get("matches", 0))
    differences.metric("Diferencias", values.get("differences", 0))
