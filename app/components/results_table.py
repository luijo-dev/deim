import streamlit as st


def results_table(rows: list[dict] | None) -> None:
    if not rows:
        st.caption("Sin resultados para mostrar.")
        return

    st.dataframe(rows, use_container_width=True, hide_index=True)
