import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="EXTRATOR DE CARTÃO DE PONTO", layout="centered")
st.title("🕒 EXTRATOR DE CARTÃO DE PONTO")

uploaded_file = st.file_uploader("\n\U0001F4E5 Envie o arquivo PDF do cartão de ponto", type=["pdf"])

def limpar_horarios(texto):
    horarios = re.findall(r"\d{2}:\d{2}[a-zA-Z]?", texto)
    return [h[:5] for h in horarios]  # remove sufixos

def processar_pdf_cartao(pdf):
    dados = []
    dias_processados = set()

    with pdfplumber.open(pdf) as pdf:
        for pagina in pdf.pages:
            linhas = pagina.extract_text().split('\n')
            for linha in linhas:
                partes = linha.split()
                if len(partes) < 2:
                    continue
                if re.match(r"\d{2}/\d{2}/\d{4}", partes[0]):
                    dia = partes[0][:2]  # extrai apenas o dia
                    if dia in dias_processados:
                        continue
                    dias_processados.add(dia)

                    match = re.search(r"(\d{2}:\d{2}[a-zA-Z]? ?)+", linha)
                    if match:
                        horarios = limpar_horarios(match.group())
                    else:
                        horarios = []
                    linha_final = [dia] + horarios + [''] * (12 - len(horarios))
                    dados.append(linha_final)

    for dia in range(1, 32):
        d = str(dia).zfill(2)
        if d not in dias_processados:
            dados.append([d] + [''] * 12)

    dados.sort(key=lambda x: int(x[0]))
    colunas = ['Dia'] + [f'Entrada{i}' if i % 2 != 0 else f'Saída{i//2}' for i in range(1, 13)]
    df = pd.DataFrame(dados, columns=colunas)
    return df

if uploaded_file:
    df = processar_pdf_cartao(uploaded_file)
    st.success("\u2705 Processamento concluído com sucesso!")
    st.subheader("\ud83d\udcc4 Tabela Extraída:")
    st.dataframe(df, use_container_width=True)

    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button("⬇️ Baixar CSV", data=csv, file_name="cartao_ponto.csv", mime="text/csv")
