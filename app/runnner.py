import streamlit as st

from app.page import render_page


def run() -> None:
    st.set_page_config(page_title="Comparador DEIM - MVP", layout="centered")
    render_page()
