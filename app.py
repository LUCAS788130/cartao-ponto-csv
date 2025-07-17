import streamlit as st
import pandas as pd
import fitz  # PyMuPDF
import io
from datetime import datetime
import re

st.set_page_config(page_title="Conversor de Cartão de Ponto → CSV", page_icon="🕐")

st.markdown(
    """
    <h1 style='font-size: 2.2em; text-align: center;'>🕐 CONVERSOR DE CARTÃO DE PONTO → CSV</h1>
    <p style='text-align: center;'>Envie um PDF de cartão de ponto</p>
    """,
    unsafe_allow_html=True
)

uploaded_file = st.file_uploader("Envie seu PDF de cartão de ponto", type=["pdf"])

if uploaded_file:
    text = ""
    try:
        with fitz.open(stream=uploaded_file.read(), filetype="pdf") as doc:
            for page in doc:
                text += page.get_text()
    except Exception as e:
        st.error("Erro ao ler o PDF: " + str(e))

    def extrair_linhas(texto):
        linhas = texto.split("\n")
        padrao_data = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")
        linhas_validas = [linha for linha in linhas if padrao_data.search(linha)]
        return linhas_validas

    def processar_texto(linhas):
        registros = []
        padrao_data = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")
        ocorrencias = [
            "D.S.R", "ATESTADO", "FERIADO", "FÉRIAS", "COMPENSA",
            "LICENÇA", "FOLGA", "FOLGOU", "ABON", "SUSPENS", "AUSÊNCIA"
        ]

        for linha in linhas:
            partes = linha.strip().split()
            data = None
            horarios = []

            for i, parte in enumerate(partes):
                if re.match(r"\d{2}/\d{2}/\d{4}", parte):
                    data = parte
                    horarios = partes[i+1:]
                    break

            ignorar = any(oc in linha.upper() for oc in ocorrencias)

            if data:
                if ignorar:
                    registros.append([data] + [""] * 12)
                else:
                    horarios_filtrados = [h for h in horarios if re.match(r"\d{2}:\d{2}", h)]
                    horarios_ajustados = horarios_filtrados[:12] + [""] * (12 - len(horarios_filtrados))
                    registros.append([data] + horarios_ajustados)

        return registros

    linhas_extraidas = extrair_linhas(text)
    registros = processar_texto(linhas_extraidas)

    if registros:
        colunas = ["Data"] + [f"{x}{i}" for i in range(1, 7) for x in ("Entrada", "Saída")]
        df = pd.DataFrame(registros, columns=colunas)

        st.markdown("### 📄 Resultado:")
        st.dataframe(df, use_container_width=True)

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Baixar CSV", data=csv, file_name="cartao_ponto.csv", mime="text/csv")
    else:
        st.warning("⚠️ Nenhum registro válido encontrado.")

st.markdown("---")
st.markdown(
    """
    <small>
    🔒 Este site processa arquivos apenas temporariamente para gerar planilhas. Nenhum dado é armazenado ou compartilhado.<br>
    <a href="#">Clique aqui para ver a Política de Privacidade</a><br>
    👨‍💻 Desenvolvido por <strong>Lucas de Matos Coelho</strong>
    </small>
    """,
    unsafe_allow_html=True
)
