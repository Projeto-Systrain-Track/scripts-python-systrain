from datetime import datetime
import pandas as pd
import psutil
import uuid
import time
import os
import socket


# BUCKET_PATH = 's3://rbc-train-track-sys/data.csv'
INTERVALO = 5

# aws_keys = {
#     "key": "123",
#     "secret": "321",
#     "token": "000999000"
# }

attrs = [
    'pid', 'name', 'username', 'status', 'create_time',
    'cpu_percent', 'memory_info', 'num_threads',
    'cmdline', 'exe', 'cpu_times', 'memory_percent'
]


def listar_processos():
    return [p.info for p in psutil.process_iter(attrs=attrs)]


def medir_latenciadef():
    try:
        st = speedtest.Speedtest()
        download_speed = st.download()
        upload_speed = st.upload()
        ping = st.results.ping
        return download_speed, upload_speed, ping
    except Exception as e:
        print("Erro ao testar velocidade:", e)
        return 0, 0, 0


def pegar_valores():

    mac_num = uuid.getnode()
    mac_address = ':'.join(
        ['{:02x}'.format((mac_num >> i) & 0xff) for i in range(0, 48, 8)][::-1]
    )
    
    ultimo_download = 0
    ultimo_upload = 0
    ultimo_ping = 0

    try:
        usuario = os.getlogin()
    except Exception:
        usuario = os.environ.get("USERNAME") or os.environ.get("USER") or "desconhecido"


    cpu_freq = psutil.cpu_freq()
    memoria = psutil.virtual_memory()


    io_inicial = psutil.disk_io_counters()
    net_inicial = psutil.net_io_counters()
    latencia_ms = medir_latencia()


    time.sleep(INTERVALO)


    io_final = psutil.disk_io_counters()
    net_final = psutil.net_io_counters()
    
    if CONTADOR == 1 or CONTADOR % 6 == 0:
        ultimo_download, ultimo_upload, ultimo_ping = captura_velocidade()

    download_speed = ultimo_download
    upload_speed = ultimo_upload
    ping = ultimo_ping

    read_rate_Bps = (io_final.read_bytes - io_inicial.read_bytes) / INTERVALO
    write_rate_Bps = (io_final.write_bytes - io_inicial.write_bytes) / INTERVALO


    download_rate_Bps = (net_final.bytes_recv - net_inicial.bytes_recv) / INTERVALO
    upload_rate_Bps = (net_final.bytes_sent - net_inicial.bytes_sent) / INTERVALO

    processos = listar_processos()
    timestamp_formatado = datetime.now().isoformat()

    new = pd.DataFrame([{
        "mac_address": mac_address,
        "usuario": usuario,
        "frequencia_atual": int(cpu_freq.current),
        "frequencia_min": int(cpu_freq.min),
        "frequencia_max": int(cpu_freq.max),
        "read_rate_Bps": int(read_rate_Bps),
        "write_rate_Bps": int(write_rate_Bps),
        "download_rate_Bps": int(download_rate_Bps),
        "upload_rate_Bps": int(upload_rate_Bps),
        "latencia_ms": latencia_ms,
        "memoria_total": int(memoria.total),
        "memoria_livre": int(memoria.available),
        "download_mbps": [str(download_speed)],
        "upload_mbps": [str(upload_speed)],
        "ping_ms": [str(ping)],
        "processos": str(processos),
        "data": timestamp_formatado
    }])

    return new


def atualizar_s3(novo_df):

    # storage_options = {
    #     "key": aws_keys["key"],
    #     "secret": aws_keys["secret"],
    #     "token": aws_keys["token"]
    # }

    # try:
    #     df_existente = pd.read_csv(BUCKET_PATH, storage_options=storage_options)
    #     df_final = pd.concat([df_existente, novo_df], ignore_index=True)

    # except Exception as e:

    df_final = novo_df

    # df_final.to_csv(BUCKET_PATH, index=False, storage_options=storage_options)

    df_final.to_csv('./novo.csv', index=False)

dados_atuais = pegar_valores()
atualizar_s3(dados_atuais)
