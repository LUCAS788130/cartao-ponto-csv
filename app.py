import streamlit as st
import pdfplumber
import pandas as pd
import re
from datetime import datetime, timedelta

st.set_page_config(page_title="CONVERSOR DE CARTÃO DE PONTO ➜ CSV")
st.markdown("<h1 style='text-align: center;'>📅 CONVERSOR DE CARTÃO DE PONTO ➜ CSV</h1>", unsafe_allow_html=True)

uploaded_file = st.file_uploader("Envie seu PDF de cartão de ponto", type="pdf")

def limpar_horario(h):
    h = h.strip()
    return re.sub(r"[^\d:]", "", h)  # remove letras como "g", "r", etc.

if uploaded_file:
    with st.spinner("⏳ Processando seu cartão de ponto... Isso pode levar alguns segundos..."):
        with pdfplumber.open(uploaded_file) as pdf:
            texto = "\n".join(page.extract_text() or "" for page in pdf.pages)

        linhas = texto.split("\n")
        dados = {}

        for linha in linhas:
            partes = linha.split()
            if len(partes) >= 2 and re.match(r"\d{2}/\d{2}/\d{4}", partes[0]):
                try:
                    data = datetime.strptime(partes[0], "%d/%m/%Y").date()
                    # Pega apenas a parte da linha ANTES de "OCORR"
                    if "OCORR" in [p.upper() for p in partes]:
                        idx = [p.upper() for p in partes].index("OCORR")
                        partes = partes[:idx]
                    # Ignora data e dia da semana (ex: "Seg-Norm")
                    horarios = [limpar_horario(p) for p in partes[2:] if re.match(r"\d{2}:\d{2}", p)]
                    dados[data] = horarios
                except:
                    continue

        if not dados:
            st.warning("⚠️ Nenhum dado válido encontrado no PDF.")
        else:
            # Garante dias consecutivos mesmo que estejam faltando
            data_inicio = min(dados.keys())
            data_fim = max(dados.keys())
            dias = [data_inicio + timedelta(days=i) for i in range((data_fim - data_inicio).days + 1)]

            registros = []
            for dia in dias:
                linha = {"Dia": dia.strftime("%d")}
                horarios = dados.get(dia, [])
                for i in range(6):
                    entrada = horarios[i * 2] if len(horarios) > i * 2 else ""
                    saida = horarios[i * 2 + 1] if len(horarios) > i * 2 + 1 else ""
                    linha[f"Entrada{i+1}"] = entrada
                    linha[f"Saída{i+1}"] = saida
                registros.append(linha)

            df = pd.DataFrame(registros)
            st.subheader("📋 Tabela Extraída:")
            st.dataframe(df, use_container_width=True)

            csv = df.to_csv(index=False).encode("utf-8")
            st.success("✅ Processamento concluído com sucesso!")
            st.download_button("📥 Baixar CSV", data=csv, file_name="cartao_convertido.csv", mime="text/csv")

# Rodapé com LGPD
st.markdown("""
<hr>
<p style='text-align: center; font-size: 13px;'>
🔒 Este site está em conformidade com a <strong>Lei Geral de Proteção de Dados (LGPD)</strong>.<br>
Os arquivos enviados são utilizados apenas para conversão e não são armazenados nem compartilhados.<br>
👨‍💻 Desenvolvido por <strong>Lucas de Matos Coelho</strong>
</p>
""", unsafe_allow_html=True)
