import streamlit as st
import pdfplumber
import pandas as pd
from datetime import datetime, timedelta

st.set_page_config(page_title="Conversor Cartão de Ponto ➜ CSV")
st.title("📅 Conversor Cartão de Ponto ➜ CSV")

uploaded_file = st.file_uploader("Envie seu PDF de cartão de ponto", type="pdf")
if uploaded_file:
    with pdfplumber.open(uploaded_file) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    linhas = [linha.strip() for linha in text.split("\n") if linha.strip()]
    registros = {}

    for ln in linhas:
        partes = ln.split()
        if len(partes) >= 2 and "/" in partes[0]:
            try:
                data = datetime.strptime(partes[0],
