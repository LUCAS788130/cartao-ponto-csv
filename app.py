import streamlit as st
import pdfplumber
import pandas as pd
import re
from datetime import datetime, timedelta

st.set_page_config(page_title="Conversor de Cartão de Ponto ➜ CSV")
st.markdown("<h1 style='text-align: center;'>📅 CONVERSOR DE CARTÃO DE PONTO ➜ CSV</h1>", unsafe_allow_html=True)

st.markdown("#### Envie seu PDF de cartão de ponto")
uploaded_file = st.file_uploader("Arraste e solte ou clique para enviar", type="pdf")

def eh_horario(p):
    return re.match(r"^\d{2}:\d{2}g?$", p)

if uploaded_file:
    with st.spinner("⏳ Convertendo arquivo..."):
        with pdfplumber.open(uploaded_file) as pdf:
            texto = "\n".join([page.extract_text() or "" for page in pdf.pages])

        linhas = [l.strip() for l in texto.split("\n") if l.strip()]
        registros = {}

        for ln in linhas:
            partes = ln.split()
            # Verifica se a linha começa com uma data válida
            if len(partes) >= 2 and re.match(r"\d{2}/\d{2}/\d{4}", partes[0]):
                try:
                    data = datetime.strptime(partes[0], "%d/%m/%Y").date()

                    # Tenta separar marcações da parte de ocorrências
                    partes_sem_data = partes[1:]
                    partes_marcacoes = []
                    for p in partes_sem_data:
                        if re.match(r"\d{2}:\d{2}g?", p):
                            partes_marcacoes.append(p)
                        else:
                            break  # Parou nas ocorrências

                    horarios = [p.replace("g", "") for p in partes_marcacoes if eh_horario(p)]

                    # Ignora se linha tiver menos de dois horários
                    registros[data] = horarios if len(horarios) >= 2 else []
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
            st.markdown("### 🗂️ Resultado:")
            st.dataframe(df, use_container_width=True)

            csv = df.to_csv(index=False).encode("utf-8")
            st.success("✅ Conversão concluída com sucesso! Seu arquivo já está disponível para download.")
            st.download_button("⬇️ Baixar CSV", data=csv, file_name="cartao_convertido.csv", mime="text/csv")
        else:
            st.warning("⚠️ Nenhum horário válido encontrado no PDF.")

# Rodapé com LGPD e autor
st.markdown("---")
st.markdown(
    """
    <div style='font-size: 13px; color: gray; text-align: center;'>
        🔒 Este site processa arquivos temporariamente para gerar planilhas. Nenhum dado é armazenado ou compartilhado.<br>
        👨‍💻 Desenvolvido por <strong>Lucas de Matos Coelho</strong>
    </div>
    """,
    unsafe_allow_html=True,
)
