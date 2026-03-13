import csv
import psutil
import time
import os
from datetime import datetime

nome_arquivo = 'registros.csv'

with open(nome_arquivo, mode='w', newline='') as arquivo:
    escrever=csv.writer(arquivo, delimiter=';')
    escrever.writerow(['USO_CPU', 'DISK(troughput)', 'MEMORIA_RAM(total, usado)'])

while True:
    disk_info1 = psutil.disk_io_counters()
    time.sleep(1)
    disk_info2 = psutil.disk_io_counters()
    tempo1 = disk_info1.write_count + disk_info1.read_count
    tempo2 = disk_info2.write_count + disk_info2.read_count
    delta_tempo = tempo2 - tempo1
    uso_disco = round(((delta_tempo / 1000) * 100) , 2)
    dataHora = datetime.now().strftime('%d-%m-%Y  %H:%M:%S')
    cpu_info = psutil.cpu_percent()
    ram_info = psutil.virtual_memory()

    with open(nome_arquivo, mode='a', newline='') as arquivo:
        escrever = csv.writer(arquivo, delimiter=';')
        escrever.writerow([cpu_info, ram_info.used, uso_disco, dataHora])
    os.system('cls')
    print(f"CPU: {cpu_info} | RAM : {ram_info.used} | DISCO: {uso_disco}%| DATAHORA: {dataHora}")
    time.sleep(1)