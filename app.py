import streamlit as st
import pdfplumber
import pandas as pd
import re
from datetime import datetime

st.set_page_config(page_title="CONVERSOR DE CARTÃO DE PONTO ➜ CSV")
st.markdown("<h1 style='text-align: center;'>📅 CONVERSOR DE CARTÃO DE PONTO ➜ CSV</h1>", unsafe_allow_html=True)

uploaded_file = st.file_uploader("Envie seu PDF de cartão de ponto", type="pdf")

ocorrencias_que_zeram = [
    "D.S.R", "FERIADO", "FALTA", "ATESTADO", "DISPENSA", "SAÍDA", "ATRASO", 
    "INTEGRAÇÃO", "FÉRIAS"
]

def extrair_datas_e_horarios(texto):
    linhas = texto.split("\n")
    dados_extraidos = []

    for linha in linhas:
        if re.search(r"\d{2}/\d{2}/\d{4}", linha):
            partes = linha.split()
            data = partes[0]

            # Filtrar ocorrências conhecidas
            ocorrencia_texto = " ".join(partes[2:])
            if any(ocorr in ocorrencia_texto.upper() for ocorr in ocorrencias_que_zeram):
                dados_extraidos.append({
                    "Data": data,
                    "Entrada 1": "", "Saída 1": "",
                    "Entrada 2": "", "Saída 2": ""
                })
                continue

            horarios_validos = re.findall(r"\b\d{2}:\d{2}\b", " ".join(partes[1:]))

            # Evita usar horários que estão só na coluna de ocorrências (últimas posições)
            if len(horarios_validos) >= 2:
                horarios_validos = horarios_validos[:4]  # Máximo de 2 entradas e 2 saídas

                # Se só tiver 1 horário, ignora (não pode ter linha com só 1 entrada ou só 1 saída)
                if len(horarios_validos) == 1:
                    continue

                linha_dict = {"Data": data}
                for i in range(4):
                    chave = ["Entrada 1", "Saída 1", "Entrada 2", "Saída 2"][i]
                    linha_dict[chave] = horarios_validos[i] if i < len(horarios_validos) else ""
                dados_extraidos.append(linha_dict)
            else:
                # Nenhum horário útil
                dados_extraidos.append({
                    "Data": data,
                    "Entrada 1": "", "Saída 1": "",
                    "Entrada 2": "", "Saída 2": ""
                })

    return dados_extraidos

if uploaded_file is not None:
    with pdfplumber.open(uploaded_file) as pdf:
        texto = ""
        for pagina in pdf.pages:
            texto += pagina.extract_text() + "\n"

    registros = extrair_datas_e_horarios(texto)

    if registros:
        df = pd.DataFrame(registros)
        st.success("Conversão concluída com sucesso!")
        st.dataframe(df)

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Baixar CSV",
            data=csv,
            file_name="cartao_ponto_convertido.csv",
            mime="text/csv"
        )
    else:
        st.warning("Nenhum dado válido encontrado no PDF.")

st.markdown("<hr><p style='text-align: center;'>Desenvolvido por Lucas de Matos Coelho</p>", unsafe_allow_html=True)
