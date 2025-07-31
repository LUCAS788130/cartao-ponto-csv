import streamlit as st
import pdfplumber
import re
import pandas as pd

st.set_page_config(page_title="EXTRATOR DE CARTÃO DE PONTO", layout="centered")
st.title("🕒 EXTRATOR DE CARTÃO DE PONTO")

uploaded_file = st.file_uploader("\n📥 Envie o arquivo PDF do cartão de ponto", type=["pdf"])

def extrair_horarios(texto):
    return [re.sub(r'[a-zA-Z]$', '', h) for h in re.findall(r'\d{2}:\d{2}[a-zA-Z]?', texto)]

def processar_pdf(pdf):
    dados = []
    dias_presentes = set()

    with pdfplumber.open(pdf) as pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text()
            if not texto:
                continue
            linhas = texto.split("\n")

            for linha in linhas:
                partes = linha.strip().split()
                if len(partes) < 2:
                    continue
                if re.fullmatch(r'\d{1,2}', partes[0]):
                    dia = partes[0].zfill(2)
                    linha_marcacoes = ' '.join(partes[1:])
                    if 'OCORR' in linha_marcacoes.upper():
                        linha_marcacoes = linha_marcacoes.split('OCORR')[0]
                    horarios = extrair_horarios(linha_marcacoes)
                    linha_csv = [dia] + horarios + [''] * (12 - len(horarios))
                    dados.append(linha_csv)
                    dias_presentes.add(dia)

    for dia in range(1, 32):
        d = str(dia).zfill(2)
        if d not in dias_presentes:
            dados.append([d] + [''] * 12)

    dados.sort(key=lambda x: int(x[0]))
    colunas = ['Dia'] + [f'Entrada{i}' if i % 2 != 0 else f'Saída{i//2}' for i in range(1, 13)]
    df = pd.DataFrame(dados, columns=colunas)
    return df

if uploaded_file:
    df = processar_pdf(uploaded_file)
    st.success("✅ Processamento concluído com sucesso!")
    st.subheader("📄 Tabela Extraída:")
    st.dataframe(df, use_container_width=True)

    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button("⬇️ Baixar CSV", data=csv, file_name="cartao_ponto.csv", mime="text/csv")
