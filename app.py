import streamlit as st
import pdfplumber
import pandas as pd
from datetime import datetime, timedelta

st.set_page_config(page_title="Conversor Cartão de Ponto ➜ CSV")
st.title("📅 Conversor Cartão de Ponto ➜ CSV")

uploaded_file = st.file_uploader("Envie seu PDF de cartão de ponto", type="pdf")
if uploaded_file:
    with pdfplumber.open(uploaded_file) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    linhas = [linha.strip() for linha in text.split("\n") if linha.strip()]
    registros = {}

    for ln in linhas:
        partes = ln.split()
        if len(partes) >= 2 and "/" in partes[0]:
            try:
                data = datetime.strptime(partes[0], "%d/%m/%Y").date()
                # coleta somente os horários no formato HH:MM
                horarios = [p for p in partes[2:] if ":" in p and len(p) == 5]
                registros[data] = horarios
            except:
                pass

    if registros:
        inicio = min(registros.keys())
        fim = max(registros.keys())
        datas_corridas = [inicio + timedelta(days=i) for i in range((fim - inicio).days + 1)]

        tabela = []
        for data in datas_corridas:
            horarios = registros.get(data, [])
            linha = {"Data": data.strftime("%d/%m/%Y")}
            for i in range(4):  # até 4 marcações por dia
                linha[f"Horário {i+1}"] = horarios[i] if i < len(horarios) else ""
            tabela.append(linha)

        df = pd.DataFrame(tabela)
        st.subheader("📋 Resultado:")
        st.dataframe(df, use_container_width=True)

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Baixar CSV", data=csv, file_name="cartao_convertido.csv", mime="text/csv")
    else:
        st.warning("❌ Nenhum registro válido encontrado.")
