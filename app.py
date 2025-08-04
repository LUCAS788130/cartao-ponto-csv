import streamlit as st
import pdfplumber
import pandas as pd
import re
from datetime import datetime, timedelta

st.set_page_config(page_title="CARTÃO DE PONTO ➜ CSV")
st.markdown("<h1 style='text-align: center;'>🕒 CONVERSOR DE CARTÃO DE PONTO</h1>", unsafe_allow_html=True)

uploaded_file = st.file_uploader("📎 Envie o cartão de ponto em PDF", type="pdf")

def extrair_datas_e_marcacoes(texto):
    linhas = texto.split("\n")
    registros = []

    for linha in linhas:
        match = re.match(r"(\d{2}/\d{2}/\d{4})", linha)
        if match:
            data_str = match.group(1)
            horarios = re.findall(r"\d{2}:\d{2}[a-z]?", linha)
            horarios = [h.replace('r', '').replace('g', '').replace('c', '') for h in horarios]
            horarios = [h for h in horarios if re.match(r"\d{2}:\d{2}", h)]
            registros.append((data_str, horarios))

    return registros

def gerar_datas_completas(inicio, fim):
    datas = []
    atual = inicio
    while atual <= fim:
        datas.append(atual.strftime("%d/%m/%Y"))
        atual += timedelta(days=1)
    return datas

def organizar_jornada(registros):
    df = pd.DataFrame(registros, columns=["Data", "Horários"])

    data_inicio = datetime.strptime(df["Data"].iloc[0], "%d/%m/%Y")
    data_fim = datetime.strptime(df["Data"].iloc[-1], "%d/%m/%Y")
    todas_datas = gerar_datas_completas(data_inicio, data_fim)

    estrutura = {
        "Data": [],
        "Entrada1": [], "Saída1": [],
        "Entrada2": [], "Saída2": []
    }

    registros_dict = dict(registros)

    for data in todas_datas:
        estrutura["Data"].append(data)
        horarios = registros_dict.get(data, [])

        pares = horarios[:4] + [''] * (4 - len(horarios))  # Garante 4 colunas
        estrutura["Entrada1"].append(pares[0] if len(pares) > 0 else '')
        estrutura["Saída1"].append(pares[1] if len(pares) > 1 else '')
        estrutura["Entrada2"].append(pares[2] if len(pares) > 2 else '')
        estrutura["Saída2"].append(pares[3] if len(pares) > 3 else '')

    return pd.DataFrame(estrutura)

if uploaded_file:
    with pdfplumber.open(uploaded_file) as pdf:
        texto_total = ""
        for pagina in pdf.pages:
            texto_total += pagina.extract_text() + "\n"

    registros = extrair_datas_e_marcacoes(texto_total)
    df_jornada = organizar_jornada(registros)

    st.success("✅ Jornada extraída com sucesso!")
    st.dataframe(df_jornada)

    csv = df_jornada.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Baixar CSV",
        data=csv,
        file_name="jornada_extraida.csv",
        mime="text/csv"
    )
