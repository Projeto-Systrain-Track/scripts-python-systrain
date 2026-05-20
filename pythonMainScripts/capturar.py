from botocore.exceptions import ClientError
from colorama import Fore, init
from typing import Dict
from dotenv import load_dotenv
from datetime import datetime
from pathlib import Path
import pandas as pd
import subprocess
import psutil
from io import StringIO

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
    's3', 
    region_name=os.getenv("AWS_REGION"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    aws_session_token=os.getenv("AWS_SESSION_TOKEN")
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
    
    percentual_uso_ram = psutil.virtual_memory().percent
    percentual_uso_disco = psutil.disk_usage('/').percent

    latencia_ping_ms = medir_ping()

    
    lista_processos = get_all_processes()
    data_hora_iso = datetime.now().isoformat()

    df_metricas = pd.DataFrame([{
        "endereco_mac": endereco_mac,
        "nome_usuario": nome_usuario,

        "percentual_uso_cpu": percentual_uso_cpu,
        "percentual_uso_ram": percentual_uso_ram,
        "percentual_uso_disco": percentual_uso_disco,
        "latencia_ping_ms": latencia_ping_ms,
        "processos": str(lista_processos),
        "data_hora_iso": data_hora_iso
    }])
    df_metricas["data_hora_iso"] = pd.to_datetime(df_metricas["data_hora_iso"], errors="coerce")    
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
                Bucket="systrain-bucket-csv",
                Key="raw/df.csv"
            )

            print(f"Uploaded: s3://{bucket}/{s3_key}")


print(Fore.GREEN + "==========================================")
print(Fore.GREEN + "🚀 SYS TRAIN TRACK - MONITORAMENTO")
print(Fore.GREEN + "==========================================\n")

contador = 0
buffer_dados = []
def iniciar_captura():
    global contador
    global buffer_dados
    dirs = ensure_output_dirs(OUTPUT_DIR)

    nome_arquivo_csv = os.getenv("S3_INPUT_KEY", "df.csv")
    output_s3_prefix = os.getenv("S3_OUTPUT_PREFIX", "raw")

    # Prevent raw/raw/df.csv
    nome_arquivo_csv = Path(nome_arquivo_csv).name

    caminho_csv = dirs["base"] / nome_arquivo_csv

    df_atual = coletar_metricas_sistema()
    buffer_dados.append(df_atual)

    contador += 1

    if contador >= 5:
        contador = 0
        df_lote = pd.concat(buffer_dados, ignore_index=True)
        df_lote["data_hora_envio"] = datetime.now().isoformat()
        try:
            # Tenta buscar o arquivo no S3
            response = s3.get_object(
                Bucket=NOME_BUCKET,
                Key="raw/df.csv"
            )
            conteudo = response['Body'].read().decode('utf-8')
            df_existente = pd.read_csv(StringIO(conteudo))
            df_existente.columns = df_existente.columns.str.strip()
            
        except ClientError as e:
            # Se o erro for "Chave não encontrada" (arquivo não existe), cria um DataFrame vazio
            if e.response['Error']['Code'] == 'NoSuchKey':
                print(Fore.YELLOW + "Arquivo 'raw/df.csv' não encontrado no S3. Criando um df vazio.")
                df_existente = pd.DataFrame()
            else:
                # Se for outro erro de permissão ou rede, repassa o erro
                print("Erro: ", e)
        
        # Se o df_existente estiver vazio, o concat vai apenas usar o df_lote
        df_combinado = pd.concat([df_existente, df_lote], ignore_index=True)
        df_lote["data_hora_envio"] = datetime.now().isoformat()
        # Salva localmente de forma limpa, sobrescrevendo
        df_combinado.to_csv(caminho_csv, index=False, header=True)
        
        # Faz o upload para o S3
        upload_directory_to_s3(
            local_dir=OUTPUT_DIR,
            bucket=NOME_BUCKET,
            s3_prefix=output_s3_prefix
        )
        buffer_dados.clear()
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

    print(Fore.WHITE + "💾 RAM")
    print(Fore.WHITE + f"   Uso: {ram:.1f}%\n")

    print(Fore.WHITE + "🗄 DISCO")
    print(cor_status(disco) + f"   Uso: {disco:.1f}%")

    print(Fore.WHITE + "🌐 REDE")
    print(Fore.CYAN + f"   Ping: {ping} ms")

    print(Fore.WHITE + "⚙ PROCESSOS")
    print(f"CONTADOR: {contador}")
    print(f"CSV LOCAL: {caminho_csv}")
    print(f"OUTPUT DIR: {OUTPUT_DIR}")
    print(f"OUTPUT S3 PREFIX: {output_s3_prefix}")
    print(f"NOME BUCKET: {NOME_BUCKET}")
    print("BUCKET:", os.getenv("S3_BUCKET_NAME"))
    print(Fore.GREEN + "==========================================")


while True:
    iniciar_captura()
    time.sleep(1)