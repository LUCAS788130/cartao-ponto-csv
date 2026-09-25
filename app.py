"""
Conversor de cartão de ponto (PDF ➜ CSV) — arquivo único.
Partes: 1) motor de leitura  2) tabela de revisão  3) modo antigo JBS  4) interface.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher

import pandas as pd
import pdfplumber
import streamlit as st



# ==========================================================================
# 1) MOTOR DE LEITURA
# ==========================================================================

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
    competencia: str = ""


@dataclass
class ResultadoPagina:
    pagina: int
    dias: list[Dia]
    metodo: str
    periodo: tuple[date, date] | None = None
    nota: str = ""
    periodo_deduzido: bool = False
    fonte_periodo: str = ""   # cabecalho | ordem | dias

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


RE_PERIODO_FLEX = re.compile(
    r"(\d{1,2}/\d{1,2}/\d{4})\s*(?:a|at[eé]|ate|à|-|–|to)\s*(\d{1,2})/(\d{1,2})(?:/(\d{1,4}))?", re.I)


def somar_mes(d: date, n: int = 1) -> date:
    import calendar
    m = d.month - 1 + n
    a, m = d.year + m // 12, m % 12 + 1
    return date(a, m, min(d.day, calendar.monthrange(a, m)[1]))


def _periodo(texto: str):
    """Lê 'dd/mm/aaaa a dd/mm/aaaa' mesmo com o ano final cortado ou coberto
    (ex.: '26/10/2025 a 25/11/20Fls.: 31' → 26/10/2025 a 25/11/2025)."""
    for m in RE_PERIODO_FLEX.finditer(texto or ""):
        ini = parse_data(m.group(1))
        if not ini:
            continue
        d, mo, ano = int(m.group(2)), int(m.group(3)), (m.group(4) or "")
        fim = None
        if len(ano) in (2, 4):
            try:
                fim = date(int(ano) + (2000 if len(ano) == 2 else 0), mo, d)
            except ValueError:
                fim = None
        if fim is None or not (0 <= (fim - ini).days <= 62):
            # ano ausente, cortado ou ilegível: deduz a partir do início
            try:
                fim = date(ini.year + (1 if mo < ini.month else 0), mo, d)
            except ValueError:
                continue
        if 0 <= (fim - ini).days <= 62:
            return ini, fim
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
- "periodo": período do cartão ("dd/mm/aaaa a dd/mm/aaaa") ou "". Se o ano estiver
  cortado ou coberto por carimbo/numeração de folha (ex.: "25/11/20"), complete-o a
  partir da data inicial e dos dias da tabela.
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


def ler_png_visao(png: bytes, num: int, api_key: str, modelo: str) -> ResultadoPagina:
    """Envia a imagem de uma página à IA. Pode rodar em paralelo (não usa o PDF)."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key, max_retries=4, timeout=180)
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


def erro_fatal(e: Exception) -> bool:
    s = f"{type(e).__name__} {e}".lower()
    return any(k in s for k in ("authentication", "x-api-key", "401", "credit", "billing",
                                 "balance", "not_found", "404", "permission", "403"))


def explicar_erro_ia(e: Exception) -> str:
    """Traduz erros da API para uma instrução clara."""
    s = f"{type(e).__name__} {e}".lower()
    if "authentication" in s or "x-api-key" in s or "401" in s:
        return ("A chave da IA foi recusada. Confira ANTHROPIC_API_KEY em "
                "Manage app → Settings → Secrets.")
    if "credit" in s or "billing" in s or "balance" in s:
        return "A conta da IA está sem créditos. Adicione créditos em console.anthropic.com → Billing."
    if "not_found" in s or "404" in s:
        return "O modelo de IA configurado não foi encontrado. Confira ANTHROPIC_MODEL em Secrets."
    if "rate" in s or "429" in s or "overloaded" in s or "529" in s:
        return "A IA está sobrecarregada agora. Tente de novo em alguns minutos."
    if "json" in s or "expecting" in s:
        return "A IA respondeu num formato inesperado em alguma página."
    return f"A IA não respondeu ({type(e).__name__})."


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
                  progresso=None, paralelo: int = 5):
    """Retorna (dias, resultados_por_pagina, erro_da_ia_ou_vazio, cobertura_mes_a_mes).

    progresso(fracao_0_a_1, texto) é chamado para atualizar a tela."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    import pdfplumber

    avisar = progresso or (lambda f, t: None)
    resultados: dict[int, ResultadoPagina] = {}
    imagem: dict[int, bool] = {}
    fila_ia, fila_ocr = [], []
    erro_ia = ""

    with pdfplumber.open(arquivo) as pdf:
        total = len(pdf.pages)
        # Fase 1 (rápida): texto do PDF em todas as páginas
        for i, page in enumerate(pdf.pages, start=1):
            avisar(0.15 * i / total, f"Analisando página {i} de {total}…")
            eh_img = pagina_eh_imagem(page)
            imagem[i] = eh_img
            r_txt = ler_pagina_texto(page, i)
            if eh_img:
                r_txt.nota += " | página digitalizada"
                for dd in r_txt.dias:
                    dd.origem = "ocr-pdf"
            resultados[i] = r_txt
            precisa = (forcar_visao or r_txt.score < score_minimo
                       or (eh_img and not (confiar_ocr_pdf and r_txt.score >= 0.999)))
            if precisa and api_key:
                fila_ia.append(i)
            elif precisa and usar_tesseract and (eh_img or not r_txt.dias):
                fila_ocr.append(i)

        # Fase 2: IA em paralelo (as imagens são geradas antes, fora das threads)
        if fila_ia:
            pngs = {}
            for k, n in enumerate(fila_ia, start=1):
                avisar(0.15 + 0.10 * k / len(fila_ia), f"Preparando imagens ({k} de {len(fila_ia)})…")
                pngs[n] = imagem_pagina_png(pdf.pages[n - 1])
            feitas, falhas = 0, []
            with ThreadPoolExecutor(max_workers=paralelo) as ex:
                futuros = {ex.submit(ler_png_visao, pngs[n], n, api_key, modelo): n for n in fila_ia}
                for fut in as_completed(futuros):
                    n = futuros[fut]
                    feitas += 1
                    avisar(0.25 + 0.75 * feitas / len(fila_ia),
                           f"IA lendo as páginas escaneadas: {feitas} de {len(fila_ia)} prontas…")
                    try:
                        r_vis = fut.result()
                        if r_vis.dias or not resultados[n].dias:
                            resultados[n] = r_vis
                    except Exception as e:
                        falhas.append(n)
                        erro_ia = erro_ia or explicar_erro_ia(e)
                        resultados[n].nota += " | a IA não conseguiu ler esta página"
                        if erro_fatal(e):  # chave, crédito ou modelo: insistir não adianta
                            for f, m in futuros.items():
                                if f.cancel():
                                    falhas.append(m)
                                    resultados[m].nota += " | a IA não conseguiu ler esta página"
                            avisar(0.25, "A IA não está disponível. Lendo com o OCR gratuito…")
                            break
            fila_ocr += [n for n in falhas if usar_tesseract and imagem[n]]

        # Fase 3: OCR gratuito (sem IA, ou onde a IA falhou)
        for k, n in enumerate(sorted(fila_ocr), start=1):
            avisar(0.15 + 0.85 * k / len(fila_ocr), f"Lendo página escaneada {k} de {len(fila_ocr)}…")
            try:
                r_tes = ler_pagina_tesseract(pdf.pages[n - 1], n)
                if r_tes.score > resultados[n].score:
                    resultados[n] = r_tes
            except Exception:
                resultados[n].nota += " | OCR gratuito indisponível"

    lista = [resultados[n] for n in sorted(resultados)]
    for r in lista:
        if r.metodo == "texto" and imagem[r.pagina]:
            for dd in r.dias:
                dd.alertas.append("OCR do PDF: conferir")
    dia_ini, cobertura = ajustar_periodos(lista)
    dias = consolidar(lista)
    faltando = [(c["_ini"], c["_fim"], c["Competência"]) for c in cobertura
                if c["Situação"].startswith("Faltando")]
    for d in dias:
        d.competencia = competencia(d.data, dia_ini)
        if "dia ausente no PDF" in d.alertas and any(a <= d.data <= b for a, b, _ in faltando):
            d.alertas = ["período inteiro ausente do PDF"]
    avisar(1.0, "Pronto.")
    return dias, lista, erro_ia, cobertura


def janela(d: date, dia_ini: int) -> tuple[date, date]:
    """Período de apuração (ciclo da empresa) que contém a data d."""
    import calendar
    ult = calendar.monthrange(d.year, d.month)[1]
    if d.day >= min(dia_ini, ult):
        ini = date(d.year, d.month, min(dia_ini, ult))
    else:
        ant = somar_mes(date(d.year, d.month, 1), -1)
        ini = date(ant.year, ant.month, min(dia_ini, calendar.monthrange(ant.year, ant.month)[1]))
    fim = somar_mes(date(ini.year, ini.month, 1), 1)
    fim = date(fim.year, fim.month, min(dia_ini, calendar.monthrange(fim.year, fim.month)[1])) - timedelta(days=1)
    return ini, fim


def competencia(d: date, dia_ini: int) -> str:
    return f"{janela(d, dia_ini)[1]:%m/%Y}"


def _idx_mes(p) -> int:
    """Número da competência (mês do fim do período)."""
    return p[1].year * 12 + p[1].month - 1


def _periodo_do_idx(idx: int, dia_ini: int):
    return janela(date(idx // 12, idx % 12 + 1, 1), dia_ini)


def ajustar_periodos(lista: list[ResultadoPagina]):
    """Descobre o ciclo (ex.: dia 26 ao 25), deduz o período das páginas sem
    cabeçalho legível (pela ordem das páginas e pelos dias lidos), remove linhas
    fora do período e monta a cobertura mês a mês."""
    from collections import Counter
    for r in lista:
        if r.periodo:
            r.fonte_periodo = "cabecalho"
    inicios = Counter(r.periodo[0].day for r in lista if r.periodo)
    dia_ini = inicios.most_common(1)[0][0] if inicios else 1

    # --- 1) período pela ORDEM das páginas (cartões costumam vir em sequência)
    pos_cab = [(k, _idx_mes(r.periodo)) for k, r in enumerate(lista) if r.fonte_periodo == "cabecalho"]
    meses_cab = Counter(m for _, m in pos_cab)

    def candidato_ordem(k):
        esq = next(((a, m) for a, m in reversed(pos_cab) if a < k), None)
        dir_ = next(((b, m) for b, m in pos_cab if b > k), None)
        if esq and dir_:
            a, ma = esq
            b, mb = dir_
            for s_ in (1, -1):
                if mb - ma == s_ * (b - a):
                    return ma + s_ * (k - a)
        return None  # sem extrapolar: cartões costumam vir em blocos fora de ordem

    for k, r in enumerate(lista):
        if r.fonte_periodo == "cabecalho":
            continue
        pelos_dias = None
        lidos = [d.data for d in r.dias if d.marcacoes or d.ocorrencia]
        if len(lidos) >= 3:
            votos = Counter(_idx_mes(janela(x, dia_ini)) for x in lidos)
            mes, qtd = votos.most_common(1)[0]
            if qtd >= 0.6 * len(lidos):  # a maioria das datas no mesmo mês
                pelos_dias = mes
        cand = candidato_ordem(k)
        usar_ordem = cand is not None and meses_cab[cand] == 0 and (
            pelos_dias is None or pelos_dias == cand or meses_cab[pelos_dias] > 0)
        if usar_ordem:
            r.periodo, r.fonte_periodo = _periodo_do_idx(cand, dia_ini), "ordem"
            r.nota += " | período deduzido pela ordem das páginas"
        elif pelos_dias is not None:
            r.periodo, r.fonte_periodo = _periodo_do_idx(pelos_dias, dia_ini), "dias"
            r.nota += " | período deduzido pelos dias da página"
        r.periodo_deduzido = bool(r.periodo)

    # --- 2) remove linhas fora do período de cada página
    for r in lista:
        if not (r.periodo and r.dias):
            continue
        ini, fim = r.periodo
        fora = [d for d in r.dias if not ini <= d.data <= fim]
        if not fora:
            continue
        if r.fonte_periodo == "ordem" or len(fora) <= 0.3 * len(r.dias):
            r.dias = [d for d in r.dias if ini <= d.data <= fim]
            r.nota += f" | {len(fora)} linha(s) com data fora do período descartada(s)"
        elif r.fonte_periodo == "cabecalho":
            r.nota += " | muitos dias fora do período do cabeçalho: conferir"
            for d in fora:
                d.alertas.append("data fora do período do cabeçalho")

    # --- 3) cobertura mês a mês
    com_periodo = [r for r in lista if r.periodo]
    cobertura = []
    lidos_todos = [d.data for r in lista for d in r.dias if d.marcacoes or d.ocorrencia]
    if com_periodo:
        fim_geral = max(r.periodo[1] for r in com_periodo)
        jan = janela(min(r.periodo[0] for r in com_periodo), dia_ini)
        primeira = jan
        # início e fim do contrato: primeiro e último dia com registro
        ini_contrato = min(lidos_todos) if lidos_todos else jan[0]
        fim_contrato = max(lidos_todos) if lidos_todos else fim_geral
        ultima = janela(fim_geral, dia_ini)
        while jan[0] <= fim_geral:
            paginas = [r for r in com_periodo if r.periodo[0] <= jan[1] and r.periodo[1] >= jan[0]]
            nums = ", ".join(str(r.pagina) for r in paginas)
            if not paginas:
                situacao = "Faltando no PDF"
            elif len(paginas) > 1:
                situacao = f"Repetido (págs. {nums})"
            else:
                r = paginas[0]
                ini, fim = max(r.periodo[0], jan[0]), min(r.periodo[1], jan[1])
                if jan == primeira:
                    ini = max(ini, ini_contrato)
                if jan == ultima:
                    fim = min(fim, fim_contrato)
                if fim < ini:  # página atribuída fora do contrato: dedução não confiável
                    ini, fim = max(r.periodo[0], jan[0]), min(r.periodo[1], jan[1])
                total = (fim - ini).days + 1
                lidos = sum(1 for d in r.dias if ini <= d.data <= fim and (d.marcacoes or d.ocorrencia))
                if lidos < 0.5 * total:
                    situacao = f"Página presente, mas só {lidos} de {total} dias lidos"
                elif (ini, fim) == jan:
                    situacao = "OK"
                else:
                    motivo = ("admissão" if jan == primeira and ini > jan[0]
                              else "rescisão" if jan == ultima and fim < jan[1] else "período parcial")
                    situacao = f"Parcial: {ini:%d/%m} a {fim:%d/%m} ({motivo})"
                if r.fonte_periodo == "ordem":
                    situacao += " · período deduzido pela ordem das páginas"
                elif r.fonte_periodo == "dias":
                    situacao += " · período deduzido pelos dias"
            cobertura.append({
                "Competência": f"{jan[1]:%m/%Y}",
                "Período": f"{jan[0]:%d/%m/%Y} a {jan[1]:%d/%m/%Y}",
                "Página": nums or "—",
                "Situação": situacao,
                "_ini": jan[0], "_fim": jan[1],
            })
            jan = janela(jan[1] + timedelta(days=1), dia_ini)
    sem_mes = [str(r.pagina) for r in lista if not r.periodo]
    if sem_mes:
        for c in cobertura:
            if c["Situação"] == "Faltando no PDF":
                c["Situação"] = ("Não identificado: pode estar numa das páginas não lidas "
                                 f"({', '.join(sem_mes)})")
    return dia_ini, cobertura


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

# ==========================================================================
# 2) TABELA DE REVISÃO
# ==========================================================================

DIAS_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
OK, CONFERIR, SEM_REGISTRO = "✓ OK", "⚠ Conferir", "— Sem registro"
COLS_ES = [f"{t}{i}" for i in range(1, MAX_PARES + 1) for t in ("Entrada", "Saída")]
RE_HORA_OK = r"^(([01]\d|2[0-3]):[0-5]\d)?$"


def motivo_simples(alerta: str) -> str:
    a = alerta.lower()
    regras = [
        ("ocr do pdf", "Página escaneada lida sem IA"),
        ("tesseract", "Página escaneada lida sem IA"),
        ("período inteiro ausente", "Mês inteiro ausente do PDF"),
        ("dia ausente", "Dia não aparece no PDF"),
        ("fora do período do cabeçalho", "Data fora do período impresso na página"),
        ("ímpar", "Falta uma entrada ou saída"),
        ("fora de ordem", "Horários fora de ordem"),
        ("16h", "Jornada acima de 16h"),
        ("fora de sequência", "Data pode ter sido mal lida"),
        ("duvidosa", "A IA ficou em dúvida nesta linha"),
        ("data repetida", "Dia repetido em outra página"),
    ]
    for chave, texto in regras:
        if chave in a:
            return texto
    m = re.search(r"ilegível: (.+)", alerta)
    if m:
        return f"Horário ilegível ({m.group(1)})"
    m = re.search(r"descartado (\d\d:\d\d)", alerta)
    if m:
        return f"{m.group(1)} ignorado (parece total, não marcação)"
    m = re.search(r"marcações em dia de (.+)", alerta)
    if m:
        return f"Marcação em dia de {m.group(1)}"
    return alerta


def montar_tabela(dias) -> pd.DataFrame:
    linhas = []
    for d in dias:
        motivos = list(dict.fromkeys(motivo_simples(a) for a in d.alertas))
        if "Dia não aparece no PDF" in motivos or "Mês inteiro ausente do PDF" in motivos:
            situacao = SEM_REGISTRO
        elif motivos:
            situacao = CONFERIR
        else:
            situacao = OK
        ln = {
            "Situação": situacao,
            "Data": d.data.strftime("%d/%m/%Y"),
            "Dia": DIAS_PT[d.data.weekday()],
            "Competência": d.competencia,
        }
        pares = d.marcacoes + [""] * (2 * MAX_PARES - len(d.marcacoes))
        ln.update(dict(zip(COLS_ES, pares)))
        ln["Ocorrência"] = d.ocorrencia
        ln["Motivo"] = "; ".join(motivos)
        ln["Pág."] = str(d.pagina) if d.pagina else ""
        ln["Conferido"] = False
        linhas.append(ln)
    return pd.DataFrame(linhas)


def colunas_visiveis(df: pd.DataFrame) -> list[str]:
    """Mostra só os pares de horário usados (mínimo 2 pares)."""
    usados = 2
    for i in range(1, MAX_PARES + 1):
        if (df[f"Entrada{i}"] != "").any() or (df[f"Saída{i}"] != "").any():
            usados = max(usados, i)
    es = [c for c in COLS_ES if int(c[-1]) <= usados]
    return ["Situação", "Competência", "Data", "Dia", *es, "Ocorrência", "Motivo", "Pág.", "Conferido"]


def resumo(df: pd.DataFrame) -> dict:
    conferir = df["Situação"] == CONFERIR
    return {
        "dias": len(df),
        "ok": int((df["Situação"] == OK).sum()),
        "conferir": int(conferir.sum()),
        "conferidos": int((conferir & df["Conferido"]).sum()),
        "sem_registro": int((df["Situação"] == SEM_REGISTRO).sum()),
        "so_scan_sem_ia": int(
            (conferir & (df["Motivo"] == "Página escaneada lida sem IA")).sum()),
        "inicio": df["Data"].iloc[0] if len(df) else "",
        "fim": df["Data"].iloc[-1] if len(df) else "",
    }


def exportar_csv(df: pd.DataFrame, com_conferencia: bool) -> bytes:
    """Mesmo formato de sempre: Data, Entrada1..Saída6 (+ colunas opcionais)."""
    cols = ["Data", *COLS_ES]
    if com_conferencia:
        cols += ["Competência", "Ocorrência", "Situação", "Motivo", "Pág.", "Conferido"]
    saida = df[cols].copy()
    if com_conferencia:
        saida["Conferido"] = saida["Conferido"].map({True: "sim", False: "não"})
    return saida.to_csv(index=False).encode("utf-8")

# ==========================================================================
# 3) MODO ANTIGO (JBS) — lógica original
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
# 4) INTERFACE
# ==========================================================================

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
API_KEY = segredo("ANTHROPIC_API_KEY")
MODELO = segredo("ANTHROPIC_MODEL", "claude-sonnet-5")
SENHA = segredo("APP_SENHA")
IA_ATIVA = bool(API_KEY)

with st.sidebar:
    if IA_ATIVA:
        st.markdown("**✓ Leitura com IA ativa**")
        st.caption("Páginas escaneadas são lidas por IA automaticamente. "
                   "PDFs com texto são lidos direto, sem IA.")
    else:
        st.markdown("**IA não configurada**")
        st.caption("Páginas escaneadas estão sendo lidas por OCR gratuito, que é menos preciso. "
                   "Para ativar a IA, adicione ANTHROPIC_API_KEY em Manage app → Settings → Secrets.")
    with st.expander("Opções avançadas"):
        forcar_visao = st.checkbox("Usar IA em todas as páginas", value=False, disabled=not IA_ATIVA,
                                   help="Inclusive nas que têm texto. Mais lento e mais caro.")
        confiar_ocr = st.checkbox("Economizar chamadas de IA", value=False, disabled=not IA_ATIVA,
                                  help="Aceita o texto embutido do PDF quando ele passa na validação. "
                                       "Mais barato, mas um 06 lido como 08 pode passar despercebido.")
        modo_jbs = st.checkbox("Modo antigo (JBS)", value=False,
                               help="Usa exatamente a lógica anterior, só para PDFs JBS com texto.")


@st.cache_resource
def _resultados_guardados():
    """Guarda resultados já processados (vale para todos os usuários), para não
    pagar a IA duas vezes pelo mesmo PDF."""
    return {}


def ler_pdf(pdf_bytes, opcoes):
    guardados = _resultados_guardados()
    chave = hashlib.md5(pdf_bytes + repr(opcoes).encode()).hexdigest()
    if chave in guardados:
        return guardados[chave]

    barra = st.progress(0.0, text="Abrindo o PDF…")
    dias, res, erro_ia, cobertura = processar_pdf(
        io.BytesIO(pdf_bytes), api_key=API_KEY or None, modelo=MODELO,
        forcar_visao=opcoes["forcar"], confiar_ocr_pdf=opcoes["confiar"],
        progresso=lambda f, t: barra.progress(min(max(f, 0.0), 1.0), text=t))
    barra.empty()

    paginas = pd.DataFrame([{
        "Página": r.pagina,
        "Lida por": {"texto": "Texto do PDF", "visao": "IA",
                     "tesseract": "OCR gratuito"}.get(r.metodo, r.metodo),
        "Período": f"{r.periodo[0]:%d/%m/%Y} a {r.periodo[1]:%d/%m/%Y}" if r.periodo else "—",
        "Dias": len(r.dias),
        "Qualidade": round(r.score * 100),
        "Observação": r.nota.strip(" |"),
    } for r in res])
    meses = pd.DataFrame([{k: v for k, v in c.items() if not k.startswith("_")} for c in cobertura])
    saida = (montar_tabela(dias), paginas, erro_ia, chave, meses)
    if not erro_ia:  # com erro da IA, não guarda: permite tentar de novo
        if len(guardados) >= 30:
            guardados.pop(next(iter(guardados)))
        guardados[chave] = saida
    return saida


# --------------------------------------------------------------------------
# Página
# --------------------------------------------------------------------------
st.markdown("""
<div class="cabecalho">
  <h1>Conversor de cartão de ponto</h1>
  <p>Transforma o cartão de ponto em PDF numa planilha de entradas e saídas por dia,
  e aponta o que precisa de conferência antes do uso.</p>
</div>""", unsafe_allow_html=True)

if SENHA and not st.session_state.get("liberado"):
    digitada = st.text_input("Senha de acesso", type="password")
    if digitada == SENHA:
        st.session_state.liberado = True
        st.rerun()
    if digitada:
        st.error("Senha incorreta.")
    st.stop()

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
        layout = detectar_layout(texto)
        df = (processar_layout_novo(texto) if layout == "novo"
              else processar_layout_antigo(texto))
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
    pdf_bytes = arquivo.getvalue()
    opcoes = {"ia": IA_ATIVA, "modelo": MODELO, "forcar": forcar_visao, "confiar": confiar_ocr}
    tabela, paginas, erro_ia, chave, meses = ler_pdf(pdf_bytes, opcoes)

    if erro_ia:
        st.error(f"**Algumas páginas não puderam ser lidas pela IA.** {erro_ia} "
                 "Essas páginas foram lidas pelo OCR gratuito e estão marcadas para conferência.")

    if tabela.empty:
        passos(1)
        st.error("Não encontrei uma tabela de ponto neste PDF. Confira se é um cartão de ponto "
                 "e se as páginas não estão em branco ou cortadas.")
        st.stop()

    # a tabela editada fica guardada enquanto o mesmo PDF e as mesmas opções estiverem em uso
    if st.session_state.get("chave") != chave:
        st.session_state.chave = chave
        st.session_state.tabela = tabela.copy()
    base = st.session_state.tabela
    r = resumo(base)

    pendentes = r["conferir"] - r["conferidos"]
    passos(2 if pendentes else 3)

    st.markdown(f"""
<div class="numeros">
  <div class="periodo"><span>Período</span><strong>{r['inicio']} a {r['fim']}</strong></div>
  <div><span>Dias no período</span><strong>{r['dias']}</strong></div>
  <div class="{'bom' if r['ok'] else ''}"><span>Lidos sem pendência</span><strong>{r['ok']}</strong></div>
  <div class="{'alerta' if pendentes else 'bom'}"><span>Para conferir</span><strong>{pendentes}</strong></div>
</div>""", unsafe_allow_html=True)

    # explicação quando o problema é a falta de IA
    if not IA_ATIVA and (r["so_scan_sem_ia"] + r["sem_registro"]) > r["dias"] * 0.3:
        st.markdown(f"""
<div class="aviso"><strong>Este PDF é escaneado e a leitura por IA não está ativada.</strong>
{r['sem_registro']} dias ficaram sem registro e {r['so_scan_sem_ia']} vieram de uma leitura imprecisa da imagem.
Com a IA configurada, a leitura destas páginas fica muito mais confiável.</div>""",
                    unsafe_allow_html=True)

    if not meses.empty:
        faltam = meses[meses["Situação"].str.startswith(("Faltando", "Não identificado"))]["Competência"].tolist()
        repetidos = meses[meses["Situação"].str.startswith("Repetido")]["Competência"].tolist()
        if faltam or repetidos:
            partes = []
            if faltam:
                partes.append(f"faltam no PDF: <b>{', '.join(faltam)}</b>")
            if repetidos:
                partes.append(f"aparecem mais de uma vez: <b>{', '.join(repetidos)}</b>")
            st.markdown(f"""<div class="aviso"><strong>Atenção aos meses do cartão.</strong>
Competências que {' e '.join(partes)}. Veja a aba “Meses”.</div>""", unsafe_allow_html=True)

    aba_revisar, aba_meses, aba_paginas = st.tabs(
        ["Revisar dias", f"Meses ({len(meses)})", "Páginas do PDF"])

    with aba_revisar:
        c1, c2 = st.columns([3, 2])
        filtro = c1.radio("Mostrar", ["Para conferir", "Todos os dias", "Sem registro"],
                          horizontal=True, label_visibility="collapsed",
                          index=0 if r["conferir"] else 1)
        if r["conferir"]:
            c2.progress(r["conferidos"] / r["conferir"],
                        text=f"{r['conferidos']} de {r['conferir']} dias conferidos")

        mapa = {"Para conferir": CONFERIR, "Sem registro": SEM_REGISTRO}
        vis = base if filtro == "Todos os dias" else base[base["Situação"] == mapa[filtro]]
        cols = colunas_visiveis(base)

        if vis.empty:
            st.success("Nada para mostrar aqui. Tudo certo nesta categoria.")
        else:
            config = {
                "Situação": st.column_config.TextColumn(width="small"),
                "Data": st.column_config.TextColumn(width="small"),
                "Competência": st.column_config.TextColumn("Compet.", width="small"),
                "Dia": st.column_config.TextColumn(width="small"),
                "Ocorrência": st.column_config.TextColumn(width="medium"),
                "Motivo": st.column_config.TextColumn("Por que conferir", width="large"),
                "Pág.": st.column_config.TextColumn(width="small"),
                "Conferido": st.column_config.CheckboxColumn(width="small"),
            }
            for c in COLS_ES:
                config[c] = st.column_config.TextColumn(
                    c.replace("Entrada", "Ent. ").replace("Saída", "Saí. "),
                    width="small", validate=RE_HORA_OK, help="Formato HH:MM")
            editada = st.data_editor(
                vis[cols], column_config=config, hide_index=True, use_container_width=True,
                height=min(38 + 35 * len(vis), 560),
                disabled=["Situação", "Competência", "Data", "Dia", "Motivo", "Pág."],
                key=f"ed_{chave}_{filtro}",
            )
            textos = [c for c in cols if c in COLS_ES or c == "Ocorrência"]
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

    with aba_meses:
        if meses.empty:
            st.info("Não foi possível identificar os períodos deste cartão.")
        else:
            def _cor(v):
                if v.startswith("OK"):
                    return "color: #2F7D4F"
                if v.startswith(("Faltando", "Repetido", "Página presente", "Não identificado")):
                    return "color: #A15C07; font-weight: 600"
                return "color: #4A5B6E"
            estilo = meses.style
            pintar = getattr(estilo, "map", None) or estilo.applymap  # pandas novo/antigo
            st.dataframe(pintar(_cor, subset=["Situação"]),
                         hide_index=True, use_container_width=True)
            st.caption("Cada linha é um período de apuração do cartão, do primeiro ao último mês. "
                       "“Parcial” marca o mês da admissão ou da rescisão. “Faltando no PDF” "
                       "significa que nenhuma página cobre aquele mês. “Página presente, mas…” "
                       "indica que a página existe e a leitura falhou: confira no PDF.")

    with aba_paginas:
        st.dataframe(
            paginas, hide_index=True, use_container_width=True,
            column_config={"Qualidade": st.column_config.ProgressColumn(
                format="%d%%", min_value=0, max_value=100,
                help="Parte dos dias da página lidos sem nenhuma inconsistência")},
        )
        st.caption("Qualidade é a parte dos dias da página lidos sem nenhuma inconsistência.")

    st.divider()
    d1, d2 = st.columns([2, 3])
    extras = d2.checkbox("Incluir colunas de conferência (situação, motivo, página)", value=False)
    rotulo = "Baixar CSV" if not pendentes else (f"Baixar CSV ({pendentes} dia ainda não conferido)" if pendentes == 1
                                         else f"Baixar CSV ({pendentes} dias ainda não conferidos)")
    d1.download_button(rotulo, exportar_csv(base, extras), "cartao_convertido.csv", "text/csv",
                       type="primary", use_container_width=True)

st.markdown("""
<div class="rodape">
Em conformidade com a LGPD: os arquivos são usados só para a conversão e não ficam guardados neste site.
As imagens das páginas escaneadas são enviadas à API da Anthropic apenas para a transcrição.
<br>Desenvolvido por Lucas de Matos Coelho.
</div>""", unsafe_allow_html=True)
