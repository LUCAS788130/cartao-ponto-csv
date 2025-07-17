import streamlit as st
import fitz  # PyMuPDF
import pandas as pd
import re
from datetime import datetime

st.set_page_config(page_title="Conversor de Cartão de Ponto → CSV", layout="centered")

st.markdown(
    "<h1 style='text-align: center; font-size: 2.5rem;'>🗓️ CONVERSOR DE CARTÃO DE PONTO → CSV</h1>",
    unsafe_allow_html=True
)

st.markdown("**Envie seu PDF de cartão de ponto**")

uploaded_file = st.file_uploader(" ", type=["pdf"])

def extrair_texto_pdf(caminho_pdf):
    texto = ""
    with fitz.open(caminho_pdf) as doc:
        for pagina in doc:
            texto += pagina.get_text()
    return texto

def processar_texto(texto):
    linhas = texto.strip().split("\n")
    padrao_data = re.compile(r"^\d{2}/\d{2}/\d{4}$")
    dados = []

    for linha in linhas:
        partes = linha.strip().split()
        if len(partes) >= 2 and "/" in partes[0]:
            try:
                data = datetime.strptime(partes[0], "%d/%m/%Y")
                horarios = [p for p in partes[1:] if re.match(r"\d{2}:\d{2}", p)]

                if any(palavra in linha.upper() for palavra in ["D.S.R", "ATESTADO", "FERIADO", "FÉRIAS", "COMPENSA"]):
                    horarios = []

                dados.append((data, horarios))
            except:
                continue

    if not dados:
        return pd.DataFrame()

    datas_extraidas = [d[0] for d in dados]
    inicio = min(datas_extraidas)
    fim = max(datas_extraidas)
    total_dias = (fim - inicio).days + 1

    todos_os_dias = [inicio + pd.Timedelta(days=i) for i in range(total_dias)]
    dados_completos = []

    for dia in todos_os_dias:
        horarios = next((h for d, h in dados if d == dia), [])
        linha = [dia.strftime("%d/%m/%Y")] + horarios + [""] * (12 - len(horarios))
        dados_completos.append(linha[:13])

    colunas = ["Data"] + [
        f"{tipo}{i}" for i in range(1, 7) for tipo in ("Entrada", "Saída")
    ]

    return pd.DataFrame(dados_completos, columns=colunas)

if uploaded_file is not None:
    texto = extrair_texto_pdf(uploaded_file)
    df = processar_texto(texto)

    if df.empty:
        st.error("❌ Nenhum registro válido encontrado.")
    else:
        st.markdown("### 📋 Resultado:")
        st.dataframe(df, use_container_width=True)

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Baixar como CSV",
            data=csv,
            file_name="cartao_ponto.csv",
            mime="text/csv",
        )

st.markdown("---")
st.markdown(
    """
    <small>
    🔒 Este site processa arquivos apenas temporariamente para gerar planilhas. Nenhum dado é armazenado ou compartilhado.  
    🔗 <a href='#' target='_blank'>Clique aqui para ver a Política de Privacidade</a>  
    👨‍💻 Desenvolvido por <strong>Lucas de Matos Coelho</strong>
    </small>
    """,
    unsafe_allow_html=True
)
