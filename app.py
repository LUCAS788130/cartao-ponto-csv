import streamlit as st
import pdfplumber
import pandas as pd
import re
from datetime import datetime, timedelta

st.set_page_config(page_title="CARTÃO DE PONTO ➜ CSV")
st.markdown("<h1 style='text-align: center;'>🕒 CONVERSOR DE CARTÃO DE PONTO</h1>", unsafe_allow_html=True)

uploaded_file = st.file_uploader("📎 Envie o cartão de ponto em PDF", type="pdf")

def detectar_layout(texto):
    linhas = texto.split("\n")
    for linha in linhas:
        if re.match(r"\d{2}/\d{2}/\d{4}", linha):
            partes = linha.split()
            if len(partes) >= 5 and any(o in linha.upper() for o in ["FERIADO", "D.S.R", "INTEGRAÇÃO", "FALTA", "LICENÇA REMUNERADA - D"]):
                return "novo"
    return "antigo"

def processar_layout_antigo(texto):
    linhas = [linha.strip() for linha in texto.split("\n") if linha.strip()]
    registros = {}

    def eh_horario(p):
        return ":" in p and len(p) == 5 and p.replace(":", "").isdigit()

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

    if registros:
        inicio = min(registros.keys())
        fim = max(registros.keys())

        dias_corridos = [inicio + timedelta(days=i) for i in range((fim - inicio).days + 1)]
        tabela = []

        for dia in dias_corridos:
            linha = {"Data": dia.strftime("%d/%m/%Y")}
            horarios = registros.get(dia, [])

            for i in range(2):
                entrada = horarios[i * 2] if len(horarios) > i * 2 else ""
                saida = horarios[i * 2 + 1] if len(horarios) > i * 2 + 1 else ""
                linha[f"Entrada{i+1}"] = entrada
                linha[f"Saída{i+1}"] = saida

            tabela.append(linha)

        return pd.DataFrame(tabela)

    return pd.DataFrame()

def processar_layout_novo(texto):
    linhas = texto.split("\n")
    registros = []

    # Ocorrências que anulam o dia (exceto saída antecipada, atraso e DISPENSA FALTA DE PRODUÇÃO - P)
    ocorrencias_que_zeram = [
        "D.S.R", "FERIADO", "FÉRIAS", "FALTA", "ATESTADO", "FERIAS", "DISPENSA",
        "INTEGRAÇÃO", "LICENÇA REMUNERADA", "SUSPENSÃO", "DESLIGAMENTO",
        "COMPENSA DIA", "FOLGA COMPENSATÓRIA", "ATESTADO MÉDICO"
    ]

    for linha in linhas:
        match = re.match(r"(\d{2}/\d{2}/\d{4})", linha)
        if match:
            data_str = match.group(1)
            linha_upper = linha.upper()

            # Zerar horários se ocorrência for irrelevante, exceto SAÍDA ANTECIPADA, ATRASO ou DISPENSA FALTA DE PRODUÇÃO - P
            if any(oc in linha_upper for oc in ocorrencias_que_zeram) and \
                "SAÍDA ANTECIPADA" not in linha_upper and \
                "ATRASO" not in linha_upper and \
                "DISPENSA FALTA DE PRODUÇÃO - P" not in linha_upper:
                registros.append((data_str, []))
                continue

            # CORTAR TEXTO ANTES DAS OCORRÊNCIAS, para não capturar horários delas
            corte_ocorrencias = r"\s+(HORA|D\.S\.R|FALTA|FERIADO|FÉRIAS|ATESTADO|DISPENSA|SAÍDA ANTECIPADA|INTEGRAÇÃO|SUSPENSÃO|DESLIGAMENTO|FOLGA|COMPENSA|ATRASO)"
            parte_marcacoes = re.split(corte_ocorrencias, linha_upper)[0]

            # Extrair horários válidos da parte de marcações somente
            horarios = re.findall(r"\d{2}:\d{2}[a-z]?", parte_marcacoes)
            horarios = [h[:-1] if h[-1].isalpha() else h for h in horarios]
            horarios = [h for h in horarios if re.match(r"\d{2}:\d{2}", h)]

            # DESCARTA horários isolados (ex: só entrada sem saída) para evitar pegar horário de ocorrência como entrada2
            if len(horarios) % 2 != 0:
                horarios = horarios[:-1]  # Remove o último horário se não formar par completo

            # Limita a no máximo seis pares (12 marcações)
            horarios = horarios[:12]

            registros.append((data_str, horarios))

    if not registros:
        return pd.DataFrame()

    df = pd.DataFrame(registros, columns=["Data", "Horários"])
    df["Data"] = pd.to_datetime(df["Data"], dayfirst=True)

    data_inicio = df["Data"].min()
    data_fim = df["Data"].max()
    todas_datas = [(data_inicio + timedelta(days=i)).strftime("%d/%m/%Y") for i in range((data_fim - data_inicio).days + 1)]

    registros_dict = {d.strftime("%d/%m/%Y"): h for d, h in zip(df["Data"], df["Horários"])}

    estrutura = {
        "Data": [],
        "Entrada1": [], "Saída1": [],
        "Entrada2": [], "Saída2": [],
        "Entrada3": [], "Saída3": [],
        "Entrada4": [], "Saída4": [],
        "Entrada5": [], "Saída5": [],
        "Entrada6": [], "Saída6": []
    }

    for data in todas_datas:
        estrutura["Data"].append(data)
        horarios = registros_dict.get(data, [])

        pares = horarios + [""] * (12 - len(horarios))
        for i in range(6):
            estrutura[f"Entrada{i+1}"].append(pares[2*i])
            estrutura[f"Saída{i+1}"].append(pares[2*i + 1])

    return pd.DataFrame(estrutura)

if uploaded_file:
    with st.spinner("⏳ Processando..."):
        with pdfplumber.open(uploaded_file) as pdf:
            texto = "\n".join(page.extract_text() or "" for page in pdf.pages)

        layout = detectar_layout(texto)
        st.info(f"📄 Layout detectado: **{layout.upper()}**")

        if layout == "novo":
            df = processar_layout_novo(texto)
        else:
            df = processar_layout_antigo(texto)

        if not df.empty:
            st.success("✅ Conversão concluída com sucesso!")
            st.dataframe(df, use_container_width=True)
            csv = df.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ Baixar CSV", data=csv, file_name="cartao_convertido.csv", mime="text/csv")
        else:
            st.warning("❌ Não foi possível extrair os dados do cartão.")

st.markdown("""
<hr>
<p style='text-align: center; font-size: 13px;'>
🔒 Este site está em conformidade com a <strong>Lei Geral de Proteção de Dados (LGPD)</strong>.<br>
Os arquivos enviados são utilizados apenas para conversão e não são armazenados nem compartilhados.<br>
👨‍💻 Desenvolvido por <strong>Lucas de Matos Coelho</strong>
</p>
""", unsafe_allow_html=True)
