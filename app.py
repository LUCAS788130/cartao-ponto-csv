import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image
import pytesseract
from pdf2image import convert_from_bytes
import pdfplumber
import io
import re

# Configuração da página
st.set_page_config(page_title="Conversor de Cartão de Ponto ➜ CSV")
st.title("📅 Conversor de Cartão de Ponto (PDF ou Imagem) ➜ CSV")

def extrair_texto(file):
    if file.type == "application/pdf":
        try:
            with pdfplumber.open(file) as pdf:
                texto = "\n".join(page.extract_text() or "" for page in pdf.pages)
            if texto.strip():
                return texto, "digital"
        except:
            pass
        imagens = convert_from_bytes(file.read(), dpi=300)
        texto = ""
        for img in imagens:
            texto += pytesseract.image_to_string(img, lang="por") + "\n"
        return texto, "imagem"
    elif "image" in file.type:
        imagem = Image.open(file)
        texto = pytesseract.image_to_string(imagem, lang="por")
        return texto, "imagem"
    return "", "desconhecido"

def eh_horario(p):
    return re.match(r"\d{2}:\d{2}$", p)

def construir_planilha_digital(texto):
    linhas = [linha.strip() for linha in texto.split("\n") if linha.strip()]
    registros = {}
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

    if not registros:
        return None

    inicio = min(registros.keys())
    fim = max(registros.keys())
    dias_corridos = [inicio + timedelta(days=i) for i in range((fim - inicio).days + 1)]
    tabela = []

    for dia in dias_corridos:
        linha = {"Data": dia.strftime("%d/%m/%Y")}
        horarios = registros.get(dia, [])
        for i in range(6):
            linha[f"Entrada{i+1}"] = horarios[i * 2] if len(horarios) > i * 2 else ""
            linha[f"Saída{i+1}"] = horarios[i * 2 + 1] if len(horarios) > i * 2 + 1 else ""
        tabela.append(linha)

    return pd.DataFrame(tabela)

def construir_planilha_mensal(texto):
    linhas = [linha for linha in texto.split("\n") if linha.strip()]
    mes_ano = None
    for linha in linhas[:5]:
        match = re.search(r"(\d{2})/(\d{4})", linha)
        if match:
            mes_ano = match.group(0)
            break
    if not mes_ano:
        return None

    tabela = []
    for ln in linhas:
        partes = ln.strip().split()
        if not partes:
            continue
        if partes[0].isdigit():
            dia = int(partes[0])
            try:
                data = datetime.strptime(f"{dia:02d}/{mes_ano}", "%d/%m/%Y")
            except:
                continue
            conteudo = " ".join(partes[1:]).upper()
            tem_ocorrencia = any(palavra in conteudo for palavra in ["DOMINGO", "SABADO", "FOLGA", "ATESTADO", "FERIADO", "FÉRIAS", "COMPENSA"])
            horarios = [p for p in partes[1:] if eh_horario(p)] if not tem_ocorrencia else []
            linha = {"Data": data.strftime("%d/%m/%Y")}
            for i in range(6):
                linha[f"Entrada{i+1}"] = horarios[i * 2] if len(horarios) > i * 2 else ""
                linha[f"Saída{i+1}"] = horarios[i * 2 + 1] if len(horarios) > i * 2 + 1 else ""
            tabela.append(linha)
    return pd.DataFrame(tabela) if tabela else None

uploaded_file = st.file_uploader("Envie um cartão de ponto (PDF ou imagem)", type=["pdf", "png", "jpg", "jpeg"])
if uploaded_file:
    with st.spinner("🔍 Extraindo texto..."):
        texto, tipo = extrair_texto(uploaded_file)

    st.subheader("📄 Texto extraído:")
    st.text(texto[:3000])

    df = construir_planilha_digital(texto)
    if df is None:
        df = construir_planilha_mensal(texto)

    if df is not None:
        st.subheader("📋 Resultado:")
        st.dataframe(df, use_container_width=True)
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Baixar CSV", data=csv, file_name="cartao_convertido.csv", mime="text/csv")
    else:
        st.warning("❌ Não foi possível interpretar o cartão de ponto.")

st.markdown("---")
st.markdown("""
🔒 Este site processa arquivos apenas temporariamente para gerar planilhas. Nenhum dado é armazenado ou compartilhado.  
📄 [Clique aqui para ver a Política de Privacidade](#politica-de-privacidade)  
👤 Desenvolvido por **Lucas de Matos Coelho**
""")

with st.expander("📄 Política de Privacidade"):
    st.markdown("""
    Este site foi desenvolvido com foco em simplicidade e privacidade.

    **1. Coleta de Dados**  
    Nenhum dado pessoal é coletado, armazenado ou compartilhado.  
    Os arquivos enviados são usados somente para gerar uma planilha, sendo descartados automaticamente após o processo.

    **2. Finalidade**  
    O site tem como única finalidade converter cartões de ponto em planilhas CSV.

    **3. Armazenamento e Compartilhamento**  
    Não há armazenamento local ou remoto dos arquivos. Nenhum dado é compartilhado com terceiros.

    **4. LGPD**  
    Estamos em conformidade com a Lei Geral de Proteção de Dados (LGPD), respeitando a privacidade dos usuários e tratando os arquivos apenas enquanto necessário para a conversão.

    Se tiver dúvidas ou sugestões, entre em contato com o responsável pelo site.
    """)
