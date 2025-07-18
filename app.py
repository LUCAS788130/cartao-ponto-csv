import streamlit as st
import pandas as pd
import pdfplumber
import pytesseract
from pdf2image import convert_from_bytes
from datetime import datetime, timedelta
import re
from PIL import Image

st.set_page_config(page_title="Conversor de Cartão de Ponto ➜ CSV")
st.markdown("## 📅 CONVERSOR DE CARTÃO DE PONTO ➜ CSV")
st.markdown("Envie seu PDF de cartão de ponto")

uploaded_file = st.file_uploader("Arraste ou selecione um arquivo", type="pdf")
if uploaded_file:
    with st.spinner("⏳ Convertendo... Aguarde um instante..."):
        # Tenta extrair texto com pdfplumber
        texto_extraido = ""
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                texto = page.extract_text()
                if texto:  # Caso seja um PDF digital
                    texto_extraido += texto + "\n"

        # Se não achou texto, tenta OCR com pytesseract
        if not texto_extraido.strip():
            imagens = convert_from_bytes(uploaded_file.read(), fmt='png')
            for img in imagens:
                texto_extraido += pytesseract.image_to_string(img, lang="por") + "\n"

        linhas = [l.strip() for l in texto_extraido.split("\n") if l.strip()]
        registros = {}

        def eh_horario(s):
            return bool(re.fullmatch(r"\d{2}:\d{2}", s))

        for ln in linhas:
            partes = ln.split()
            if len(partes) >= 2 and re.match(r"\d{2}/\d{2}/\d{4}", partes[0]):
                data_str = partes[0]
                try:
                    data = datetime.strptime(data_str, "%d/%m/%Y").date()
                except:
                    continue

                ocorrencias = " ".join(partes[5:]).upper()
                if any(kw in ocorrencias for kw in ["D.S.R", "FERIADO", "ATESTADO", "FÉRIAS", "LICENÇA", "COMPENSA"]):
                    registros[data] = []
                else:
                    horarios = [p for p in partes[1:] if eh_horario(p)]
                    registros[data] = horarios

        if registros:
            inicio = min(registros.keys())
            fim = max(registros.keys())
            dias = [inicio + timedelta(days=i) for i in range((fim - inicio).days + 1)]
            resultado = []

            for dia in dias:
                linha = {"Data": dia.strftime("%d/%m/%Y")}
                horarios = registros.get(dia, [])
                for i in range(5):
                    linha[f"Entrada{i+1}"] = horarios[i*2] if i*2 < len(horarios) else ""
                    linha[f"Saída{i+1}"] = horarios[i*2+1] if i*2+1 < len(horarios) else ""
                resultado.append(linha)

            df = pd.DataFrame(resultado)
            st.subheader("📄 Resultado:")
            st.dataframe(df, use_container_width=True)

            csv = df.to_csv(index=False).encode("utf-8")
            st.success("✅ Conversão concluída com sucesso!")
            st.download_button("📥 Baixar CSV", csv, "cartao_convertido.csv", "text/csv")
        else:
            st.warning("⚠️ Nenhum registro válido encontrado.")

st.markdown("---")
st.markdown("🔒 Este site processa arquivos apenas temporariamente para gerar planilhas. Nenhum dado é armazenado.")
st.markdown("🧑‍💻 Desenvolvido por **Lucas de Matos Coelho**")
st.markdown("📃 [Clique aqui para ver a Política de Privacidade](#)")
