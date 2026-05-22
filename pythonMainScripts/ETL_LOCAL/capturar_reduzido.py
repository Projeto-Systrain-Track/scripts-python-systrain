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

TESTE_LOCAL_MUDA_ISSO = True

INTERVALO_SEGUNDOS = 3
OUTPUT_DIR = "raw"

ATRIBUTOS_PROCESSOS = [
    'pid', 'name', 'create_time',
    'cpu_percent', 'memory_percent',
    'memory_info', 'num_threads',
    'cmdline', 'exe'
]


if not TESTE_LOCAL_MUDA_ISSO:
    load_dotenv(dotenv_path=".env.dev")
    NOME_BUCKET = os.getenv("S3_BUCKET_NAME")
    s3 = boto3.client("s3")


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


def limpar_cmdline(cmdline):
    if not cmdline:
        return None

    if isinstance(cmdline, (list, tuple)):
        cmdline_limpo = [str(item).strip() for item in cmdline if item and str(item).strip()]
        return cmdline_limpo or None

    if isinstance(cmdline, str):
        cmdline = cmdline.strip()
        return cmdline or None

    return None

PREFIXO_PROCESSO = "RBC_"


def compactar_processo(info):
    memoria_info = info.get("memory_info")

    rss = int(getattr(memoria_info, "rss", 0) or 0)
    vms = int(getattr(memoria_info, "vms", 0) or 0)

    processo = {
        "pid": info.get("pid"),
        "name": info.get("name"),
        "create_time": info.get("create_time"),
        "cpu_percent": float(info.get("cpu_percent") or 0),
        "memory_percent": float(info.get("memory_percent") or 0),
        "memory_info": {
            "rss": rss,
            "vms": vms
        },
        "num_threads": int(info.get("num_threads") or 0)
    }

    cmdline = limpar_cmdline(info.get("cmdline"))
    if cmdline:
        processo["cmdline"] = cmdline

    exe = info.get("exe")
    if exe:
        processo["exe"] = str(exe)

    return processo



def processo_tem_prefixo(info):
    prefixo = PREFIXO_PROCESSO.lower()

    nome = str(info.get("name") or "").lower()
    exe = str(info.get("exe") or "").lower()

    cmdline = info.get("cmdline") or []
    if not isinstance(cmdline, list):
        cmdline = []

    cmdline_texto = " ".join(str(x) for x in cmdline).lower()

    return (
        nome.startswith(prefixo)
        or prefixo in exe
        or cmdline_texto.startswith(prefixo)
        or f" {prefixo}" in cmdline_texto
    )


def get_all_processes():
    process_list = []

    for proc in psutil.process_iter(ATRIBUTOS_PROCESSOS):
        try:
            info = proc.info

            if not processo_tem_prefixo(info):
                continue

            mem = info.get("memory_info")

            info["memory_info"] = {
                "rss": int(getattr(mem, "rss", 0) or 0),
                "vms": int(getattr(mem, "vms", 0) or 0),
            }

            process_list.append(info)

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

    memoria_virtual = psutil.virtual_memory()
    percentual_uso_ram = memoria_virtual.percent

    uso_disco = psutil.disk_usage('/')

    time.sleep(INTERVALO_SEGUNDOS)

    latencia_ping_ms = medir_ping()

    lista_processos = get_all_processes()
    data_hora_iso = datetime.now().isoformat()

    df_metricas = pd.DataFrame([{
        "endereco_mac": endereco_mac,

        "nome_usuario": nome_usuario,

        "percentual_uso_cpu": percentual_uso_cpu,

        "percentual_uso_ram": percentual_uso_ram,

        "percentual_uso_disco": uso_disco.percent,

        "latencia_ping_ms": latencia_ping_ms,

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

            if not TESTE_LOCAL_MUDA_ISSO:
                s3_key = f"{s3_prefix}/{relative_path}".replace("\\", "/")

                s3.upload_file(
                    Filename=str(file_path),
                    Bucket=bucket,
                    Key=s3_key
                )

                print(f"Uploaded: s3://{bucket}/{s3_key}")

contador = 0

def iniciar_captura():
    global contador

    dirs = ensure_output_dirs(OUTPUT_DIR)

    if not TESTE_LOCAL_MUDA_ISSO:
        nome_arquivo_csv = os.getenv("S3_INPUT_KEY", "df.csv")
        output_s3_prefix = os.getenv("S3_OUTPUT_PREFIX", "raw")
    else:
        nome_arquivo_csv = "df.csv"
        output_s3_prefix = "raw/"    
        NOME_BUCKET = "lmao"
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

while True:
    iniciar_captura()