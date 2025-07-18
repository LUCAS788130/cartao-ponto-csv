import streamlit as st
import pdfplumber
import pandas as pd
import re
from datetime import datetime, timedelta

st.set_page_config(page_title="CONVERSOR DE CARTÃO DE PONTO ➞ CSV")

st.markdown("""
<h1 style='text-align: center;'>🗓️ CONVERSOR DE CARTÃO DE PONTO <br>➞ CSV</h1>
<h4 style='text-align: center;'>Envie seu PDF de cartão de ponto</h4>
""", unsafe_allow_html=True)

uploaded_file = st.file_uploader("", type="pdf")

if uploaded_file:
    with st.spinner("🔄 Convertendo, aguarde..."):
        with pdfplumber.open(uploaded_file) as pdf:
            texto_completo = ""
            for page in pdf.pages:
                texto_completo += page.extract_text() + "\n"

        linhas = [l.strip() for l in texto_completo.split("\n") if l.strip()]
        padrao_data = re.compile(r"\d{2}/\d{2}/\d{4}")
        padrao_hora = re.compile(r"\b\d{2}:\d{2}g?\b")

        dados = {}

        for linha in linhas:
            partes = linha.split()
            datas = [p for p in partes if padrao_data.fullmatch(p)]
            if not datas:
                continue

            data_str = datas[0]
            try:
                data = datetime.strptime(data_str, "%d/%m/%Y").date()
            except:
                continue

            idx_data = linha.find(data_str)
            depois_data = linha[idx_data + len(data_str):].strip()

            # Tenta capturar só os horários ANTES da palavra "OCORRÊNCIAS" ou qualquer texto textual
            partes_linha = re.split(r"\s{2,}", depois_data)  # separa visualmente por colunas
            horarios_validos = []

            for bloco in partes_linha:
                bloco_upper = bloco.upper()
                if any(palavra in bloco_upper for palavra in ["OCORRÊNCIA", "JUSTIFICATIVA", "D.S.R", "FERIADO", "FOLGA", "ATESTADO", "FÉRIAS"]):
                    continue
                horarios = padrao_hora.findall(bloco)
                horarios_validos.extend(horarios)

                # Parar se detectar coluna de ocorrências (assume que colunas estão na ordem)
                if len(horarios_validos) >= 1 and len(horarios) == 0:
                    break

            dados[data] = horarios_validos

        if dados:
            inicio = min(dados)
            fim = max(dados)
            dias = [inicio + timedelta(days=i) for i in range((fim - inicio).days + 1)]

            tabela = []
            for dia in dias:
                linha = {"Data": dia.strftime("%d/%m/%Y")}
                horarios = dados.get(dia, [])
                for i in range(6):
                    linha[f"Entrada{i+1}"] = horarios[i*2] if len(horarios) > i*2 else ""
                    linha[f"Saída{i+1}"] = horarios[i*2+1] if len(horarios) > i*2+1 else ""
                tabela.append(linha)

            df = pd.DataFrame(tabela)
            st.subheader("📋 Resultado:")
            st.dataframe(df, use_container_width=True)

            csv = df.to_csv(index=False).encode("utf-8")
            st.success("✅ Conversão finalizada! Clique abaixo para baixar o arquivo CSV.")
            st.download_button("⬇️ Baixar CSV", data=csv, file_name="cartao_convertido.csv", mime="text/csv")
        else:
            st.warning("⚠️ Nenhum registro válido foi encontrado no PDF.")

    st.markdown("""
---

🔒 Este site processa arquivos apenas temporariamente para gerar planilhas. Nenhum dado é armazenado ou compartilhado.  
👨‍💻 Desenvolvido por **Lucas de Matos Coelho**
""", unsafe_allow_html=True)
