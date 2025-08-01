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
            m = re.match(r'(\d{2}:\d{2})[a-zA-Z]?', p)
            return m.group(1) if m else None

        def eh_horario(p):
            return limpar_horario(p) is not None

        for ln in linhas:
            partes = ln.split()
            if len(partes) >= 2 and re.match(r"\d{2}/\d{2}/\d{4}", partes[0]):
                try:
                    data = datetime.strptime(partes[0], "%d/%m/%Y").date()
                    horarios_brutos = partes[1:]
                    horarios_limpos = [limpar_horario(p) for p in horarios_brutos if eh_horario(p)]

                    # Ignora se todos os campos depois da data forem palavras (ex: FERIADO, DSR, FALTAS...)
                    if len(horarios_limpos) > 0:
                        registros[data] = horarios_limpos
                    else:
                        registros[data] = []
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
