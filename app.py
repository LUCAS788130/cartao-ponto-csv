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
            linhas = []
            for page in pdf.pages:
                try:
                    table = page.extract_table()
                    if table:
                        linhas.extend(table)
                except:
                    continue

        registros = {}

        def limpar_horario(p):
            m = re.match(r'(\d{2}:\d{2})', p)
            return m.group(1) if m else None

        for linha in linhas:
            if not linha or len(linha) < 2:
                continue
            data_raw = linha[0].strip()
            marcacoes_raw = linha[1].strip() if len(linha) > 1 else ""

            if re.match(r"\d{2}/\d{2}/\d{4}", data_raw):
                try:
                    data = datetime.strptime(data_raw, "%d/%m/%Y").date()
                    horarios = [limpar_horario(p) for p in marcacoes_raw.split() if limpar_horario(p)]
                    registros[data] = horarios
                except:
                    continue

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
