# Versão simples e funcional sem OCR:
import streamlit as st
import pdfplumber
import pandas as pd
from datetime import datetime, timedelta

st.set_page_config(page_title="Conversor de Cartão de Ponto ➜ CSV")
st.title("📅 CONVERSOR DE CARTÃO DE PONTO ➜ CSV")

uploaded_file = st.file_uploader("Envie seu PDF de cartão de ponto", type="pdf")
if uploaded_file:
    with st.spinner("⏳ Processando o arquivo..."):
        with pdfplumber.open(uploaded_file) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)

        linhas = [linha.strip() for linha in text.split("\n") if linha.strip()]
        registros = {}

        def eh_horario(p):
            return ":" in p and len(p) == 5 and p.replace(":", "").isdigit()

        for ln in linhas:
            partes = ln.split()
            if len(partes) >= 2 and "/" in partes[0]:
                try:
                    data = datetime.strptime(partes[0], "%d/%m/%Y").date()
                    pos_dia = partes[2:]
                    tem_ocorrencia = any(not eh_horario(p) for p in pos_dia)
                    horarios = [p for p in pos_dia if eh_horario(p)]
                    registros[data] = [] if tem_ocorrencia else horarios
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
            st.subheader("📋 Resultado:")
            st.dataframe(df, use_container_width=True)

            csv = df.to_csv(index=False).encode("utf-8")
            st.success("✅ Prontinho! Sua planilha está pronta para download.")
            st.download_button("⬇️ Baixar CSV", data=csv, file_name="cartao_convertido.csv", mime="text/csv")
        else:
            st.warning("⚠️ Nenhum registro válido encontrado.")

st.markdown("---")
st.markdown("🔒 Este site processa arquivos apenas temporariamente para gerar planilhas. Nenhum dado é armazenado.")
st.markdown("👨‍💻 Desenvolvido por **Lucas de Matos Coelho**")
