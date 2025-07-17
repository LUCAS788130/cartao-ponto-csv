import streamlit as st
import pandas as pd
import tempfile
import os
from utils import extrair_texto_pdf, processar_texto

st.set_page_config(page_title="Conversor de Cartão de Ponto", layout="centered")

# TÍTULO
st.markdown("<h2 style='text-align: center;'>CONVERSOR DE CARTÃO DE PONTO → CSV</h2>", unsafe_allow_html=True)
st.write("Envie um cartão de ponto no formato PDF para gerar uma planilha (CSV).")

# UPLOAD
uploaded_file = st.file_uploader("Arraste e solte o arquivo aqui", type=["pdf"], label_visibility="collapsed")

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(uploaded_file.read())
        caminho_pdf = tmp.name

    # EXTRAÇÃO E PROCESSAMENTO
    texto = extrair_texto_pdf(caminho_pdf)
    resultado = processar_texto(texto)

    # EXIBIÇÃO
    if resultado.empty:
        st.warning("❌ Nenhum registro válido encontrado.")
    else:
        st.markdown("### 📄 Resultado:")
        st.dataframe(resultado, use_container_width=True)
        csv = resultado.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Baixar CSV", data=csv, file_name="cartao_ponto.csv", mime="text/csv")

    os.remove(caminho_pdf)

# RODAPÉ
st.markdown("---")
st.markdown("🔒 Este site processa arquivos apenas temporariamente para gerar planilhas. Nenhum dado é armazenado ou compartilhado.")
st.markdown("[🔗 Clique aqui para ver a Política de Privacidade](https://example.com/politica)")
st.markdown("👨‍💻 Desenvolvido por **Lucas de Matos Coelho**")
