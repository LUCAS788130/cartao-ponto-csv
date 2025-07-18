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
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)

        linhas = [linha.strip() for linha in text.split("\n") if linha.strip()]

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

            if data not in dados:
                dados[data] = []

            # Considera apenas os dados antes da coluna "Ocorrências"
            if "Ocorr" in linha:
                continue
            pos_data = linha.find(data_str)
            depois_data = linha[pos_data + len(data_str):]
            partes = depois_data.split()

            # Ignora qualquer trecho da linha após encontrar palavras de ocorrência
            ocorrencias_idx = None
            for i, parte in enumerate(partes):
                if any(p in parte.upper() for p in ["FERIADO", "D.S.R", "DSR", "ATESTADO", "FOLGA", "FÉRIAS", "COMPENSA"]):
                    ocorrencias_idx = i
                    break
            if ocorrencias_idx is not None:
                partes = partes[:ocorrencias_idx]

            # Agora coleta os horários restantes da parte esquerda (marcações)
            horarios = [h for h in partes if padrao_hora.fullmatch(h)]

            # Se tiver menos de 2, não considera esse dia (não trabalhou)
            if len(horarios) >= 2:
                dados[data].extend(horarios)

        if dados:
            inicio = min(dados)
            fim = max(dados)
            dias = [inicio + timedelta(days=i) for i in range((fim - inicio).days + 1)]

            tabela = []
            for dia in dias:
                linha = {"Data": dia.strftime("%d/%m/%Y")}
                horarios = dados.get(dia, [])
                for i in range(2):
                    linha[f"Entrada{i+1}"] = horarios[i*2] if len(horarios) > i*2 else ""
                    linha[f"Saída{i+1}"] = horarios[i*2+1] if len(horarios) > i*2+1 else ""
                tabela.append(linha)

            df = pd.DataFrame(tabela)
            st.subheader(":clipboard: Resultado:")
            st.dataframe(df, use_container_width=True)

            csv = df.to_csv(index=False).encode("utf-8")
            st.success("Arquivo convertido com sucesso! 🎉 Clique abaixo para baixar.")
            st.download_button("⬇️ Baixar CSV", data=csv, file_name="cartao_convertido.csv", mime="text/csv")
        else:
            st.warning("Nenhum registro válido encontrado no PDF.")

    st.markdown("""
---

:lock: Este site processa arquivos apenas temporariamente para gerar planilhas. Nenhum dado é armazenado ou compartilhado.  
:page_facing_up: [Clique aqui para ver a Política de Privacidade](#)  
:technologist: Desenvolvido por **Lucas de Matos Coelho**
""", unsafe_allow_html=True)
