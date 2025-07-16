import streamlit as st
import pdfplumber
import pandas as pd
from datetime import datetime, timedelta

st.set_page_config(page_title="Conversor Cartão de Ponto")
st.title("Conversor Cartão de Ponto ➜ CSV")

uploaded_file = st.file_uploader("Envie seu PDF de cartão de ponto", type="pdf")
if uploaded_file:
    with pdfplumber.open(uploaded_file) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)

    linhas = [ln.strip() for ln in text.split("\n") if ln.strip()]
    registros = {}

    for ln in linhas:
        partes = ln.split()
        if len(partes) >= 3 and "/" in partes[0]:
