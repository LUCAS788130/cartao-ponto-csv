import streamlit as st
import pdfplumber
import pandas as pd
from datetime import datetime, timedelta
import re

st.set_page_config(page_title="CONVERSOR DE CARTÃO DE PONTO ➜ CSV")
st.title("📅 CONVERSOR DE CARTÃO DE PONTO ➜ CSV")
st.markdown("#### Envie seu PDF de cartão de ponto")

uploaded_file = st.file_uploader("Arraste ou selecione um arquivo", type="pdf")
if uploaded_file:
    with st.spinner("⏳ Convertendo... aguarde..."):
        with pdfplumber.open(uploaded_file) as pdf:
            texto = "\n".join(page.extract_text() or "" for page in pdf.pages)

        linhas = [l.strip() for l in texto.split("\n") if l.strip()]
        registros = {}

        def limpar_horario(p):
            match = re.match(r"(\d{2}:\d{2})[a-zA-Z]?$", p)
            return match.group(1) if match else None

        def eh_ocorrencia(palavra):
            return any(oc in palavra.upper() for oc in ["FERIADO", "D.S.R", "FOLG", "INTEGRAÇÃO", "ATESTADO", "FÉRIAS", "LICENÇA", "COMPENSA"])

        for ln in linhas:
            partes = ln.split()
            if len(partes) >= 2 and re.match(r"\d{2}/\d{2}/\d{4}", partes[0]):
                try:
                    data = datetime.strptime(partes[0], "%d/%m/%Y").date()
                except:
                    continue

                horarios = []
                for p in partes[2:]:  # ignora data e dia da semana
                    if eh_ocorrencia(p):
                        horarios = []  # ignora todos se for dia não útil
                        break
                    hora_limpa = limpar_horario(p)
                    if hora_limpa:
                        horarios.append(hora_limpa)
                    else:
                        break  # parou nas colunas de jornada/ocorrência/justificativa

                registros[data] = horarios

        if registros:
            inicio = min(registros.keys())
            fim = max(registros.keys())
            dias = [inicio + timedelta(days=i) for i in range((fim - inicio).days + 1)]
            resultado = []

            for dia in dias:
                linha = {"Data": dia.strftime("%d/%m/%Y")}
                horarios = registros.get(dia, [])
                for i in range(6):
                    linha[f"Entrada{i+1}"] = horarios[i*2] if i*2 < len(horarios) else ""
                    linha[f"Saída{i+1}"] = horarios[i*2+1] if i*2+1 < len(horarios) else ""
                resultado.append(linha)

            df = pd.DataFrame(resultado)
            st.subheader("📋 Resultado:")
            st.dataframe(df, use_container_width=True)

            csv = df.to_csv(index=False).encode("utf-8")
            st.success("✅ Conversão concluída com sucesso!")
            st.download_button("⬇️ Baixar CSV", csv, "cartao_convertido.csv", "text/csv")
        else:
            st.warning("⚠️ Nenhum registro válido foi encontrado.")

st.markdown("---")
st.markdown("🔒 Este site não armazena arquivos enviados. Os dados são processados apenas temporariamente.")
st.markdown("🧑‍💻 Desenvolvido por **Lucas de Matos Coelho**")
