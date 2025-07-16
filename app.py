import streamlit as st
import pdfplumber
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Conversor Cartão de Ponto")
st.title("Conversor Cartão de Ponto ➜ CSV")

uploaded_file = st.file_uploader("Envie seu PDF de cartão de ponto", type="pdf")
if uploaded_file:
    with pdfplumber.open(uploaded_file) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    linhas = [ln.strip() for ln in text.split("\n") if ln.strip()]
    registros = {}

    for ln in linhas:
        partes = ln.split()
        if len(partes) >= 3 and "/" in partes[0]:
            try:
                datetime.strptime(partes[0], "%d/%m/%Y")  # valida data
                data = partes[0]
                entrada = partes[1] if ":" in partes[1] else ""
                saida = partes[2] if ":" in partes[2] else ""
                registros[data] = (entrada, saida)
            except Exception:
                pass

    if registros:
        datas_convertidas = [datetime.strptime(d, "%d/%m/%Y") for d in registros.keys()]
        start, end = min(datas_convertidas), max(datas_convertidas)

        datas_corridas = list(pd.date_range(start=start, end=end))
        linhas_saida = []

        for d in datas_corridas:
            data_str = d.strftime("%d/%m/%Y")
            entrada, saida = registros.get(data_str, ("", ""))
            linhas_saida.append({"Data": data_str, "Entrada": entrada, "Saída": saida})

        df = pd.DataFrame(linhas_saida)
        st.subheader("📋 Resultado:")
