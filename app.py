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

def extrair_marcacoes(texto):
    linhas = [linha.strip() for linha in texto.split("\n") if linha.strip()]
    padrao_data = re.compile(r"\d{2}/\d{2}/\d{4}")
    padrao_hora = re.compile(r"\d{2}:\d{2}g?")

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

        # Encontrar posição da data e extrair apenas a parte até a coluna "Ocorrências"
        pos_data = linha.find(data_str)
        depois_data = linha[pos_data + len(data_str):]

        # Corta a linha ao encontrar alguma palavra comum da coluna de ocorrências
        ocorrencias_idx = len(depois_data)
        for palavra in ["D.S.R", "FERIADO", "ATESTADO", "FÉRIAS", "HORA", "INTEGRAÇÃO", "FOLGA", "COMPENSA", "JUSTIFICATIVA"]:
            if palavra in depois_data:
                ocorrencias_idx = min(ocorrencias_idx, depois_data.find(palavra))

        apenas_marcacoes = depois_data[:ocorrencias_idx]
        horarios = padrao_hora.findall(apenas_marcacoes)

        if horarios:
            dados[data] = horarios

    return dados

if uploaded_file:
    with st.spinner("🔄 Convertendo, aguarde..."):
        with pdfplumber.open(uploaded_file) as pdf:
            texto = "\n".join(page.extract_text() or "" for page in pdf.pages)

        dados = extrair_marcacoes(texto)

        if dados:
            inicio = min(dados)
            fim = max(dados)
            dias = [inicio + timedelta(days=i) for i in range((fim - inicio).days + 1)]

            tabela = []
            for dia in dias:
                linha = {"Data": dia.strftime("%d/%m/%Y")}
                horarios = dados.get(dia, [])
                for i in range(6):
                    linha[f"Entrada{i+1}"] = horarios[i * 2] if len(horarios) > i * 2 else ""
                    linha[f"Saída{i+1}"] = horarios[i * 2 + 1] if len(horarios) > i * 2 + 1 else ""
                tabela.append(linha)

            df = pd.DataFrame(tabela)
            st.subheader(":clipboard: Resultado:")
            st.dataframe(df, use_container_width=True)

            csv = df.to_csv(index=False).encode("utf-8")
            st.success("✅ Arquivo convertido com sucesso!")
            st.download_button("⬇️ Baixar CSV", data=csv, file_name="cartao_convertido.csv", mime="text/csv")
        else:
            st.warning("⚠️ Nenhum horário válido encontrado. Verifique o layout do seu cartão.")

    st.markdown("""
---

🔒 Este site processa arquivos apenas temporariamente. Nenhum dado é armazenado ou compartilhado.  
📄 [Política de Privacidade](#)  
👨‍💻 Desenvolvido por **Lucas de Matos Coelho**
""", unsafe_allow_html=True)
