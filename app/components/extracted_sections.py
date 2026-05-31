import streamlit as st


def _display_value(value: object, missing: bool) -> str:
    if missing:
        return "0"
    return str(value)


def _render_source(label: str, value: object, missing: bool) -> None:
    st.markdown(f"**{label}:** {_display_value(value, missing)}")
    if missing:
        st.caption("no encontrado")


def totals_section(items: list[dict] | None) -> None:
    if not items:
        return

    st.subheader("Totales comparados")
    for item in items:
        with st.container(border=True):
            st.markdown(f"**{item['label']}**")
            left, center, right = st.columns([1, 1, 1])
            with left:
                _render_source("DIAN", item.get("dian_value"), bool(item.get("dian_missing")))
            with center:
                _render_source(
                    "Platform",
                    item.get("platform_value"),
                    bool(item.get("platform_missing")),
                )
            with right:
                st.markdown(f"**Estado:** {item.get('status', 'Sin match')}")


def informative_fields_section(items: list[dict] | None) -> None:
    if not items:
        return

    st.subheader("Datos extraídos")
    for item in items:
        with st.container(border=True):
            st.markdown(f"**{item['label']}**")
            left, right = st.columns(2)
            with left:
                _render_source("DIAN", item.get("dian_value"), bool(item.get("dian_missing")))
            with right:
                _render_source(
                    "Platform",
                    item.get("platform_value"),
                    bool(item.get("platform_missing")),
                )
