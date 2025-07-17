import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image
import pytesseract
from pdf2image import convert_from_bytes
import io

# Configuração da página
st.set_page_config(page_title="Conversor de Cartão de Ponto OCR ➜ CSV")
st.title("📅 Conversor de Cartão de Ponto (PDF/Imagem) ➜ CSV")

# Função que extrai texto com OCR
def extrair_texto(file):
    texto = ""
    if file.type == "application/pdf":
        imagens = convert_from_bytes(file.read(), dpi=300)
        for img in imagens:
            texto += pytesseract.image_to_string(img, lang="por") + "\n"
    elif "image" in file.type:
        imagem = Image.open(file)
        texto = pytesseract.image_to_string(imagem, lang="por")
    return texto

# Função para identificar se algo é horário
def eh_horario(p):
    return ":" in p and len(p) == 5 and p.replace(":", "").isdigit()

uploaded_file = st.file_uploader("Envie um cartão de ponto (PDF escaneado ou imagem)", type=["pdf", "png", "jpg", "jpeg"])
if uploaded_file:
    with st.spinner("🔍 Extraindo texto..."):
        texto = extrair_texto(uploaded_file)

    linhas = [linha.strip() for linha in texto.split("\n") if linha.strip()]
    registros = {}

    for ln in linhas:
        partes = ln.split()
        if len(partes) >= 2 and "/" in partes[0]:
            try:
                data = datetime.strptime(partes[0], "%d/%m/%Y").date()
                pos_dia = partes[2:]  # ignora data e dia da semana
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
        st.download_button("⬇️ Baixar CSV", data=csv, file_name="cartao_convertido.csv", mime="text/csv")
    else:
        st.warning("❌ Nenhum registro válido encontrado.")

# Rodapé LGPD
st.markdown("---")
st.markdown(
    "🔒 Este site processa arquivos apenas temporariamente para gerar planilhas. Nenhum dado é armazenado ou compartilhado. "
    "[Clique aqui para ver a Política de Privacidade](#politica-de-privacidade)"
)

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
