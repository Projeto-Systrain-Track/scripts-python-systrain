from datetime import date, datetime
import pandas as pd;
import psutil;
import time;
import csv;
import os;

# ============= Imports p/ S3 ============= #
import logging
import boto3
from botocore.exceptions import ClientError
# ========================================= #

path_to_csv = (f"{datetime.now().day}-{datetime.now().month}-{datetime.now().year}-{datetime.now().hour}:{datetime.now().minute}.csv")
INTERVALO = 5
#CONTADOR = 0
    
p = psutil.Process()

def listar_processos():
    return [proc.info for proc in psutil.process_iter(attrs=['pid', 'name', 'username', 'cpu_percent', 'memory_info'])]

def captura_dados():
    final_io = psutil.disk_io_counters()

    pular = "\n" * 2

    while True: 

#        CONTADOR += 1

        processos = listar_processos()

        porcentagem_uso_da_cpu = psutil.cpu_percent(INTERVALO)
        cpu_freq = psutil.cpu_freq()

        porcentagem_uso_do_disco = psutil.disk_usage("/").percent 
        initial_io = psutil.disk_io_counters()
        
        read_bytes_diff = initial_io.read_bytes - final_io.read_bytes 
        write_bytes_diff = initial_io.write_bytes - final_io.write_bytes
        
        read_rate_Bps = read_bytes_diff / INTERVALO
        write_rate_Bps = write_bytes_diff / INTERVALO
        
        memoria = psutil.virtual_memory();  
        memoria_total = memoria.total;  
        memoria_disponivel = memoria.available
        memoria_percentual = (memoria_disponivel / memoria_total) * 100

        timestamp_atual = datetime.now()

        timestamp_formatado = timestamp_atual.isoformat()

        new_row_dataframe = pd.DataFrame({
            "usuario": [os.getlogin()],
            "porcentagem_uso_da_cpu": [porcentagem_uso_da_cpu],
            "frequencia_atual": [int(cpu_freq.current)],
            "frequencia_min": [int(cpu_freq.min)],
            "frequencia_max": [int(cpu_freq.max)],
            "porcentagem_uso_do_disco": [porcentagem_uso_do_disco],
            "read_rate_Bps": [int(read_rate_Bps)],
            "write_rate_Bps": [int(write_rate_Bps)],
            "memoria_percentual": [int(memoria_percentual)],
            "memoria_total": [int(memoria_total)],
            "memoria_livre": [int(memoria_disponivel)],
            "processos": [str(processos)],
            "data": [timestamp_formatado]
        })


        if not os.path.exists(path_to_csv):
            new_row_dataframe.to_csv(path_to_csv, mode='a', index=False, header=True)
            print(new_row_dataframe)

        else:
            new_row_dataframe.to_csv(path_to_csv, mode='a', index=False, header=False)
            print(new_row_dataframe)


        time.sleep(INTERVALO)    
        final_io = psutil.disk_io_counters()

#        if (CONTADOR == 60):
#            upload_file()
#            CONTADOR = 0

   
captura_dados()