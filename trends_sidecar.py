"""Standalone Trends lab: python -m streamlit run trends_sidecar.py --server.port 8502."""

import streamlit as st

from src.ui.theme import inject_theme
from src.ui.views.google_trends import render

st.set_page_config(page_title="Google Trends · Sidecar", layout="wide")
inject_theme()
st.title("Search attention")
st.caption("Independent Google Trends collector test")
render()
