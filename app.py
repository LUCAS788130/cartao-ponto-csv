import io
import re
from datetime import datetime, timedelta

import pandas as pd
import pdfplumber
import streamlit as st

import ponto_engine as pe

st.set_page_config(page_title="CARTÃO DE PONTO ➜ CSV", layout="wide")
st.markdown("<h1 style='text-align: center;'>🕒 CONVERSOR DE CARTÃO DE PONTO</h1>",
            unsafe_allow_html=True)


# ==========================================================================
# MODO LEGADO JBS — funções originais, sem alteração de comportamento
# ==========================================================================

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
            except Exception:
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
            if any(oc in linha_upper for oc in ocorrencias_que_zeram) and \
                    "SAÍDA ANTECIPADA" not in linha_upper and \
                    "ATRASO" not in linha_upper and \
                    "DISPENSA FALTA DE PRODUÇÃO - P" not in linha_upper:
                registros.append((data_str, []))
                continue
            corte_ocorrencias = r"\s+(HORA|D\.S\.R|FALTA|FERIADO|FÉRIAS|ATESTADO|DISPENSA|SAÍDA ANTECIPADA|INTEGRAÇÃO|SUSPENSÃO|DESLIGAMENTO|FOLGA|COMPENSA|ATRASO)"
            parte_marcacoes = re.split(corte_ocorrencias, linha_upper)[0]
            horarios = re.findall(r"\d{2}:\d{2}[a-z]?", parte_marcacoes)
            horarios = [h[:-1] if h[-1].isalpha() else h for h in horarios]
            horarios = [h for h in horarios if re.match(r"\d{2}:\d{2}", h)]
            if len(horarios) % 2 != 0:
                horarios = horarios[:-1]
            horarios = horarios[:12]
            registros.append((data_str, horarios))

    if not registros:
        return pd.DataFrame()

    df = pd.DataFrame(registros, columns=["Data", "Horários"])
    df["Data"] = pd.to_datetime(df["Data"], dayfirst=True)
    data_inicio = df["Data"].min()
    data_fim = df["Data"].max()
    todas_datas = [(data_inicio + timedelta(days=i)).strftime("%d/%m/%Y")
                   for i in range((data_fim - data_inicio).days + 1)]
    registros_dict = {d.strftime("%d/%m/%Y"): h for d, h in zip(df["Data"], df["Horários"])}
    estrutura = {"Data": []}
    for i in range(6):
        estrutura[f"Entrada{i+1}"] = []
        estrutura[f"Saída{i+1}"] = []
    for data in todas_datas:
        estrutura["Data"].append(data)
        horarios = registros_dict.get(data, [])
        pares = horarios + [""] * (12 - len(horarios))
        for i in range(6):
            estrutura[f"Entrada{i+1}"].append(pares[2 * i])
            estrutura[f"Saída{i+1}"].append(pares[2 * i + 1])
    return pd.DataFrame(estrutura)


# ==========================================================================
# CONFIGURAÇÕES
# ==========================================================================

def segredo(nome, padrao=""):
    try:
        return st.secrets.get(nome, padrao)
    except Exception:  # sem .streamlit/secrets.toml
        return padrao


chave_secrets = segredo("ANTHROPIC_API_KEY")

with st.sidebar:
    st.header("⚙️ Configurações")
    modo = st.radio("Modo de leitura",
                    ["Automático (qualquer layout)", "JBS – legado"],
                    help="O modo legado usa exatamente a lógica anterior, só para PDFs JBS com texto.")
    st.divider()
    st.subheader("📷 Cartões digitalizados")
    usar_visao = st.toggle("Usar leitura por IA (Claude) em páginas digitalizadas",
                           value=bool(chave_secrets),
                           help="Recomendado para scans. As imagens das páginas são enviadas à API da Anthropic.")
    api_key = chave_secrets
    if usar_visao and not chave_secrets:
        api_key = st.text_input("Chave da API Anthropic", type="password")
    modelo = st.text_input("Modelo", value=segredo("ANTHROPIC_MODEL", "claude-sonnet-5"))
    forcar_visao = st.checkbox("Usar IA em todas as páginas", value=False)
    confiar_ocr = st.checkbox("Economizar: aceitar o OCR embutido do PDF quando ele passar na validação",
                              value=False,
                              help="Reduz chamadas à API. Um dígito trocado (06↔08) pode passar na validação.")
    usar_tesseract = st.checkbox("Usar Tesseract quando não houver IA", value=True,
                                 help="Gratuito, mas pouco confiável em scans de baixa resolução (≈150 dpi).")
    st.divider()
    colunas_extras = st.checkbox("Incluir colunas Ocorrência / Origem / Página / Alertas no CSV",
                                 value=False)


@st.cache_data(show_spinner=False)
def rodar_automatico(pdf_bytes, api_key, modelo, forcar, confiar, tesseract):
    dias, res = pe.processar_pdf(io.BytesIO(pdf_bytes), api_key=api_key or None, modelo=modelo,
                                 forcar_visao=forcar, usar_tesseract=tesseract,
                                 confiar_ocr_pdf=confiar)
    relatorio = pd.DataFrame([{
        "Página": r.pagina,
        "Método": {"texto": "Texto do PDF", "visao": "IA (visão)",
                   "tesseract": "Tesseract"}.get(r.metodo, r.metodo),
        "Período": f"{r.periodo[0]:%d/%m/%Y} a {r.periodo[1]:%d/%m/%Y}" if r.periodo else "",
        "Dias lidos": len(r.dias),
        "Qualidade": f"{r.score:.0%}",
        "Observação": r.nota.strip(" |"),
    } for r in res])
    return dias, relatorio


# ==========================================================================
# PROCESSAMENTO
# ==========================================================================

uploaded_file = st.file_uploader("📎 Envie o cartão de ponto em PDF", type="pdf")

if uploaded_file:
    pdf_bytes = uploaded_file.getvalue()

    if modo == "JBS – legado":
        with st.spinner("⏳ Processando..."):
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                texto = "\n".join(page.extract_text() or "" for page in pdf.pages)
            layout = detectar_layout(texto)
            st.info(f"📄 Layout detectado: **{layout.upper()}**")
            df = processar_layout_novo(texto) if layout == "novo" else processar_layout_antigo(texto)
        if df.empty:
            st.warning("❌ Não foi possível extrair os dados do cartão.")
            st.stop()
        df_csv = df
        st.dataframe(df, use_container_width=True)

    else:
        if usar_visao and not api_key:
            st.warning("Informe a chave da API para usar a leitura por IA, ou desligue a opção.")
        with st.spinner("⏳ Lendo páginas (páginas digitalizadas podem levar alguns segundos cada)..."):
            dias, relatorio = rodar_automatico(pdf_bytes, api_key if usar_visao else "",
                                               modelo, forcar_visao, confiar_ocr, usar_tesseract)
        if not dias:
            st.warning("❌ Não foi possível identificar uma tabela de ponto neste PDF.")
            st.dataframe(relatorio, use_container_width=True, hide_index=True)
            st.stop()

        df_full = pe.para_dataframe(dias, extras=True)
        n_alertas = int((df_full["Alertas"] != "").sum())
        c1, c2, c3 = st.columns(3)
        c1.metric("Dias", len(df_full))
        c2.metric("Período", f"{df_full['Data'].iloc[0]} → {df_full['Data'].iloc[-1]}")
        c3.metric("Dias para conferir", n_alertas)

        if n_alertas:
            st.warning(f"⚠️ {n_alertas} dia(s) com alerta. Confira-os no PDF antes de usar o CSV.")
        else:
            st.success("✅ Conversão concluída sem alertas.")

        so_alertas = st.checkbox("Mostrar só os dias com alerta", value=False)
        vis = df_full[df_full["Alertas"] != ""] if so_alertas else df_full
        st.dataframe(
            vis.style.apply(lambda r: ["background-color: #fff3cd" if r["Alertas"] else ""] * len(r),
                            axis=1),
            use_container_width=True, hide_index=True)

        with st.expander("📑 Relatório por página"):
            st.dataframe(relatorio, use_container_width=True, hide_index=True)

        df_csv = df_full if colunas_extras else df_full.drop(
            columns=["Ocorrência", "Origem", "Página", "Alertas"])

    csv = df_csv.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Baixar CSV", data=csv, file_name="cartao_convertido.csv",
                       mime="text/csv")

st.markdown("""
<hr>
<p style='text-align: center; font-size: 13px;'>
🔒 Este site está em conformidade com a <strong>Lei Geral de Proteção de Dados (LGPD)</strong>.<br>
Os arquivos enviados são utilizados apenas para conversão e não são armazenados por este site.<br>
Quando a leitura por IA está ativada, as imagens das páginas digitalizadas são enviadas à API da Anthropic
exclusivamente para a transcrição.<br>
👨‍💻 Desenvolvido por <strong>Lucas de Matos Coelho</strong>
</p>
""", unsafe_allow_html=True)
