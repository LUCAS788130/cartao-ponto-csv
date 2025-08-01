import streamlit as st
import pdfplumber
import pandas as pd
import re
from datetime import datetime

st.set_page_config(page_title="CONVERSOR DE CARTÃO DE PONTO ➜ CSV")
st.markdown("<h1 style='text-align: center;'>📅 CONVERSOR DE CARTÃO DE PONTO ➜ CSV</h1>", unsafe_allow_html=True)

uploaded_file = st.file_uploader("Envie seu PDF de cartão de ponto", type="pdf")
if uploaded_file:
    with st.spinner("⏳ Processando seu cartão de ponto..."):
        with pdfplumber.open(uploaded_file) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)

        linhas = [linha for linha in text.split("\n") if re.match(r"\d{2}/\d{2}/\d{4}", linha)]
        registros = []

        for linha in linhas:
            partes = linha.split()
            data_str = partes[0]

            try:
                data = datetime.strptime(data_str, "%d/%m/%Y").strftime("%d/%m/%Y")
            except ValueError:
                continue

            # Pega somente a parte das marcações (entre a data e a coluna Ocorrências)
            try:
                idx_marcacoes = partes.index("Ocorrências")
                marcacoes = partes[1:idx_marcacoes]
            except ValueError:
                # Caso "Ocorrências" não esteja presente, pega até onde começam blocos como 08:00d etc
                marcacoes = []
                for p in partes[1:]:
                    if re.match(r"\d{2}:\d{2}", p):
                        marcacoes.append(p)
                    elif re.search(r"\d{2}:\d{2}", p):
                        marcacoes.append(re.search(r"\d{2}:\d{2}", p).group())
                    else:
                        break

            # Remove letras (como 08:00d → 08:00)
            horarios_limpos = [re.sub(r"[^\d:]", "", h) for h in marcacoes if re.match(r"\d{2}:\d{2}", h)]

            linha = {
                "Data": data,
                "Entrada1": horarios_limpos[0] if len(horarios_limpos) > 0 else "",
                "Saída1":   horarios_limpos[1] if len(horarios_limpos) > 1 else "",
                "Entrada2": horarios_limpos[2] if len(horarios_limpos) > 2 else "",
                "Saída2":   horarios_limpos[3] if len(horarios_limpos) > 3 else "",
            }
            registros.append(linha)

        if registros:
            df = pd.DataFrame(registros)
            st.subheader("📋 Tabela Extraída:")
            st.dataframe(df, use_container_width=True)

            csv = df.to_csv(index=False).encode("utf-8")
            st.success("✅ Processamento concluído com sucesso!")
            st.download_button("⬇️ Baixar CSV", csv, "cartao_convertido.csv", "text/csv")
        else:
            st.warning("⚠️ Nenhum dado de marcação foi encontrado.")

# Rodapé
st.markdown("""
<hr>
<p style='text-align: center; font-size: 13px;'>
🔒 Este site está em conformidade com a <strong>Lei Geral de Proteção de Dados (LGPD)</strong>.<br>
Os arquivos enviados são utilizados apenas para conversão e não são armazenados nem compartilhados.<br>
👨‍💻 Desenvolvido por <strong>Lucas de Matos Coelho</strong>
</p>
""", unsafe_allow_html=True)
