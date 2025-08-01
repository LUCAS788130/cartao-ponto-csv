import streamlit as st
import pdfplumber
import pandas as pd
from datetime import datetime, timedelta
import re

st.set_page_config(page_title="CONVERSOR DE CARTÃO DE PONTO ➔ CSV")
st.markdown("<h1 style='text-align: center;'>🗕️ CONVERSOR DE CARTÃO DE PONTO ➔ CSV</h1>", unsafe_allow_html=True)

uploaded_file = st.file_uploader("Envie seu PDF de cartão de ponto", type="pdf")
if uploaded_file:
    with st.spinner("⏳ Processando seu cartão de ponto... Isso pode levar alguns segundos..."):
        with pdfplumber.open(uploaded_file) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)

        linhas = [linha.strip() for linha in text.split("\n") if linha.strip()]
        registros = {}

        def limpar_horario(p):
            m = re.match(r'(\d{2}:\d{2})', p)
            return m.group(1) if m else None

        def eh_data(s):
            return re.match(r"\d{2}/\d{2}/\d{4}", s)

        for ln in linhas:
            partes = ln.split()
            if len(partes) >= 2 and eh_data(partes[0]):
                try:
                    data = datetime.strptime(partes[0], "%d/%m/%Y").date()

                    # Pega somente os valores antes da coluna Ocorrências, se existir
                    if 'OCORR' in ln.upper():
                        ln = ln.upper().split('OCORR')[0]
                        partes = ln.split()

                    horarios = []
                    for p in partes[1:]:
                        h = limpar_horario(p)
                        if h:
                            horarios.append(h)

                    registros[data] = horarios
                except:
                    pass

        if registros:
            inicio = min(registros.keys())
            fim = max(registros.keys())

            dias_corridos = [inicio + timedelta(days=i) for i in range((fim - inicio).days + 1)]
            tabela = []

            for dia in dias_corridos:
                linha = {"Data": dia.strftime("%d/%m/%Y")}
                horarios = registros.get(dia, [])

                for i in range(6):
                    entrada = horarios[i * 2] if len(horarios) > i * 2 else ""
                    saida = horarios[i * 2 + 1] if len(horarios) > i * 2 + 1 else ""
                    linha[f"Entrada{i+1}"] = entrada
                    linha[f"Saída{i+1}"] = saida

                tabela.append(linha)

            df = pd.DataFrame(tabela)
            st.subheader("Resultado:")
            st.dataframe(df, use_container_width=True)

            csv = df.to_csv(index=False).encode("utf-8")

            st.markdown("<div style='font-size: 48px; text-align: center;'>🚀</div>", unsafe_allow_html=True)
            st.success("✅ Conversão concluída com sucesso! Sua planilha está pronta para download.")

            st.download_button(
                label="⬇️ Baixar CSV",
                data=csv,
                file_name="cartao_convertido.csv",
                mime="text/csv",
            )
        else:
            st.warning("❌ Nenhum registro válido encontrado.")

# Rodapé com LGPD e desenvolvedor
st.markdown("""
<hr>
<p style='text-align: center; font-size: 13px;'>
🔒 Este site está em conformidade com a <strong>Lei Geral de Proteção de Dados (LGPD)</strong>.<br>
Os arquivos enviados são utilizados apenas para conversão e não são armazenados nem compartilhados.<br>
👨‍💻 Desenvolvido por <strong>Lucas de Matos Coelho</strong>
</p>
""", unsafe_allow_html=True)
