import streamlit as st
import pdfplumber
import pandas as pd
from datetime import datetime, timedelta

st.set_page_config(page_title="Conversor Cartão de Ponto")
st.title("Conversor Cartão de Ponto ➜ CSV")

uploaded_file = st.file_uploader("Envie seu PDF de cartão de ponto", type="pdf")
if uploaded_file:
    with pdfplumber.open(uploaded_file) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)

    linhas = [ln.strip() for ln in text.split("\n") if ln.strip()]
    registros = {}
    for ln in linhas:
        partes = ln.split()
        if len(partes) >= 3 and partes[0].count("/") >= 1:
            data, entrada, saida = partes[0], partes[1], partes[2]
            registros[data] = (entrada, saida)

    datas = sorted(datetime.strptime(d, "%d/%m/%Y") for d in registros.keys())
    if not datas:
        st.warning("Nenhum registro de ponto encontrado.")
    else:
        inicio, fim = datas[0], datas[-1]
        dias = (fim - inicio).days + 1
        rows = []
        for i in range(dias):
            d = inicio + timedelta(days=i)
            ds = d.strftime("%d/%m/%Y")
            ent, sai = registros.get(ds, ("", ""))
            rows.append({"Data": ds, "Entrada": ent, "Saída": sai})

        df = pd.DataFrame(rows)
        st.dataframe(df)
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Baixar CSV", data=csv,
                           file_name="cartao_convertido.csv", mime="text/csv")
