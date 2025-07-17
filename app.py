import streamlit as st
import pandas as pd
import fitz  # PyMuPDF
import re
from datetime import datetime

st.set_page_config(page_title="Conversor de Cartão de Ponto → CSV")

st.markdown("<h1 style='text-align: center; font-size: 36px;'>🗓️ CONVERSOR DE CARTÃO DE PONTO<br>→ CSV</h1>", unsafe_allow_html=True)
st.markdown("### Envie seu PDF de cartão de ponto")

uploaded_file = st.file_uploader("Drag and drop file here", type=["pdf"])

def extrair_texto_pdf(file):
    texto = ""
    with fitz.open(stream=file.read(), filetype="pdf") as doc:
        for pagina in doc:
            texto += pagina.get_text()
    return texto

def processar_texto(texto):
    linhas = texto.splitlines()
    padrao_data = re.compile(r"\d{2}/\d{2}/\d{4}")
    dados = []

    for linha in linhas:
        partes = linha.strip().split()
        if len(partes) >= 2 and padrao_data.match(partes[0]):
            try:
                data = datetime.strptime(partes[0], "%d/%m/%Y").strftime("%d/%m/%Y")

                # Ignorar linhas com DSR, ATESTADO, FÉRIAS, FERIADO, COMPENSA
                linha_maiuscula = linha.upper()
                if any(palavra in linha_maiuscula for palavra in ["DSR", "ATESTADO", "FÉRIADO", "FÉRIAS", "COMPENSA"]):
                    dados.append([data] + [""] * 12)
                    continue

                horarios = re.findall(r"\d{2}:\d{2}", linha)
                dados.append([data] + horarios[:12] + [""] * (12 - len(horarios)))
            except:
                continue

    if not dados:
        return pd.DataFrame()

    colunas = ["Data"]
    for i in range(1, 7):
        colunas.append(f"Entrada{i}")
        colunas.append(f"Saída{i}")

    df = pd.DataFrame(dados, columns=colunas[:len(dados[0])])
    return df

if uploaded_file:
    texto = extrair_texto_pdf(uploaded_file)
    df_resultado = processar_texto(texto)

    if not df_resultado.empty:
        st.markdown("### 📝 Resultado:")
        st.dataframe(df_resultado, use_container_width=True)

        csv = df_resultado.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Baixar CSV",
            data=csv,
            file_name="cartao_ponto.csv",
            mime="text/csv",
        )
    else:
        st.error("❌ Nenhum registro válido encontrado.")

# Rodapé com política e desenvolvedor
st.markdown("---")
st.markdown(
    """
    <div style='text-align: center; font-size: 13px;'>
        <p>🔒 Este site processa arquivos apenas temporariamente para gerar planilhas. Nenhum dado é armazenado ou compartilhado.</p>
        <p><a href='#'>🔗 Clique aqui para ver a Política de Privacidade</a></p>
        <p>👨‍💻 Desenvolvido por <strong>Lucas de Matos Coelho</strong></p>
    </div>
    """,
    unsafe_allow_html=True
)
