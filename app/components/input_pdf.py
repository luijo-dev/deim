import streamlit as st


def input_pdf(label: str, key: str):
    return st.file_uploader(label, type=["pdf"], key=key)
