from botocore.exceptions import ClientError
from colorama import Fore, init
from typing import Dict
from dotenv import load_dotenv
from datetime import datetime
from pathlib import Path
import pandas as pd
import subprocess
import psutil
import boto3
import uuid
import time
import os

INTERVALO_SEGUNDOS = 3
OUTPUT_DIR = "raw"

ATRIBUTOS_PROCESSOS = [
    'pid', 'name', 'username', 'status', 'create_time',
    'cpu_percent', 'memory_info', 'num_threads',
    'cmdline', 'exe', 'cpu_times', 'memory_percent'
]

load_dotenv(dotenv_path=".env.dev")

NOME_BUCKET = os.getenv("S3_BUCKET_NAME")

s3 = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_DEFAULT_REGION"),
    aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
    endpoint_url=os.getenv("S3_ENDPOINT_URL") or None
)

init(autoreset=True)


def cor_status(valor, limite1=60, limite2=80):
    if valor >= limite2:
        return Fore.RED
    elif valor >= limite1:
        return Fore.YELLOW
    return Fore.GREEN


def ensure_output_dirs(base_dir: str) -> Dict[str, Path]:
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    return {"base": base}


def limpar_terminal():
    os.system('cls' if os.name == 'nt' else 'clear')


def medir_ping(host="8.8.8.8", timeout_segundos=4):
    try:
        comando = ["ping", "-n", "1", host] if os.name == "nt" else ["ping", "-c", "1", host]

        resultado = subprocess.run(
            comando,
            capture_output=True,
            text=True,
            timeout=timeout_segundos
        )

        for linha in resultado.stdout.splitlines():
            linha_lower = linha.lower()

            if "tempo=" in linha_lower:
                tempo = linha_lower.split("tempo=")[1].split("ms")[0].strip()
                return int(float(tempo.replace(",", ".")))

            if "time=" in linha_lower:
                tempo = linha_lower.split("time=")[1].split("ms")[0].strip()
                return int(float(tempo.replace(",", ".")))

        return 0

    except Exception:
        return 0


def get_all_processes():
    process_list = []

    for proc in psutil.process_iter(ATRIBUTOS_PROCESSOS):
        try:
            process_list.append(proc.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    return process_list


def coletar_metricas_sistema():
    mac_numero = uuid.getnode()
    endereco_mac = ':'.join(
        ['{:02x}'.format((mac_numero >> i) & 0xff) for i in range(0, 48, 8)][::-1]
    )

    try:
        nome_usuario = os.getlogin()
    except Exception:
        nome_usuario = os.environ.get("USERNAME") or os.environ.get("USER") or "desconhecido"

    percentual_uso_cpu = psutil.cpu_percent(interval=None)
    frequencia_cpu = psutil.cpu_freq()

    frequencia_cpu_atual_mhz = round(frequencia_cpu.current, 2) if frequencia_cpu else 0
    frequencia_cpu_minima_mhz = round(frequencia_cpu.min, 2) if frequencia_cpu else 0
    frequencia_cpu_maxima_mhz = round(frequencia_cpu.max, 2) if frequencia_cpu else 0

    memoria_virtual = psutil.virtual_memory()
    percentual_uso_ram = memoria_virtual.percent

    memoria_swap = psutil.swap_memory()

    percentual_uso_swap = 0
    if memoria_swap.total > 0:
        percentual_uso_swap = (memoria_swap.used / memoria_swap.total) * 100

    uso_disco = psutil.disk_usage('/')

    io_disco_inicial = psutil.disk_io_counters()
    io_rede_inicial = psutil.net_io_counters()

    time.sleep(INTERVALO_SEGUNDOS)

    io_disco_final = psutil.disk_io_counters()
    io_rede_final = psutil.net_io_counters()

    latencia_ping_ms = medir_ping()

    taxa_leitura_disco_bytes_por_segundo = (
        io_disco_final.read_bytes - io_disco_inicial.read_bytes
    ) / INTERVALO_SEGUNDOS

    taxa_escrita_disco_bytes_por_segundo = (
        io_disco_final.write_bytes - io_disco_inicial.write_bytes
    ) / INTERVALO_SEGUNDOS

    taxa_download_rede_bytes_por_segundo = (
        io_rede_final.bytes_recv - io_rede_inicial.bytes_recv
    ) / INTERVALO_SEGUNDOS

    taxa_upload_rede_bytes_por_segundo = (
        io_rede_final.bytes_sent - io_rede_inicial.bytes_sent
    ) / INTERVALO_SEGUNDOS

    lista_processos = get_all_processes()
    data_hora_iso = datetime.now().isoformat()

    df_metricas = pd.DataFrame([{
        "endereco_mac": endereco_mac,
        "nome_usuario": nome_usuario,

        "percentual_uso_cpu": percentual_uso_cpu,
        "frequencia_cpu_atual_mhz": frequencia_cpu_atual_mhz,
        "frequencia_cpu_minima_mhz": frequencia_cpu_minima_mhz,
        "frequencia_cpu_maxima_mhz": frequencia_cpu_maxima_mhz,

        "memoria_total_bytes": int(memoria_virtual.total),
        "memoria_disponivel_bytes": int(memoria_virtual.available),
        "percentual_uso_ram": percentual_uso_ram,

        "swap_total_bytes": int(memoria_swap.total),
        "swap_usado_bytes": int(memoria_swap.used),
        "swap_livre_bytes": int(memoria_swap.free),
        "swap_entrada_bytes": int(memoria_swap.sin),
        "swap_saida_bytes": int(memoria_swap.sout),
        "percentual_uso_swap": percentual_uso_swap,

        "disco_total_bytes": int(uso_disco.total),
        "disco_usado_bytes": int(uso_disco.used),
        "disco_livre_bytes": int(uso_disco.free),
        "percentual_uso_disco": uso_disco.percent,

        "taxa_leitura_disco_bytes_por_segundo": int(taxa_leitura_disco_bytes_por_segundo),
        "taxa_escrita_disco_bytes_por_segundo": int(taxa_escrita_disco_bytes_por_segundo),

        "latencia_ping_ms": latencia_ping_ms,
        "taxa_download_rede_bytes_por_segundo": int(taxa_download_rede_bytes_por_segundo),
        "taxa_upload_rede_bytes_por_segundo": int(taxa_upload_rede_bytes_por_segundo),

        "processos": str(lista_processos),
        "data_hora_iso": data_hora_iso
    }])

    return df_metricas


def salvar_csv_append(df_atual: pd.DataFrame, caminho_arquivo: Path):
    caminho_arquivo.parent.mkdir(parents=True, exist_ok=True)

    arquivo_existe = caminho_arquivo.exists()

    df_atual.to_csv(
        caminho_arquivo,
        mode="a",
        header=not arquivo_existe,
        index=False
    )


def upload_directory_to_s3(local_dir: str, bucket: str, s3_prefix: str):
    local_path = Path(local_dir)

    for file_path in local_path.rglob("*"):
        if file_path.is_file():
            relative_path = file_path.relative_to(local_path)
            s3_key = f"{s3_prefix}/{relative_path}".replace("\\", "/")

            s3.upload_file(
                Filename=str(file_path),
                Bucket=bucket,
                Key=s3_key
            )

            print(f"Uploaded: s3://{bucket}/{s3_key}")


print(Fore.GREEN + "==========================================")
print(Fore.GREEN + "🚀 SYS TRAIN TRACK - MONITORAMENTO")
print(Fore.GREEN + "==========================================\n")

contador = 0


def iniciar_captura():
    global contador

    dirs = ensure_output_dirs(OUTPUT_DIR)

    nome_arquivo_csv = os.getenv("S3_INPUT_KEY", "df.csv")
    output_s3_prefix = os.getenv("S3_OUTPUT_PREFIX", "raw")

    # Prevent raw/raw/df.csv
    nome_arquivo_csv = Path(nome_arquivo_csv).name

    caminho_csv = dirs["base"] / nome_arquivo_csv

    df_atual = coletar_metricas_sistema()

    salvar_csv_append(df_atual, caminho_csv)

    contador += 1

    if contador >= 5:
        contador = 0

        upload_directory_to_s3(
            local_dir=OUTPUT_DIR,
            bucket=NOME_BUCKET,
            s3_prefix=output_s3_prefix
        )

    dados = df_atual.iloc[0]

    limpar_terminal()

    print(Fore.GREEN + "==========================================")
    print(Fore.GREEN + "📊 MONITORAMENTO EM TEMPO REAL")
    print(Fore.GREEN + "==========================================\n")

    print(Fore.CYAN + f"👤 Usuário: {dados['nome_usuario']}")
    print(Fore.CYAN + f"🕒 {datetime.now().strftime('%H:%M:%S')}")
    print(Fore.CYAN + f"⏱ Intervalo: {INTERVALO_SEGUNDOS}s\n")

    cpu = dados["percentual_uso_cpu"]
    ram = dados["percentual_uso_ram"]
    disco = dados["percentual_uso_disco"]
    ping = dados["latencia_ping_ms"]

    print(Fore.WHITE + "🧠 CPU")
    print(cor_status(cpu) + f"   Uso: {cpu:.1f}%")
    print(Fore.WHITE + f"   Freq: {dados['frequencia_cpu_atual_mhz']} MHz\n")

    print(Fore.WHITE + "💾 RAM")
    print(cor_status(ram) + f"   Uso: {ram:.1f}%")
    print(Fore.WHITE + f"   Livre: {dados['memoria_disponivel_bytes'] // (1024 ** 3)} GB\n")

    print(Fore.WHITE + "🗄 DISCO")
    print(cor_status(disco) + f"   Uso: {disco:.1f}%")
    print(Fore.WHITE + f"   Livre: {dados['disco_livre_bytes'] // (1024 ** 3)} GB\n")

    print(Fore.WHITE + "🌐 REDE")
    print(Fore.CYAN + f"   Ping: {ping} ms")
    print(Fore.MAGENTA + f"   ↓ {dados['taxa_download_rede_bytes_por_segundo']} B/s")
    print(Fore.MAGENTA + f"   ↑ {dados['taxa_upload_rede_bytes_por_segundo']} B/s\n")

    print(Fore.WHITE + "⚙ PROCESSOS")
    print(f"CONTADOR: {contador}")
    print(f"CSV LOCAL: {caminho_csv}")
    print(f"OUTPUT DIR: {OUTPUT_DIR}")
    print(f"OUTPUT S3 PREFIX: {output_s3_prefix}")
    print(f"NOME BUCKET: {NOME_BUCKET}")
    print(Fore.GREEN + "==========================================")


while True:
    iniciar_captura()