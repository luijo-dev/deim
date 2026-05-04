import streamlit as st


def primary_button(label: str, key: str) -> bool:
    left, center, right = st.columns([1, 1, 1])

    with center:
        return st.button(label, key=key, type="primary", width="stretch")
