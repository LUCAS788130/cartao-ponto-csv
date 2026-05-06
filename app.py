import streamlit as st
import pdfplumber
import pandas as pd
import re
from datetime import datetime, timedelta

st.set_page_config(page_title="CARTÃO DE PONTO ➜ CSV")

st.markdown(
    "<h1 style='text-align: center;'>🕒 CONVERSOR DE CARTÃO DE PONTO</h1>",
    unsafe_allow_html=True
)

uploaded_file = st.file_uploader("📎 Envie o cartão de ponto em PDF", type="pdf")


def criar_estrutura_padrao():
    return {
        "Data": [],
        "Entrada1": [], "Saída1": [],
        "Entrada2": [], "Saída2": [],
        "Entrada3": [], "Saída3": [],
        "Entrada4": [], "Saída4": [],
        "Entrada5": [], "Saída5": [],
        "Entrada6": [], "Saída6": []
    }


def preencher_horarios(estrutura, horarios):
    horarios = horarios[:12]

    if len(horarios) % 2 != 0:
        horarios = horarios[:-1]

    pares = horarios + [""] * (12 - len(horarios))

    for i in range(6):
        estrutura[f"Entrada{i + 1}"].append(pares[2 * i])
        estrutura[f"Saída{i + 1}"].append(pares[2 * i + 1])


def detectar_layout(texto):
    texto_upper = texto.upper()

    if "FORPONTO" in texto_upper and "JBS" in texto_upper:
        return "jbs"

    linhas = texto.split("\n")

    for linha in linhas:
        if re.match(r"\d{2}/\d{2}/\d{4}", linha):
            partes = linha.split()
            if len(partes) >= 5 and any(
                o in linha.upper()
                for o in [
                    "FERIADO",
                    "D.S.R",
                    "INTEGRAÇÃO",
                    "FALTA",
                    "LICENÇA REMUNERADA - D"
                ]
            ):
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

    if not registros:
        return pd.DataFrame()

    inicio = min(registros.keys())
    fim = max(registros.keys())

    tabela = []

    for dia in [
        inicio + timedelta(days=i)
        for i in range((fim - inicio).days + 1)
    ]:
        linha = {"Data": dia.strftime("%d/%m/%Y")}
        horarios = registros.get(dia, [])

        for i in range(2):
            linha[f"Entrada{i + 1}"] = horarios[i * 2] if len(horarios) > i * 2 else ""
            linha[f"Saída{i + 1}"] = horarios[i * 2 + 1] if len(horarios) > i * 2 + 1 else ""

        tabela.append(linha)

    return pd.DataFrame(tabela)


def processar_layout_novo(texto):
    linhas = texto.split("\n")
    registros = []

    ocorrencias_que_zeram = [
        "D.S.R", "FERIADO", "FÉRIAS", "FALTA", "ATESTADO", "FERIAS",
        "DISPENSA", "INTEGRAÇÃO", "LICENÇA REMUNERADA", "SUSPENSÃO",
        "DESLIGAMENTO", "COMPENSA DIA", "FOLGA COMPENSATÓRIA",
        "ATESTADO MÉDICO"
    ]

    for linha in linhas:
        match = re.match(r"(\d{2}/\d{2}/\d{4})", linha)

        if match:
            data_str = match.group(1)
            linha_upper = linha.upper()

            if (
                any(oc in linha_upper for oc in ocorrencias_que_zeram)
                and "SAÍDA ANTECIPADA" not in linha_upper
                and "ATRASO" not in linha_upper
                and "DISPENSA FALTA DE PRODUÇÃO - P" not in linha_upper
            ):
                registros.append((data_str, []))
                continue

            corte_ocorrencias = (
                r"\s+(HORA|D\.S\.R|FALTA|FERIADO|FÉRIAS|ATESTADO|"
                r"DISPENSA|SAÍDA ANTECIPADA|INTEGRAÇÃO|SUSPENSÃO|"
                r"DESLIGAMENTO|FOLGA|COMPENSA|ATRASO)"
            )

            parte_marcacoes = re.split(corte_ocorrencias, linha_upper)[0]

            horarios = re.findall(r"\d{2}:\d{2}[a-z]?", parte_marcacoes)
            horarios = [h[:-1] if h[-1].isalpha() else h for h in horarios]
            horarios = [h for h in horarios if re.match(r"\d{2}:\d{2}", h)]

            if len(horarios) % 2 != 0:
                horarios = horarios[:-1]

            registros.append((data_str, horarios[:12]))

    if not registros:
        return pd.DataFrame()

    df = pd.DataFrame(registros, columns=["Data", "Horários"])
    df["Data"] = pd.to_datetime(df["Data"], dayfirst=True)

    data_inicio = df["Data"].min()
    data_fim = df["Data"].max()

    registros_dict = {
        d.strftime("%d/%m/%Y"): h
        for d, h in zip(df["Data"], df["Horários"])
    }

    estrutura = criar_estrutura_padrao()

    for dia in [
        data_inicio + timedelta(days=i)
        for i in range((data_fim - data_inicio).days + 1)
    ]:
        data_formatada = dia.strftime("%d/%m/%Y")
        estrutura["Data"].append(data_formatada)
        preencher_horarios(estrutura, registros_dict.get(data_formatada, []))

    return pd.DataFrame(estrutura)


def processar_layout_jbs_pdf(pdf):
    registros = {}

    for page in pdf.pages:
        words = page.extract_words(
            x_tolerance=2,
            y_tolerance=3,
            keep_blank_chars=False,
            use_text_flow=False
        )

        if not words:
            continue

        for w_data in words:
            texto_data = w_data["text"].strip()

            if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", texto_data):
                continue

            if float(w_data["x0"]) > 80:
                continue

            try:
                data = datetime.strptime(texto_data, "%d/%m/%Y").date()
            except:
                continue

            top = float(w_data["top"])
            bottom = float(w_data["bottom"])

            # RECORTE EXATO DA COLUNA:
            # "Marcação ou Situação Funcional"
            #
            # No layout JBS/Forponto enviado:
            # X 175 a 305 = área dos horários da coluna de marcação.
            # Não pega FALTAS, AD.NOT, H.E.50%, H.NEG ou Horas.
            bbox = (
                175,
                max(0, top - 2),
                305,
                min(float(page.height), bottom + 2)
            )

            area = page.crop(bbox)
            texto_area = area.extract_text(
                x_tolerance=2,
                y_tolerance=3
            ) or ""

            horarios = re.findall(r"\b\d{2}:\d{2}\b", texto_area)

            # Fallback: caso o crop não extraia texto, usa words da mesma linha
            # dentro da mesma área.
            if not horarios:
                mesma_linha = [
                    w for w in words
                    if abs(float(w["top"]) - top) <= 2.5
                ]

                for w in mesma_linha:
                    txt = w["text"].strip()
                    x0 = float(w["x0"])

                    if (
                        175 <= x0 <= 305
                        and re.fullmatch(r"\d{2}:\d{2}", txt)
                    ):
                        horarios.append(txt)

            registros[data] = horarios[:12]

    if not registros:
        return pd.DataFrame()

    inicio = min(registros.keys())
    fim = max(registros.keys())

    estrutura = criar_estrutura_padrao()

    for dia in [
        inicio + timedelta(days=i)
        for i in range((fim - inicio).days + 1)
    ]:
        estrutura["Data"].append(dia.strftime("%d/%m/%Y"))
        preencher_horarios(estrutura, registros.get(dia, []))

    return pd.DataFrame(estrutura)


if uploaded_file:
    with st.spinner("⏳ Processando..."):
        with pdfplumber.open(uploaded_file) as pdf:
            texto = "\n".join(page.extract_text() or "" for page in pdf.pages)
            layout = detectar_layout(texto)

            nomes_layout = {
                "antigo": "ANTIGO",
                "novo": "NOVO",
                "jbs": "JBS / FORPONTO"
            }

            st.info(f"📄 Layout detectado: **{nomes_layout.get(layout, layout.upper())}**")

            if layout == "jbs":
                df = processar_layout_jbs_pdf(pdf)
            elif layout == "novo":
                df = processar_layout_novo(texto)
            else:
                df = processar_layout_antigo(texto)

        if not df.empty:
            st.success("✅ Conversão concluída com sucesso!")
            st.dataframe(df, use_container_width=True)

            csv = df.to_csv(index=False).encode("utf-8")

            st.download_button(
                "⬇️ Baixar CSV",
                data=csv,
                file_name="cartao_convertido.csv",
                mime="text/csv"
            )
        else:
            st.warning("❌ Não foi possível extrair os dados do cartão.")


st.markdown(
    """
    <hr>
    <p style='text-align: center; font-size: 13px;'>
    🔒 Este site está em conformidade com a <strong>Lei Geral de Proteção de Dados (LGPD)</strong>.<br>
    Os arquivos enviados são utilizados apenas para conversão e não são armazenados nem compartilhados.<br>
    👨‍💻 Desenvolvido por <strong>Lucas de Matos Coelho</strong>
    </p>
    """,
    unsafe_allow_html=True
)
