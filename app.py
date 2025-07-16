import streamlit as st
import pdfplumber
import pandas as pd
from io import BytesIO

st.set_page_config(page_title="Conversor de Cartão de Ponto para CSV")
st.title("🕒 Conversor de Cartão de Ponto (PDF ➜ CSV)")

uploaded_file = st.file_uploader("Envie o cartão de ponto (PDF com texto)", type="pdf")

if uploaded_file:
    with pdfplumber.open(uploaded_file) as pdf:
        text = ''
        for page in pdf.pages:
            text += page.extract_text() + "\n"

    linhas = [linha for linha in text.split("\n") if linha.strip()]
    
    dados = []
    for linha in linhas:
        partes = linha.strip().split()
        if len(partes) >= 3:
            data = partes[0]
            entrada = partes[1]
            saida = partes[2]
            dados.append({
                "Data": data,
                "Entrada": entrada,
                "Saída": saida
            })

    if dados:
        df = pd.DataFrame(dados)
        st.subheader("📄 Resultado:")
        st.dataframe(df)

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇️ Baixar CSV",
            data=csv,
            file_name="cartao_ponto_convertido.csv",
            mime="text/csv"
        )
    else:
        st.warning("⚠️ Nenhum dado válido foi encontrado no PDF.")
