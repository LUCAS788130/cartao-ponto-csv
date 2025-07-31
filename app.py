import pdfplumber
import csv
import re

def extrair_horarios(linha_marcacoes):
    # Encontra todos os horários com ou sem sufixo (ex: 06:00c, 12:31e)
    return [re.sub(r'[a-zA-Z]$', '', h) for h in re.findall(r'\d{2}:\d{2}[a-zA-Z]?', linha_marcacoes)]

def processar_cartao_ponto(pdf_path, csv_path):
    with pdfplumber.open(pdf_path) as pdf:
        dados = []

        for pagina in pdf.pages:
            linhas = pagina.extract_text().split('\n')

            for linha in linhas:
                partes = linha.strip().split()
                if len(partes) < 2:
                    continue

                # Tenta identificar se a linha começa com número de dia
                if re.fullmatch(r'\d{1,2}', partes[0]):
                    dia = partes[0].zfill(2)
                    # Junta tudo exceto o dia para extrair horários
                    linha_marcacoes = ' '.join(partes[1:])

                    # Ignora trecho após a palavra "Ocorrência" (se existir)
                    if 'OCORRÊNCIA' in linha_marcacoes.upper():
                        linha_marcacoes = linha_marcacoes.split('OCORRÊNCIA')[0]

                    horarios = extrair_horarios(linha_marcacoes)

                    # Preenche até 6 pares de entrada/saída (12 colunas)
                    linha_csv = [dia]
                    linha_csv += horarios + [''] * (12 - len(horarios))
                    dados.append(linha_csv)

        # Garantir que todos os dias do mês estejam presentes (1 a 31)
        dias_presentes = {linha[0] for linha in dados}
        for dia in range(1, 32):
            dia_str = str(dia).zfill(2)
            if dia_str not in dias_presentes:
                dados.append([dia_str] + [''] * 12)

        # Ordenar os dados pelo dia
        dados.sort(key=lambda x: int(x[0]))

        # Cabeçalho CSV
        cabecalho = ['Dia']
        for i in range(1, 7):
            cabecalho += [f'Entrada{i}', f'Saída{i}']

        # Salvar CSV
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(cabecalho)
            writer.writerows(dados)

# Exemplo de uso:
# processar_cartao_ponto('Documento_e6b1f58.pdf', 'saida.csv')
