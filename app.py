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

            # Identifica se é linha com ocorrências que anulam a jornada
            linha_upper = linha.upper()
            tem_ocorrencia = any(palavra in linha_upper for palavra in [
                "D.S.R", "FERIADO", "FALTA", "ATESTADO", "DISPENSA", "SAÍDA", "ATRASO"
            ])

            if tem_ocorrencia:
                registros.append((data_str, []))  # Zera horários
                continue

            # Senão, extrai os horários normais (antes da parte de ocorrência)
            partes = re.split(r"\s+(HORA|D\.S\.R|FALTA|FERIADO|ATESTADO|DISPENSA|SA[IÍ]DA|ATRASO)", linha)
            parte_marcacoes = partes[0]

            horarios = re.findall(r"\d{2}:\d{2}[a-z]?", parte_marcacoes)
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
    df["Data"] = pd.to_datetime(df["Data"], dayfirst=True)

    data_inicio = df["Data"].min()
    data_fim = df["Data"].max()
    todas_datas = gerar_datas_completas(data_inicio, data_fim)

    registros_dict = {data.strftime("%d/%m/%Y"): horarios for data, horarios in zip(df["Data"], df["Horários"])}

    estrutura = {
        "Data": [],
        "Entrada1": [], "Saída1": [],
        "Entrada2": [], "Saída2": []
    }

    for data in todas_datas:
        estrutura["Data"].append(data)
        horarios = registros_dict.get(data, [])

        pares = horarios[:4] + [''] * (4 - len(horarios))  # até 4 horários
        estrutura["Entrada1"].append(pares[0])
        estrutura["Saída1"].append(pares[1])
        estrutura["Entrada2"].append(pares[2])
        estrutura["Saída2"].append(pares[3])

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
