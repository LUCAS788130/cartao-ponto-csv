import streamlit as st
import pdfplumber
import pandas as pd
from datetime import datetime, timedelta

st.set_page_config(page_title="CONVERSOR DE CARTÃO DE PONTO ➜ CSV")
st.markdown("<h1 style='text-align: center;'>📅 CONVERSOR DE CARTÃO DE PONTO ➜ CSV</h1>", unsafe_allow_html=True)

uploaded_file = st.file_uploader("Envie seu PDF de cartão de ponto", type="pdf")
if uploaded_file:
    with st.spinner("⏳ Processando seu cartão de ponto... Isso pode levar alguns segundos..."):
        with pdfplumber.open(uploaded_file) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)

        linhas = [linha.strip() for linha in text.split("\n") if linha.strip()]
        
        st.write("Exemplo das linhas extraídas:", linhas[:30])  # Debug - veja as primeiras linhas no app

        registros = {}

        def eh_horario(p):
            return ":" in p and len(p) == 5 and p.replace(":", "").isdigit()

        for ln in linhas:
            partes = ln.split()
            # Tentar achar data completa dd/mm/yyyy
            if len(partes) >= 2 and "/" in partes[0]:
                try:
                    data = datetime.strptime(partes[0], "%d/%m/%Y").date()
                    pos_dia = partes[1:]  # considera tudo depois da data

                    # Filtra só os horários válidos (ignora textos e ocorrências)
                    horarios = [p for p in pos_dia if eh_horario(p)]
                    tem_ocorrencia = any(not eh_horario(p) for p in pos_dia)

                    # Guarda só se não tiver ocorrência (ou adapte conforme seu critério)
                    if not tem_ocorrencia and horarios:
                        registros[data] = horarios
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

                # Só 2 pares entrada/saida
                for i in range(2):
                    entrada = horarios[i * 2] if len(horarios) > i * 2 else ""
                    saida = horarios[i * 2 + 1] if len(horarios) > i * 2 + 1 else ""
                    linha[f"Entrada{i+1}"] = entrada
                    linha[f"Saída{i+1}"] = saida

                tabela.append(linha)

            df = pd.DataFrame(tabela)
            st.subheader("📋 Resultado:")
            st.dataframe(df, use_container_width=True)

            csv = df.to_csv(index=False).encode("utf-8")

            st.markdown("<div style='font-size: 48px; text-align: center;'>🚀</div>", unsafe_allow_html=True)
            st.success("✅ Conversão concluída com sucesso! Sua planilha está pronta para download.")

            st.download_button(
                label="⬇️ Baixar CSV",
                data=csv,
                file_name="cartao_convertido.csv",
                mime="text/csv",
            )
        else:
            st.warning("❌ Nenhum registro válido encontrado.")

# Rodapé com LGPD e desenvolvedor
st.markdown("""
<hr>
<p style='text-align: center; font-size: 13px;'>
🔒 Este site está em conformidade com a <strong>Lei Geral de Proteção de Dados (LGPD)</strong>.<br>
Os arquivos enviados são utilizados apenas para conversão e não são armazenados nem compartilhados.<br>
👨‍💻 Desenvolvido por <strong>Lucas de Matos Coelho</strong>
</p>
""", unsafe_allow_html=True)
