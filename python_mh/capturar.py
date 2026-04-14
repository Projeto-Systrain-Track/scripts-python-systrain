from datetime import datetime
import pandas as pd
import psutil
import boto3
import s3fs
import uuid
import time
import os


BUCKET_PATH = 's3://rbc-train-track-sys/data.csv'
INTERVALO = 5


aws_keys = {
    "key":          "123",
    "secret":       "321",
    "token":        "000999000"
}

def listar_processos():
    return [p.info['name'] for p in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_info'])]

def pegar_valores():
    #############################################
    #############################################
    mac_num = uuid.getnode()
    mac_address = ':'.join(['{:02x}'.format((mac_num >> i) & 0xff) for i in range(0, 48, 8)][::-1])
    #############################################
    #############################################
    usuario = os.getlogin()
    #############################################
    #############################################
    cpu_freq = psutil.cpu_freq()
    memoria = psutil.virtual_memory()
    #############################################
    #############################################
    io_inicial = psutil.disk_io_counters()
    time.sleep(INTERVALO)
    io_final = psutil.disk_io_counters()
    #############################################
    #############################################
    read_rate_Bps = (io_final.read_bytes - io_inicial.read_bytes) / INTERVALO
    write_rate_Bps = (io_final.write_bytes - io_inicial.write_bytes) / INTERVALO
    #############################################
    #############################################
    processos = listar_processos()
    timestamp_formatado = datetime.now().isoformat()
    #############################################
    #############################################
    new = pd.DataFrame([{
        "mac_address": mac_address,
        "usuario": usuario,
        "frequencia_atual": int(cpu_freq.current),
        "frequencia_min": int(cpu_freq.min),
        "frequencia_max": int(cpu_freq.max),
        "read_rate_Bps": int(read_rate_Bps),
        "write_rate_Bps": int(write_rate_Bps),
        "memoria_total": int(memoria.total),
        "memoria_livre": int(memoria.available),
        "processos": str(processos),
        "data": timestamp_formatado
    }])
    
    return new

def atualizar_s3(novo_df):
    # Configuramos as opções de armazenamento com suas chaves e token
    storage_options = {
        "key": aws_keys["key"],
        "secret": aws_keys["secret"],
        "token": aws_keys["token"]
    }
    
    try:

        df_existente = pd.read_csv(BUCKET_PATH, storage_options=storage_options)
        df_final = pd.concat([df_existente, novo_df], ignore_index=True)
        print("Arquivo existente carregado.")
    except Exception as e:

        print(f"Criando novo arquivo ou erro ao ler: {e}")
        df_final = novo_df
    

    df_final.to_csv(BUCKET_PATH, index=False, storage_options=storage_options)

    dados_atuais = pegar_valores()
    atualizar_s3(dados_atuais)
    
    print(f"Dados enviados com sucesso às {datetime.now()}")




dados_atuais = pegar_valores()
atualizar_s3(dados_atuais)