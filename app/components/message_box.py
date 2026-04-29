import streamlit as st


def message_box(message: str | None, kind: str = "info") -> None:
    if not message:
        return

    renderers = {
        "success": st.success,
        "error": st.error,
        "warning": st.warning,
        "info": st.info,
    }
    render = renderers.get(kind, st.info)
    render(message)
