import hashlib
import io
import pandas as pd
import pdfplumber
import streamlit as st
import ponto_engine as pe
import revisao as rv

st.set_page_config(page_title="Conversor de cartão de ponto", page_icon="🕒", layout="wide")

# --------------------------------------------------------------------------
# Estilo
# --------------------------------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, .stButton, input, textarea {
  font-family: 'Public Sans', system-ui, sans-serif;
}
#MainMenu, footer, [data-testid="stDecoration"] { visibility: hidden; }
.block-container { padding-top: 2.2rem; max-width: 1280px; }

.cabecalho h1 { font-size: 1.9rem; font-weight: 700; color: #1B2A3A; margin: 0; letter-spacing: -0.01em; }
.cabecalho p  { color: #4A5B6E; font-size: 1.02rem; margin: .35rem 0 0; max-width: 62ch; }

.passos { display: flex; gap: .5rem; margin: 1.4rem 0 1.1rem; flex-wrap: wrap; }
.passo { display: flex; align-items: center; gap: .55rem; padding: .45rem .9rem .45rem .5rem;
         border-radius: 999px; background: #EAEEF4; color: #6B7A8C; font-weight: 500; font-size: .93rem; }
.passo b { display: inline-grid; place-items: center; width: 1.55rem; height: 1.55rem; border-radius: 50%;
           background: #fff; color: #6B7A8C; font-size: .82rem; }
.passo.ativo { background: #2B4C9B; color: #fff; }
.passo.ativo b { color: #2B4C9B; }
.passo.feito { background: #E3ECF9; color: #2B4C9B; }
.passo.feito b { background: #2B4C9B; color: #fff; }

.numeros { display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr; gap: 1px;
           background: #D9DFE8; border: 1px solid #D9DFE8; border-radius: 10px; overflow: hidden; margin-bottom: 1rem; }
.numeros div { background: #fff; padding: .85rem 1rem; }
.numeros span { display: block; color: #4A5B6E; font-size: .85rem; }
.numeros strong { font-size: 1.55rem; font-weight: 600; color: #1B2A3A; }
.numeros .periodo strong { font-size: 1.2rem; line-height: 2.3rem; white-space: nowrap; }
.numeros .alerta strong { color: #A15C07; }
.numeros .bom strong { color: #2F7D4F; }
@media (max-width: 700px) { .numeros { grid-template-columns: repeat(2, 1fr); } }

.aviso { border-left: 4px solid #2B4C9B; background: #fff; padding: .9rem 1.1rem; border-radius: 0 8px 8px 0;
         margin: .2rem 0 1rem; color: #1B2A3A; }
.aviso strong { display: block; margin-bottom: .2rem; }
.vazio { background: #fff; border: 1px dashed #B8C2D0; border-radius: 10px; padding: 1.2rem 1.4rem; color: #4A5B6E; }
.vazio li { margin: .25rem 0; }
.rodape { color: #6B7A8C; font-size: .8rem; margin-top: 2.5rem; border-top: 1px solid #D9DFE8; padding-top: .9rem; }
</style>
""", unsafe_allow_html=True)


def segredo(nome, padrao=""):
    try:
        return st.secrets.get(nome, padrao)
    except Exception:
        return padrao


def passos(atual: int):
    nomes = ["Envie o PDF", "Confira os dias sinalizados", "Baixe o CSV"]
    html = []
    for i, n in enumerate(nomes, start=1):
        cls = "ativo" if i == atual else ("feito" if i < atual else "")
        html.append(f'<div class="passo {cls}"><b>{"✓" if i < atual else i}</b>{n}</div>')
    st.markdown(f'<div class="passos">{"".join(html)}</div>', unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Barra lateral
# --------------------------------------------------------------------------
chave_salva = segredo("ANTHROPIC_API_KEY")

with st.sidebar:
    st.markdown("### Leitura de páginas escaneadas")
    com_ia = st.radio(
        "Como ler PDFs digitalizados?",
        ["Com IA — mais precisa", "Sem IA — gratuita, menos precisa"],
        index=0 if chave_salva else 1,
        label_visibility="collapsed",
    ).startswith("Com IA")
    api_key = ""
    if com_ia:
        if chave_salva:
            st.caption("✓ Chave da IA configurada.")
            api_key = chave_salva
        else:
            api_key = st.text_input("Chave da API Anthropic", type="password",
                                    help="Começa com sk-ant-. Pode ser salva em Settings → Secrets.")
    st.caption("PDFs com texto (não escaneados) são lidos sem IA em qualquer opção.")

    with st.expander("Avançado"):
        modelo = st.text_input("Modelo da IA", value=segredo("ANTHROPIC_MODEL", "claude-sonnet-5"))
        forcar_visao = st.checkbox("Usar IA em todas as páginas", value=False, disabled=not com_ia)
        confiar_ocr = st.checkbox("Economizar chamadas de IA", value=False, disabled=not com_ia,
                                  help="Aceita o texto embutido do PDF quando ele passa na validação. "
                                       "Mais barato, mas um 06 lido como 08 pode passar despercebido.")
        usar_tesseract = st.checkbox("Tentar OCR gratuito quando não houver IA", value=True)
        modo_jbs = st.checkbox("Modo antigo (JBS)", value=False,
                               help="Usa exatamente a lógica anterior, só para PDFs JBS com texto.")


@st.cache_data(show_spinner=False)
def ler_pdf(pdf_bytes, api_key, modelo, forcar, confiar, tesseract):
    dias, res = pe.processar_pdf(io.BytesIO(pdf_bytes), api_key=api_key or None, modelo=modelo,
                                 forcar_visao=forcar, usar_tesseract=tesseract,
                                 confiar_ocr_pdf=confiar)
    paginas = pd.DataFrame([{
        "Página": r.pagina,
        "Lida por": {"texto": "Texto do PDF", "visao": "IA",
                     "tesseract": "OCR gratuito"}.get(r.metodo, r.metodo),
        "Período": f"{r.periodo[0]:%d/%m/%Y} a {r.periodo[1]:%d/%m/%Y}" if r.periodo else "—",
        "Dias": len(r.dias),
        "Qualidade": round(r.score * 100),
        "Observação": r.nota.strip(" |"),
    } for r in res])
    return rv.montar_tabela(dias), paginas


# --------------------------------------------------------------------------
# Página
# --------------------------------------------------------------------------
st.markdown("""
<div class="cabecalho">
  <h1>Conversor de cartão de ponto</h1>
  <p>Transforma o cartão de ponto em PDF numa planilha de entradas e saídas por dia,
  e aponta o que precisa de conferência antes do uso.</p>
</div>""", unsafe_allow_html=True)

arquivo = st.file_uploader("Cartão de ponto em PDF", type="pdf", label_visibility="collapsed")

if not arquivo:
    passos(1)
    st.markdown("""
<div class="vazio">
  <strong>Arraste o PDF acima ou clique para escolher.</strong>
  <ul>
    <li>Funciona com cartões em texto e escaneados, de vários sistemas de ponto.</li>
    <li>Cada dia lido é verificado: horários fora de ordem, entrada sem saída, jornadas longas.</li>
    <li>Você corrige na própria tabela e baixa o CSV no formato Data, Entrada1, Saída1…</li>
  </ul>
</div>""", unsafe_allow_html=True)

# ---------------- modo antigo -------------------------------------------
elif modo_jbs:
    with st.spinner("Lendo o PDF…"):
        with pdfplumber.open(io.BytesIO(arquivo.getvalue())) as pdf:
            texto = "\n".join(p.extract_text() or "" for p in pdf.pages)
        layout = legado_jbs.detectar_layout(texto)
        df = (legado_jbs.processar_layout_novo(texto) if layout == "novo"
              else legado_jbs.processar_layout_antigo(texto))
    if df.empty:
        passos(1)
        st.error("Não encontrei marcações neste PDF no modo antigo. Desmarque “Modo antigo (JBS)” "
                 "em Avançado para usar a leitura automática.")
    else:
        passos(3)
        st.caption(f"Modo antigo (JBS) · layout {layout}")
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button("Baixar CSV", df.to_csv(index=False).encode("utf-8"),
                           "cartao_convertido.csv", "text/csv", type="primary")

# ---------------- leitura automática ------------------------------------
else:
    if com_ia and not api_key:
        st.info("Para usar a IA, informe a chave na barra lateral. Enquanto isso, o PDF é lido sem IA.")

    pdf_bytes = arquivo.getvalue()
    with st.spinner("Lendo o PDF… páginas escaneadas levam alguns segundos cada."):
        tabela, paginas = ler_pdf(pdf_bytes, api_key if com_ia else "", modelo,
                                  forcar_visao, confiar_ocr, usar_tesseract)

    if tabela.empty:
        passos(1)
        st.error("Não encontrei uma tabela de ponto neste PDF. Se ele for escaneado, "
                 "use a opção “Com IA” na barra lateral.")
        st.stop()

    # a tabela editada fica guardada enquanto o mesmo PDF e as mesmas opções estiverem em uso
    chave = hashlib.md5(pdf_bytes + repr((com_ia, bool(api_key), modelo, forcar_visao,
                                          confiar_ocr, usar_tesseract)).encode()).hexdigest()
    if st.session_state.get("chave") != chave:
        st.session_state.chave = chave
        st.session_state.tabela = tabela.copy()
    base = st.session_state.tabela
    r = rv.resumo(base)

    pendentes = r["conferir"] - r["conferidos"]
    passos(2 if pendentes else 3)

    st.markdown(f"""
<div class="numeros">
  <div class="periodo"><span>Período</span><strong>{r['inicio']} a {r['fim']}</strong></div>
  <div><span>Dias no período</span><strong>{r['dias']}</strong></div>
  <div class="{'bom' if r['ok'] else ''}"><span>Lidos sem pendência</span><strong>{r['ok']}</strong></div>
  <div class="{'alerta' if pendentes else 'bom'}"><span>Para conferir</span><strong>{pendentes}</strong></div>
</div>""", unsafe_allow_html=True)

    # explicação quando o problema é só falta de IA
    if not (com_ia and api_key) and (r["so_scan_sem_ia"] + r["sem_registro"]) > r["dias"] * 0.3:
        st.markdown(f"""
<div class="aviso"><strong>Este PDF é escaneado e foi lido sem IA.</strong>
{r['sem_registro']} dias ficaram sem registro e {r['so_scan_sem_ia']} vieram de uma leitura imprecisa da imagem.
Para um resultado confiável, escolha <b>Com IA</b> na barra lateral e envie o PDF de novo.</div>""",
                    unsafe_allow_html=True)

    aba_revisar, aba_paginas = st.tabs(["Revisar dias", "Páginas do PDF"])

    with aba_revisar:
        c1, c2 = st.columns([3, 2])
        filtro = c1.radio("Mostrar", ["Para conferir", "Todos os dias", "Sem registro"],
                          horizontal=True, label_visibility="collapsed",
                          index=0 if r["conferir"] else 1)
        if r["conferir"]:
            c2.progress(r["conferidos"] / r["conferir"],
                        text=f"{r['conferidos']} de {r['conferir']} dias conferidos")

        mapa = {"Para conferir": rv.CONFERIR, "Sem registro": rv.SEM_REGISTRO}
        vis = base if filtro == "Todos os dias" else base[base["Situação"] == mapa[filtro]]
        cols = rv.colunas_visiveis(base)

        if vis.empty:
            st.success("Nada para mostrar aqui. Tudo certo nesta categoria.")
        else:
            config = {
                "Situação": st.column_config.TextColumn(width="small"),
                "Data": st.column_config.TextColumn(width="small"),
                "Dia": st.column_config.TextColumn(width="small"),
                "Ocorrência": st.column_config.TextColumn(width="medium"),
                "Motivo": st.column_config.TextColumn("Por que conferir", width="large"),
                "Pág.": st.column_config.TextColumn(width="small"),
                "Conferido": st.column_config.CheckboxColumn(width="small"),
            }
            for c in rv.COLS_ES:
                config[c] = st.column_config.TextColumn(
                    c.replace("Entrada", "Ent. ").replace("Saída", "Saí. "),
                    width="small", validate=rv.RE_HORA_OK, help="Formato HH:MM")
            editada = st.data_editor(
                vis[cols], column_config=config, hide_index=True, use_container_width=True,
                height=min(38 + 35 * len(vis), 560),
                disabled=["Situação", "Data", "Dia", "Motivo", "Pág."],
                key=f"ed_{chave}_{filtro}",
            )
            textos = [c for c in cols if c in rv.COLS_ES or c == "Ocorrência"]
            novos = editada.copy()
            novos[textos] = novos[textos].fillna("").astype(str).apply(lambda s: s.str.strip())
            novos["Conferido"] = novos["Conferido"].fillna(False).astype(bool)
            editaveis = textos + ["Conferido"]
            antes = base.loc[novos.index, editaveis].astype(str)
            if not novos[editaveis].astype(str).equals(antes):
                base.loc[novos.index, editaveis] = novos[editaveis]
                st.rerun()
            st.caption("Clique num horário para corrigir (formato HH:MM). Marque “Conferido” "
                       "depois de comparar a linha com o PDF. As alterações vão para o CSV.")

    with aba_paginas:
        st.dataframe(
            paginas, hide_index=True, use_container_width=True,
            column_config={"Qualidade": st.column_config.ProgressColumn(
                format="%d%%", min_value=0, max_value=100,
                help="Parte dos dias da página lidos sem nenhuma inconsistência")},
        )
        st.caption("Qualidade baixa numa página escaneada normalmente se resolve com a opção “Com IA”.")

    st.divider()
    d1, d2 = st.columns([2, 3])
    extras = d2.checkbox("Incluir colunas de conferência (situação, motivo, página)", value=False)
    rotulo = "Baixar CSV" if not pendentes else f"Baixar CSV ({pendentes} dias ainda não conferidos)"
    d1.download_button(rotulo, rv.exportar_csv(base, extras), "cartao_convertido.csv", "text/csv",
                       type="primary", use_container_width=True)

st.markdown("""
<div class="rodape">
Em conformidade com a LGPD: os arquivos são usados só para a conversão e não ficam guardados neste site.
Com a opção “Com IA”, as imagens das páginas escaneadas são enviadas à API da Anthropic apenas para a transcrição.
<br>Desenvolvido por Lucas de Matos Coelho.
</div>""", unsafe_allow_html=True)
