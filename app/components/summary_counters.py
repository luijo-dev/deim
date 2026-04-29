import streamlit as st


def summary_counters(counters: dict[str, int] | None) -> None:
    values = counters or {}

    ordered_labels = ["total", *[key for key in values if key != "total"]]
    if not ordered_labels:
        ordered_labels = ["total"]

    columns = st.columns(len(ordered_labels))
    for column, label in zip(columns, ordered_labels, strict=True):
        column.metric(label, values.get(label, 0))
