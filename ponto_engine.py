"""
Motor genérico de extração de cartões de ponto (PDF texto ou digitalizado).

Estratégia por página:
  1. Camada de texto (pdfplumber) + parser por coordenadas: acha a linha de
     cabeçalho, delimita a faixa das colunas de marcação (Entrada/Saída/Marcações)
     e lê só os horários dentro dessa faixa. Funciona para layouts com data
     completa (dd/mm/aaaa) e com dia + dia da semana ("26 QUA"), usando o período
     do cabeçalho para montar a data.
  2. Se a página for imagem (digitalizada) ou o texto não passar na validação:
     - visão (Claude API), se houver chave configurada — o caminho confiável
       para scans de baixa resolução;
     - Tesseract como último recurso, sempre marcado como "baixa confiança".
  3. Validação de cada dia (ordem cronológica, pares completos, jornada
     plausível, dia da semana) e alertas para revisão humana.
"""
from __future__ import annotations

import base64
import io
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher

MAX_PARES = 6

# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------

def sem_acento(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def parecido(a: str, b: str, limiar: float = 0.8) -> bool:
    return a == b or SequenceMatcher(None, a, b).ratio() >= limiar


RE_HORA = re.compile(r"(?<![\d:/])([01]?\d|2[0-3])[:hH]([0-5]\d)(?![\d/])")
RE_DATA = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})(?!\d)")
RE_PERIODO = re.compile(
    r"(\d{2}/\d{2}/\d{4})\s*(?:a|at[eé]|ate|à|-|–)\s*(\d{2}/\d{2}/\d{2,4})", re.I
)

DIAS_SEMANA = {
    "seg": 0, "ter": 1, "qua": 2, "qui": 3, "sex": 4, "sab": 5, "dom": 6,
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}

# Cabeçalhos das colunas de marcação e das colunas de totais
CAB_MARCACAO = ["entrada", "saida", "ent", "sai", "marcacoes", "marcacao",
                "batidas", "registros", "e1", "s1", "e2", "s2"]
CAB_TOTAIS = ["credito", "debito", "trab", "trabalhadas", "intervalo", "normais",
              "extras", "extra", "total", "totais", "saldo", "dtap", "faltas",
              "atraso", "noturno", "noturnas", "adic", "ht", "abono", "banco"]

OCORRENCIAS = [
    "ferias", "folga", "dsr", "d.s.r", "feriado", "atestado", "falta", "faltas",
    "compensado", "compensacao", "liberacao", "liberado", "termino de producao",
    "licenca", "suspensao", "afastamento", "abono", "aviso previo", "desligamento",
    "integracao", "dispensa", "ajuste", "troca de feriado", "natal",
]


def normaliza_hora(tok: str) -> str | None:
    m = RE_HORA.search(tok)
    if not m:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def horas_do_texto(txt: str) -> list[str]:
    return [f"{int(h):02d}:{m}" for h, m in RE_HORA.findall(txt)]


def para_min(h: str) -> int:
    hh, mm = h.split(":")
    return int(hh) * 60 + int(mm)


def parse_data(txt: str) -> date | None:
    m = RE_DATA.search(txt)
    if not m:
        return None
    d, mo, a = int(m.group(1)), int(m.group(2)), m.group(3)
    a = int(a) + (2000 if len(a) == 2 else 0)
    try:
        return date(a, mo, d)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Estruturas
# --------------------------------------------------------------------------

@dataclass
class Dia:
    data: date
    marcacoes: list[str] = field(default_factory=list)
    ocorrencia: str = ""
    origem: str = ""          # texto | visao | tesseract | legado
    pagina: int = 0
    alertas: list[str] = field(default_factory=list)


@dataclass
class ResultadoPagina:
    pagina: int
    dias: list[Dia]
    metodo: str
    periodo: tuple[date, date] | None = None
    nota: str = ""

    @property
    def score(self) -> float:
        """Fração de dias com marcações coerentes (0-1)."""
        if not self.dias:
            return 0.0
        esperado = None
        if self.periodo:
            esperado = (self.periodo[1] - self.periodo[0]).days + 1
        bons = sum(1 for d in self.dias
                   if (d.marcacoes and not validar_marcacoes(d.marcacoes))
                   or (not d.marcacoes and d.ocorrencia))
        base = max(len(self.dias), esperado or 0)
        return bons / base if base else 0.0


# --------------------------------------------------------------------------
# Validação
# --------------------------------------------------------------------------

def validar_marcacoes(m: list[str]) -> list[str]:
    """Regras de coerência. Retorna lista de alertas (vazia = ok)."""
    alertas = []
    if not m:
        return alertas
    if len(m) % 2:
        alertas.append("número ímpar de marcações")
    viradas = 0
    for a, b in zip(m, m[1:]):
        if para_min(b) <= para_min(a):
            viradas += 1
    if viradas > 1:
        alertas.append("marcações fora de ordem")
    # duração total (considera virada de dia)
    if len(m) >= 2:
        ini, fim = para_min(m[0]), para_min(m[-1])
        dur = fim - ini if fim > ini else fim + 1440 - ini
        if dur > 16 * 60:
            alertas.append("jornada acima de 16h")
    return alertas


def validar_dia(d: Dia):
    d.alertas = list(dict.fromkeys(validar_marcacoes(d.marcacoes) + d.alertas))
    if d.marcacoes and d.ocorrencia and any(
            k in sem_acento(d.ocorrencia) for k in ("ferias", "atestado", "falta")):
        d.alertas.append(f"marcações em dia de {d.ocorrencia.lower()}")


# --------------------------------------------------------------------------
# Leitura por camada de texto (coordenadas)
# --------------------------------------------------------------------------

def _inclinacao(words, tol=2.5):
    """Estima a inclinação do scan (dy/dx) a partir de palavras já alinhadas."""
    import statistics
    grupos = _agrupar(words, tol, 0.0)
    slopes = []
    for g in grupos:
        ws = g["w"]
        if len(ws) < 3 or ws[-1]["x0"] - ws[0]["x0"] < 60:
            continue
        xs = [(w["x0"] + w["x1"]) / 2 for w in ws]
        ys = [(w["top"] + w["bottom"]) / 2 for w in ws]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        den = sum((x - mx) ** 2 for x in xs)
        if den:
            slopes.append(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den)
    if len(slopes) < 3:
        return 0.0
    s = statistics.median(slopes)
    return s if abs(s) < 0.05 else 0.0


def _agrupar(words, tol, slope):
    ws = []
    for w in words:
        xc = (w["x0"] + w["x1"]) / 2
        ws.append((((w["top"] + w["bottom"]) / 2) - slope * xc, w))
    ws.sort(key=lambda t: (t[0], t[1]["x0"]))
    linhas = []
    for yc, w in ws:
        if linhas and abs(linhas[-1]["y"] - yc) <= tol:
            linhas[-1]["w"].append(w)
            n = len(linhas[-1]["w"])
            linhas[-1]["y"] += (yc - linhas[-1]["y"]) / n
        else:
            linhas.append({"y": yc, "w": [w]})
    return linhas


def _linhas(words, tol=3.0):
    """Agrupa palavras em linhas visuais, corrigindo a inclinação do scan."""
    slope = _inclinacao(words)
    linhas = _agrupar(words, tol, slope)
    for ln in linhas:
        ln["w"].sort(key=lambda w: w["x0"])
        ln["txt"] = " ".join(w["text"] for w in ln["w"])
    return linhas


def _linhas_antigo(words, tol=3.0):
    words = sorted(words, key=lambda w: (round(w["top"]), w["x0"]))
    linhas = []
    for w in words:
        yc = (w["top"] + w["bottom"]) / 2
        for ln in linhas:
            if abs(ln["y"] - yc) <= tol:
                ln["w"].append(w)
                break
        else:
            linhas.append({"y": yc, "w": [w]})
    for ln in linhas:
        ln["w"].sort(key=lambda w: w["x0"])
        ln["txt"] = " ".join(w["text"] for w in ln["w"])
    linhas.sort(key=lambda ln: ln["y"])
    return linhas


def _faixa_marcacoes(linhas):
    """Acha (x_ini, x_fim, y_cabecalho) das colunas de marcação pelo cabeçalho."""
    melhor = None
    for ln in linhas:
        marc = [w for w in ln["w"]
                if any(parecido(re.sub(r"[^a-z0-9]", "", sem_acento(w["text"])), k, 0.8)
                       for k in CAB_MARCACAO)]
        if len(marc) >= 2 or any("marca" in sem_acento(w["text"]) for w in marc):
            if melhor is None or len(marc) > len(melhor[1]):
                melhor = (ln, marc)
    if not melhor:
        return None
    ln_cab, marc = melhor
    for ln in linhas:  # cabeçalho quebrado em duas linhas visuais
        if ln is not ln_cab and abs(ln["y"] - ln_cab["y"]) <= 12:
            marc += [w for w in ln["w"]
                     if any(parecido(re.sub(r"[^a-z0-9]", "", sem_acento(w["text"])), k, 0.8)
                            for k in CAB_MARCACAO)]
    x_ini = min(w["x0"] for w in marc) - 12
    x_max_marc = max(w["x1"] for w in marc)
    # limite direito: primeiro cabeçalho de totais à direita (na mesma faixa vertical)
    candidatos = []
    for ln in linhas:
        if abs(ln["y"] - ln_cab["y"]) > 25:
            continue
        for w in ln["w"]:
            t = re.sub(r"[^a-z]", "", sem_acento(w["text"]))
            if w["x0"] > x_max_marc - 5 and any(parecido(t, k, 0.85) for k in CAB_TOTAIS):
                candidatos.append(w["x0"])
    x_fim = min(candidatos) - 2 if candidatos else x_max_marc + 40
    return x_ini, x_fim, ln_cab["y"]


def _periodo(texto: str):
    m = RE_PERIODO.search(texto)
    if not m:
        return None
    a, b = parse_data(m.group(1)), parse_data(m.group(2))
    if a and b and a <= b:
        return a, b
    return None


def _data_da_linha(ln, periodo, cursor):
    """Data completa na linha ou 'dia + dia da semana' com base no período."""
    ws = ln["w"]
    for w in ws[:3]:
        d = parse_data(w["text"])
        if d:
            return d
    if periodo and len(ws) >= 2:
        t0 = re.sub(r"\D", "", ws[0]["text"])
        t1 = sem_acento(ws[1]["text"])[:3]
        if t0 and 1 <= int(t0) <= 31 and t1 in DIAS_SEMANA:
            dia = int(t0)
            c = cursor or periodo[0]
            for _ in range(40):
                if c.day == dia and c.weekday() == DIAS_SEMANA[t1]:
                    return c
                c += timedelta(days=1)
            # sem conferir dia da semana
            c = cursor or periodo[0]
            for _ in range(40):
                if c.day == dia:
                    return c
                c += timedelta(days=1)
    return None


def _ocorrencia(txt: str) -> str:
    s = sem_acento(txt)
    achadas = [o for o in OCORRENCIAS if re.search(r"\b" + re.escape(o) + r"\b", s)]
    if not achadas:
        return ""
    # devolve o trecho original só com palavras "limpas" (sem horários, códigos e lixo de OCR)
    palavras = re.findall(r"[A-Za-zÀ-ú][A-Za-zÀ-ú.]{1,}", txt)
    palavras = [p for p in palavras
                if sem_acento(p).strip(".")[:3] not in DIAS_SEMANA or len(p) > 4]
    trecho = " ".join(p for p in palavras if len(p) >= 3 or p.lower() in ("de", "da", "do"))
    return trecho.strip(" ,.-")[:60] or achadas[0].title()


def _monotonicas(horas: list[str]) -> list[str]:
    """Heurística sem cabeçalho: pega a sequência crescente inicial
    (permite uma virada de meia-noite)."""
    out, virou = [], False
    for h in horas:
        if not out:
            out.append(h)
            continue
        a, b = para_min(out[-1]), para_min(h)
        if b > a:
            out.append(h)
        elif not virou and a >= 18 * 60 and b <= 9 * 60:
            virou = True
            out.append(h)
        else:
            break
    return out[: 2 * MAX_PARES]


def ler_pagina_texto(page, num: int) -> ResultadoPagina:
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
    texto = page.extract_text() or ""
    periodo = _periodo(texto)
    linhas = _linhas(words)
    faixa = _faixa_marcacoes(linhas)
    dias, cursor = [], None
    for ln in linhas:
        if faixa and ln["y"] <= faixa[2]:
            continue
        d = _data_da_linha(ln, periodo, cursor)
        if not d:
            continue
        if periodo and not (periodo[0] - timedelta(days=1) <= d <= periodo[1] + timedelta(days=1)):
            continue
        alertas = []
        if cursor and (d <= cursor or (d - cursor).days > 7):
            alertas.append("data fora de sequência (conferir leitura)")
        cursor = d
        if faixa:
            x0, x1, _ = faixa
            zona = [w for w in ln["w"] if x0 <= (w["x0"] + w["x1"]) / 2 <= x1]
            horas = horas_do_texto(" ".join(w["text"] for w in zona))[: 2 * MAX_PARES]
            ocor = _ocorrencia(" ".join(w["text"] for w in ln["w"]))
        else:
            resto = " ".join(w["text"] for w in ln["w"][1:])
            # corta no primeiro texto que não seja dia da semana (ocorrência):
            # horários depois dele pertencem à ocorrência, não são marcações
            corte = []
            for tok in resto.split():
                letras = re.sub(r"[^A-Za-zÀ-ú]", "", tok)
                if len(letras) >= 1 and sem_acento(letras)[:3] not in DIAS_SEMANA:
                    break
                corte.append(tok)
            horas = _monotonicas(horas_do_texto(" ".join(corte)))
            if len(horas) % 2 and len(horas) >= 3:
                alertas.append(f"descartado {horas[-1]} (provável total, não marcação)")
                horas = horas[:-1]
            ocor = _ocorrencia(resto)
        dias.append(Dia(d, horas, ocor, "texto", num, alertas))
    nota = "cabeçalho de marcações encontrado" if faixa else "sem cabeçalho: heurística cronológica"
    dias, descartados = _remover_datas_discrepantes(dias)
    if descartados:
        nota += f" | {descartados} linha(s) com data implausível descartada(s)"
    return ResultadoPagina(num, dias, "texto", periodo, nota)


def _remover_datas_discrepantes(dias, janela=40):
    """Numa página de cartão os dias ficam em ~1 mês: descarta datas muito
    distantes da mediana (típico de OCR que lê 2024 como 2020)."""
    if len(dias) < 3:
        return dias, 0
    ords = sorted(d.data.toordinal() for d in dias)
    mediana = ords[len(ords) // 2]
    bons = [d for d in dias if abs(d.data.toordinal() - mediana) <= janela]
    return bons, len(dias) - len(bons)


def pagina_eh_imagem(page) -> bool:
    """True se a página é basicamente uma imagem (scan), mesmo que o PJe
    tenha colocado uma camada de OCR invisível por cima."""
    area = float(page.width * page.height)
    for img in page.images:
        w = abs(img["x1"] - img["x0"])
        h = abs(img["bottom"] - img["top"])
        if w * h >= 0.6 * area:
            return True
    return False


# --------------------------------------------------------------------------
# Visão (Claude API)
# --------------------------------------------------------------------------

PROMPT_VISAO = """Você é um transcritor de cartões de ponto trabalhistas brasileiros.
Transcreva a tabela diária desta página com fidelidade absoluta.

Regras:
- Uma linha por dia da tabela, na ordem em que aparecem.
- "data": sempre dd/mm/aaaa. Se a tabela só mostra o dia (ex.: "26 QUA"), monte a
  data completa usando o período impresso no cabeçalho.
- "marcacoes": SOMENTE os horários de entrada e saída registrados (colunas de
  marcação / Entrada / Saída / batidas), na ordem. NUNCA inclua totais (horas
  trabalhadas, normais, crédito, débito, extras, intervalo, saldo, DTAP, faltas).
- Horários no formato HH:MM. Não corrija, não arredonde, não invente horário.
  Se um dígito estiver ilegível, use "?" no lugar dele (ex.: "0?:55").
- "ocorrencia": texto de ocorrência do dia, se houver (Folga, DSR, Férias,
  Feriado, Atestado, Falta, Compensado, Liberação pela Empresa etc.). Senão "".
- "duvida": true se algo na linha estiver ilegível ou ambíguo.
- "periodo": período do cartão como impresso ("dd/mm/aaaa a dd/mm/aaaa") ou "".
- Se a página não for um cartão de ponto, devolva "linhas": [].

Responda APENAS com JSON válido, sem texto antes ou depois:
{"periodo": "...", "linhas": [{"data": "dd/mm/aaaa", "marcacoes": ["HH:MM"], "ocorrencia": "", "duvida": false}]}"""


def imagem_pagina_png(page, dpi=200) -> bytes:
    img = page.to_image(resolution=dpi).original.convert("L")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def extrair_json(txt: str) -> dict:
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    ini, fim = txt.find("{"), txt.rfind("}")
    return json.loads(txt[ini:fim + 1])


def interpretar_visao(dados: dict, num: int) -> ResultadoPagina:
    periodo = _periodo(dados.get("periodo", "") or "")
    dias = []
    for ln in dados.get("linhas", []):
        d = parse_data(ln.get("data", ""))
        if not d:
            continue
        marc, alertas = [], []
        for h in ln.get("marcacoes", [])[: 2 * MAX_PARES]:
            hn = normaliza_hora(str(h))
            if hn:
                marc.append(hn)
            else:
                alertas.append(f"horário ilegível: {h}")
        if ln.get("duvida"):
            alertas.append("leitura duvidosa")
        dias.append(Dia(d, marc, (ln.get("ocorrencia") or "").strip(), "visao", num, alertas))
    dias, descartados = _remover_datas_discrepantes(dias)
    nota = f"{descartados} linha(s) com data implausível descartada(s)" if descartados else ""
    return ResultadoPagina(num, dias, "visao", periodo, nota)


def ler_pagina_visao(page, num: int, api_key: str, modelo: str) -> ResultadoPagina:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    png = imagem_pagina_png(page)
    resp = client.messages.create(
        model=modelo,
        max_tokens=8000,
        temperature=0,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                             "data": base64.b64encode(png).decode()}},
                {"type": "text", "text": PROMPT_VISAO},
            ],
        }],
    )
    texto = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return interpretar_visao(extrair_json(texto), num)


# --------------------------------------------------------------------------
# Tesseract (último recurso)
# --------------------------------------------------------------------------

def _idioma_tesseract():
    try:
        import pytesseract
        langs = set(pytesseract.get_languages(config=""))
        return "por" if "por" in langs else "eng"
    except Exception:
        return "eng"


def ler_pagina_tesseract(page, num: int) -> ResultadoPagina:
    import numpy as np
    import pytesseract
    escala = 400 / 72
    img = np.array(page.to_image(resolution=400).original.convert("L"))
    d = pytesseract.image_to_data(img, lang=_idioma_tesseract(), config="--psm 6",
                                  output_type=pytesseract.Output.DICT)
    # converte para o mesmo formato de palavras do pdfplumber (em pontos)
    words = []
    for i, t in enumerate(d["text"]):
        t = (t or "").strip()
        if not t:
            continue
        t = t.replace("O", "0") if re.fullmatch(r"[\dO]{1,2}[:.][\dO]{2}", t) else t
        t = re.sub(r"^(\d{1,2})[.,](\d{2})$", r"\1:\2", t)
        x, y, w, h = d["left"][i], d["top"][i], d["width"][i], d["height"][i]
        words.append({"text": t, "x0": x / escala, "x1": (x + w) / escala,
                      "top": y / escala, "bottom": (y + h) / escala})

    class _P:  # adaptador mínimo para reaproveitar o parser de texto
        def extract_words(self, **_):
            return words

        def extract_text(self):
            return " ".join(w["text"] for w in words)

    r = ler_pagina_texto(_P(), num)
    for dia in r.dias:
        dia.origem = "tesseract"
        dia.alertas.append("OCR Tesseract: conferir")
    r.metodo = "tesseract"
    return r


# --------------------------------------------------------------------------
# Orquestração
# --------------------------------------------------------------------------

def processar_pdf(arquivo, api_key: str | None = None, modelo: str = "claude-sonnet-5",
                  forcar_visao: bool = False, usar_tesseract: bool = True,
                  score_minimo: float = 0.9, confiar_ocr_pdf: bool = False,
                  progresso=None):
    """Retorna (lista_de_Dia, lista_de_ResultadoPagina)."""
    import pdfplumber

    resultados = []
    with pdfplumber.open(arquivo) as pdf:
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            if progresso:
                progresso(i, total)
            eh_img = pagina_eh_imagem(page)
            r_txt = ler_pagina_texto(page, i)
            escolhido = r_txt
            if eh_img:
                escolhido.nota += " | página digitalizada (texto é OCR do PDF)"
                for dd in escolhido.dias:
                    dd.origem = "ocr-pdf"

            precisa = (forcar_visao or r_txt.score < score_minimo
                       or (eh_img and not (confiar_ocr_pdf and r_txt.score >= 0.999)))
            if precisa and api_key:
                try:
                    r_vis = ler_pagina_visao(page, i, api_key, modelo)
                    if r_vis.dias or not r_txt.dias:
                        escolhido = r_vis
                except Exception as e:  # mantém o texto se a API falhar
                    escolhido.nota += f" | visão falhou: {e}"
            elif precisa and usar_tesseract and (eh_img or not r_txt.dias):
                try:
                    r_tes = ler_pagina_tesseract(page, i)
                    if r_tes.score > r_txt.score:
                        escolhido = r_tes
                except Exception as e:
                    escolhido.nota += f" | tesseract indisponível: {e}"

            if escolhido.metodo == "texto" and eh_img:
                for dd in escolhido.dias:
                    dd.alertas.append("OCR do PDF: conferir")
            resultados.append(escolhido)

    return consolidar(resultados), resultados


def consolidar(resultados: list[ResultadoPagina]) -> list[Dia]:
    por_data: dict[date, Dia] = {}
    for r in resultados:
        for d in r.dias:
            validar_dia(d)
            atual = por_data.get(d.data)
            if atual is None:
                por_data[d.data] = d
                continue
            # data repetida (períodos sobrepostos): fica a leitura mais completa e sem alertas
            chave = lambda x: (len(x.marcacoes), -len(x.alertas))
            venc, perd = (d, atual) if chave(d) > chave(atual) else (atual, d)
            if perd.marcacoes and perd.marcacoes != venc.marcacoes:
                venc.alertas.append(f"data repetida na pág. {perd.pagina} com marcações diferentes")
            por_data[d.data] = venc
    if not por_data:
        return []
    ini, fim = min(por_data), max(por_data)
    dias = []
    c = ini
    while c <= fim:
        dias.append(por_data.get(c) or Dia(c, [], "", "", 0, ["dia ausente no PDF"]))
        c += timedelta(days=1)
    return dias


def para_dataframe(dias: list[Dia], extras: bool = False):
    import pandas as pd
    linhas = []
    for d in dias:
        ln = {"Data": d.data.strftime("%d/%m/%Y")}
        pares = d.marcacoes + [""] * (2 * MAX_PARES - len(d.marcacoes))
        for i in range(MAX_PARES):
            ln[f"Entrada{i + 1}"] = pares[2 * i]
            ln[f"Saída{i + 1}"] = pares[2 * i + 1]
        if extras:
            ln["Ocorrência"] = d.ocorrencia
            ln["Origem"] = d.origem
            ln["Página"] = d.pagina or ""
            ln["Alertas"] = "; ".join(dict.fromkeys(d.alertas))
        linhas.append(ln)
    return pd.DataFrame(linhas)
