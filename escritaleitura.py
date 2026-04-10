import csv
import psutil
import time
import os
from datetime import datetime

nome_arquivo = "registros.csv"

# verifica se o arquivo já existe
arquivo_existe = os.path.isfile(nome_arquivo)

# cria o arquivo com cabeçalho se não existir
if not arquivo_existe:
    with open(nome_arquivo, mode="w", newline="", encoding="utf-8") as arquivo:
        escrever = csv.writer(arquivo, delimiter=";")
        escrever.writerow(["USO_CPU", "RAM_USADA", "DISCO_%", "DATAHORA"])

# carrega registros antigos na memória
dados = []

if arquivo_existe:
    with open(nome_arquivo, mode="r", encoding="utf-8") as arquivo:
        leitor = csv.reader(arquivo, delimiter=";")
        next(leitor, None)  # pula cabeçalho
        for linha in leitor:
            dados.append(linha)

while True:

    # mede atividade de disco
    disk1 = psutil.disk_io_counters()
    time.sleep(1)
    disk2 = psutil.disk_io_counters()

    operacoes1 = disk1.read_count + disk1.write_count
    operacoes2 = disk2.read_count + disk2.write_count

    delta = operacoes2 - operacoes1
    uso_disco = round((delta / 1000) * 100, 2)

    cpu_info = psutil.cpu_percent()
    ram_info = psutil.virtual_memory()

    dataHora = datetime.now().strftime("%d-%m-%Y %H:%M:%S")

    linha = [cpu_info, ram_info.used, uso_disco, dataHora]

    # salva no csv
    with open(nome_arquivo, mode="a", newline="", encoding="utf-8") as arquivo:
        escrever = csv.writer(arquivo, delimiter=";")
        escrever.writerow(linha)

    # adiciona na memória
    dados.append(linha)

    # limpa terminal em qualquer OS
    os.system('cls' if os.name == 'nt' else 'clear')

    print(f"CPU: {cpu_info}%")
    print(f"RAM usada: {ram_info.used}")
    print(f"DISCO: {uso_disco}%")
    print(f"DATAHORA: {dataHora}")
    print(f"Total de registros em memória: {len(dados)}")

    time.sleep(5)