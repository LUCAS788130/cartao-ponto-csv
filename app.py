import streamlit as st
import pdfplumber
import pandas as pd
import re
from datetime import datetime, timedelta

st.set_page_config(page_title="Conversor de Cartão de Ponto ➜ CSV")
st.title("📅 CONVERSOR DE CARTÃO DE PONTO ➜ CSV")

st.markdown("Envie seu PDF de cartão de ponto")
uploaded_file = st.file_uploader(" ", type="pdf")

def extrair_texto_pdf(file):
    with pdfplumber.open(file) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)

def eh_horario(valor):
    return re.fullmatch(r"\d{2}:\d{2}g?", valor) is not None

def extrair_linhas_por_coluna(texto):
    linhas = texto.split("\n")
    linhas_validas = []
    for linha in linhas:
        if re.search(r"\d{2}/\d{2}/\d{4}", linha):
            linhas_validas.append(linha)
    return linhas_validas

def processar_linhas_jbs(linhas):
    registros = {}

    for linha in linhas:
        partes = linha.split()
        if len(partes) < 2:
            continue

        try:
            data = datetime.strptime(partes[0], "%d/%m/%Y").date()
        except:
            continue

        # Separar onde começam os horários
        horarios = [p for p in partes[1:] if eh_horario(p)]
        ocorrencias = partes[partes.index(horarios[-1])+1:] if horarios else []

        # Remover qualquer horário que também esteja nas ocorrências
        horarios_filtrados = [h for h in horarios if h not in ocorrencias]

        registros[data] = horarios_filtrados

    return registros

def gerar_planilha(registros):
    if not registros:
        return pd.DataFrame()

    inicio = min(registros.keys())
    fim = max(registros.keys())
    dias = [inicio + timedelta(days=i) for i in range((fim - inicio).days + 1)]

    tabela = []
    for dia in dias:
        linha = {"Data": dia.strftime("%d/%m/%Y")}
        horarios = registros.get(dia, [])

        for i in range(6):  # até Entrada6 / Saída6
            entrada = horarios[i * 2] if len(horarios) > i * 2 else ""
            saida = horarios[i * 2 + 1] if len(horarios) > i * 2 + 1 else ""
            linha[f"Entrada{i+1}"] = entrada
            linha[f"Saída{i+1}"] = saida

        tabela.append(linha)

    return pd.DataFrame(tabela)

if uploaded_file:
    with st.spinner("⏳ Convertendo o cartão de ponto..."):
        texto = extrair_texto_pdf(uploaded_file)
        linhas = extrair_linhas_por_coluna(texto)
        registros = processar_linhas_jbs(linhas)
        df = gerar_planilha(registros)

    if not df.empty:
        st.subheader("📋 Resultado:")
        st.dataframe(df, use_container_width=True)
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Baixar CSV", data=csv, file_name="cartao_convertido.csv", mime="text/csv")
        st.success("✅ Conversão concluída com sucesso!")
    else:
        st.warning("⚠️ Nenhum horário válido encontrado nas marcações.")

# Rodapé LGPD e autor
st.markdown("---")
st.markdown("🔒 Este site processa arquivos apenas temporariamente para gerar planilhas. Nenhum dado é armazenado ou compartilhado.")
st.markdown("👨‍💻 Desenvolvido por **Lucas de Matos Coelho**")
