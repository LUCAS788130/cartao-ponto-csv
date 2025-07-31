import streamlit as st
import pdfplumber
import csv
import re
import os

st.set_page_config(page_title="EXTRATOR DE CARTÃO DE PONTO", layout="centered")

st.markdown("<h2 style='text-align: center;'>EXTRATOR DE CARTÃO DE PONTO</h2>", unsafe_allow_html=True)
st.markdown("---")

uploaded_file = st.file_uploader("📎 Envie o arquivo PDF do cartão de ponto", type=["pdf"])

def extrair_horarios(linha_marcacoes):
    return [re.sub(r'[a-zA-Z]$', '', h) for h in re.findall(r'\d{2}:\d{2}[a-zA-Z]?', linha_marcacoes)]

def processar_cartao_ponto(file):
    dados = []

    with pdfplumber.open(file) as pdf:
        for pagina in pdf.pages:
            linhas = pagina.extract_text().split('\n')
            for linha in linhas:
                partes = linha.strip().split()
                if len(partes) < 2:
                    continue
                if re.fullmatch(r'\d{1,2}', partes[0]):
                    dia = partes[0].zfill(2)
                    linha_marcacoes = ' '.join(partes[1:])
                    if 'OCORRÊNCIA' in linha_marcacoes.upper():
                        linha_marcacoes = linha_marcacoes.split('OCORRÊNCIA')[0]
                    horarios = extrair_horarios(linha_marcacoes)
                    linha_csv = [dia] + horarios + [''] * (12 - len(horarios))
                    dados.append(linha_csv)

    dias_presentes = {linha[0] for linha in dados}
    for dia in range(1, 32):
        dia_str = str(dia).zfill(2)
        if dia_str not in dias_presentes:
            dados.append([dia_str] + [''] * 12)

    dados.sort(key=lambda x: int(x[0]))

    cabecalho = ['Dia'] + [f'Entrada{i}' if i % 2 != 0 else f'Saída{i//2}' for i in range(1, 13)]
    return cabecalho, dados

if uploaded_file:
    try:
        cabecalho, dados = processar_cartao_ponto(uploaded_file)
        st.success("✅ Processamento concluído com sucesso!")

        # Exibir tabela
        st.markdown("### 📋 Tabela Extraída:")
        st.dataframe([dict(zip(cabecalho, linha)) for linha in dados])

        # Gerar CSV para download
        output_path = "/tmp/saida.csv"
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(cabecalho)
            writer.writerows(dados)

        with open(output_path, "rb") as f:
            st.download_button("⬇️ Baixar CSV", f, file_name="cartao_ponto_extraido.csv", mime="text/csv")

    except Exception as e:
        st.error(f"❌ Erro ao processar o arquivo: {e}")
