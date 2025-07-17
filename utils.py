import fitz  # PyMuPDF
import re
from datetime import datetime
import pandas as pd

def extrair_texto_pdf(pdf_path):
    texto = ""
    with fitz.open(pdf_path) as doc:
        for page in doc:
            texto += page.get_text()
    return texto

def processar_texto(texto):
    linhas = texto.splitlines()
    padrao_data = re.compile(r"\d{2}/\d{2}/\d{4}")
    dados = []

    for linha in linhas:
        partes = linha.strip().split()
        if len(partes) >= 2 and "/" in partes[0]:
            try:
                data = datetime.strptime(partes[0], "%d/%m/%Y")
                horarios = [p for p in partes[1:] if re.match(r"\d{2}:\d{2}", p)]
                if "D.S.R" in linha.upper() or "ATESTADO" in linha.upper() or "FERIADO" in linha.upper() or "FÉRIAS" in linha.upper() or "COMPENSA" in linha.upper():
                    horarios = []
                dados.append((data.strftime("%d/%m/%Y"), horarios))
            except:
                continue

    if not dados:
        return pd.DataFrame()

    datas_extraidas = [datetime.strptime(d[0], "%d/%m/%Y") for d in dados]
    inicio = min(datas_extraidas)
    fim = max(datas_extraidas)
    datas_completas = pd.date_range(start=inicio, end=fim).to_pydatetime().tolist()

    tabela = []
    for data in datas_completas:
        data_str = data.strftime("%d/%m/%Y")
        horarios = next((h for d, h in dados if d == data_str), [])
        linha = [data_str] + horarios + [""] * (12 - len(horarios))
        tabela.append(linha[:13])  # Data + 6 entradas + 6 saídas

    colunas = ["Data"]
    for i in range(1, 7):
        colunas.extend([f"Entrada{i}", f"Saída{i}"])

    return pd.DataFrame(tabela, columns=colunas)
