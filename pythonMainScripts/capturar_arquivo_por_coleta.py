from botocore.exceptions import ClientError
from colorama import Fore, init
from typing import Dict
from dotenv import load_dotenv
from datetime import datetime
from pathlib import Path
from io import StringIO
import pandas as pd
import subprocess
import psutil
import boto3
import time
import uuid
import os

load_dotenv(dotenv_path=".env.dev")

INTERVALO_SEGUNDOS  = 10         
COLETAS_POR_LOTE    = 6         
OUTPUT_DIR          = "raw"
NOME_BUCKET         = os.getenv("S3_BUCKET_NAME")

ATRIBUTOS_PROCESSOS = [
    "pid", "name", "username", "status", "create_time",
    "cpu_percent", "memory_info", "num_threads",
    "cmdline", "exe", "cpu_times", "memory_percent",
]

def _gerar_mac() -> str:
    n = uuid.getnode()
    return ":".join([f"{(n >> i) & 0xff:02x}" for i in range(0, 48, 8)][::-1]).replace(":", "-")

ENDERECO_MAC = _gerar_mac().split("-")
ENDERECO_MAC = "30" + "-" + ENDERECO_MAC[1] + "-" + ENDERECO_MAC[2] + "-" + ENDERECO_MAC[3] + "-" + ENDERECO_MAC[4] + "-" + ENDERECO_MAC[5] 

s3 = boto3.client(
    "s3",
    region_name=os.getenv("AWS_REGION"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
)

init(autoreset=True)


def cor_status(valor, limite1=60, limite2=80):
    if valor >= limite2:
        return Fore.RED
    if valor >= limite1:
        return Fore.YELLOW
    return Fore.GREEN


def limpar_terminal():
    os.system("cls" if os.name == "nt" else "clear")


def s3_key_lote(mac: str, dt: datetime) -> str:
    """
    raw/aa-bb-cc-dd-ee-ff/2026/05/21/14h00.csv
    Cada RBC escreve só na própria pasta → zero race condition.
    """
    return (
        f"raw/{mac}/{dt.year}/{dt.month:02d}/{dt.day:02d}/{dt.hour:02d}h{dt.minute:02d}.csv"
    )

def caminho_local_lote(mac: str, dt: datetime) -> Path:
    p = (
        Path(OUTPUT_DIR)
        / mac
        / str(dt.year)
        / f"{dt.month:02d}"
        / f"{dt.day:02d}"
        / f"{dt.hour:02d}h.csv"
    )
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ── coleta ────────────────────────────────────────────────────
def medir_ping(host="8.8.8.8", timeout=4) -> int:
    try:
        cmd = ["ping", "-n", "1", host] if os.name == "nt" else ["ping", "-c", "1", host]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
        for linha in out.splitlines():
            ll = linha.lower()
            for marcador in ("tempo=", "time="):
                if marcador in ll:
                    return int(float(ll.split(marcador)[1].split("ms")[0].strip().replace(",", ".")))
    except Exception:
        pass
    return 0

PREFIXO_PROCESSO = "RBC_"
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



def coletar_metricas() -> pd.DataFrame:
    try:
        nome_usuario = os.getlogin()
    except Exception:
        nome_usuario = os.environ.get("USERNAME") or os.environ.get("USER") or "desconhecido"

    return pd.DataFrame([{
        "endereco_mac":         ENDERECO_MAC,
        "nome_usuario":         nome_usuario,
        "percentual_uso_cpu":   psutil.cpu_percent(interval=None),
        "percentual_uso_ram":   psutil.virtual_memory().percent,
        "percentual_uso_disco": psutil.disk_usage("/").percent,
        "latencia_ping_ms":     medir_ping(),
        "processos":            str(get_all_processes()),
        "data_hora_iso":        datetime.now().isoformat(),
    }])


def enviar_lote_s3(df_lote: pd.DataFrame, dt_envio: datetime):
    key   = s3_key_lote(ENDERECO_MAC, dt_envio)
    local = caminho_local_lote(ENDERECO_MAC, dt_envio)
    df_lote.to_csv(local, index=False)
    s3.upload_file(Filename=str(local), Bucket=NOME_BUCKET, Key=key)
    print(Fore.GREEN + f"[S3] Upload: s3://{NOME_BUCKET}/{key}")

print(Fore.LIGHTRED_EX + "==========================================")
print(Fore.LIGHTRED_EX + "  SYS TRAIN TRACK — MONITORAMENTO")
print(Fore.LIGHTRED_EX + f"  MAC: {ENDERECO_MAC}")
print(Fore.LIGHTRED_EX + "==========================================\n")

contador    = 0
buffer      = []

while True:
    df = coletar_metricas()
    buffer.append(df)
    contador += 1

    dados = df.iloc[0]
    cpu   = dados["percentual_uso_cpu"]
    ram   = dados["percentual_uso_ram"]
    disco = dados["percentual_uso_disco"]
    ping  = dados["latencia_ping_ms"]

    limpar_terminal()
    print(Fore.GREEN + "==========================================")
    print(Fore.GREEN + "  SYS TRAIN TRACK — MONITORAMENTO")
    print(Fore.GREEN + f"  MAC : {ENDERECO_MAC}")
    print(Fore.CYAN  + f"  User: {dados['nome_usuario']}  |  {datetime.now().strftime('%H:%M:%S')}")
    print(Fore.GREEN + "==========================================\n")
    print(Fore.WHITE + "CPU  ", cor_status(cpu)   + f"{cpu:.1f}%")
    print(Fore.WHITE + "RAM  ", Fore.WHITE         + f"{ram:.1f}%")
    print(Fore.WHITE + "DISCO", cor_status(disco)  + f"{disco:.1f}%")
    print(Fore.WHITE + "PING ", Fore.CYAN          + f"{ping} ms")
    print(Fore.WHITE + f"\nColeta {contador}/{COLETAS_POR_LOTE}")

    if contador >= COLETAS_POR_LOTE:
        dt_envio = datetime.now()
        df_lote  = pd.concat(buffer, ignore_index=True)
        df_lote["data_hora_envio"] = dt_envio.isoformat()

        try:
            enviar_lote_s3(df_lote, dt_envio)
        except Exception as e:
            print(Fore.RED + f"[S3] Erro no upload: {e}")

        contador = 0
        buffer   = []

    time.sleep(INTERVALO_SEGUNDOS)