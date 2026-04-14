from datetime import datetime
import pandas as pd
import psutil
import time
import os
import boto3
import logging
from botocore.exceptions import ClientError

# ================= CONFIG ================= #
INTERVALO = 5
ARQUIVO_TRATADO = "dados_tratados.csv"
BUCKET = "s3-raw-lab-202604061333"

# ================= LOAD (S3) ================= #
def upload_file(file_name, bucket, object_name=None):
    if object_name is None:
        object_name = os.path.basename(file_name)

    s3_client = boto3.client(
        's3',
        aws_access_key_id='x',
        aws_secret_access_key='y',
        aws_session_token='z'
    )

    try:
        s3_client.upload_file(file_name, bucket, object_name)
        print(f"Upload realizado: {object_name}")
    except ClientError as e:
        logging.error(e)
        return False
    return True

# ================= EXTRACT ================= #
def extract():
    cpu = psutil.cpu_percent()
    memoria = psutil.virtual_memory()
    disco = psutil.disk_usage("/").percent

    datahora = datetime.now()

    dados = {
        "cpu": cpu,
        "ram_usada": memoria.used,
        "ram_total": memoria.total,
        "disco": disco,
        "datahora": datahora
    }

    return dados

# ================= TRANSFORM ================= #

def transform(dados):
    df = pd.DataFrame([dados])

    df["ram_percentual"] = round((df["ram_usada"] / df["ram_total"]) * 100, 2)

    def classificar_ram(ram_percentual):
        if ram_percentual < 40:
            return "BAIXO"
        elif ram_percentual < 70:
            return "MODERADO"
        else:
            return "ALTO"
        
    df["status_ram"] = df["ram_percentual"].apply(classificar_ram)
        
    def classificar_cpu(cpu):
        if cpu < 50:
            return "BAIXO"
        elif cpu < 80:
            return "MODERADO"
        else:
            return "ALTO"

    df["status_cpu"] = df["cpu"].apply(classificar_cpu)

    def classificar_disco(disco):
        if disco < 40:
            return "OK"
        elif disco < 70:
            return "ATENCAO"
        else:
            return "CRITICO"

    df["status_disco"] = df["disco"].apply(classificar_disco)

    df["hora"] = df["datahora"].dt.hour

    def periodo(hora):
        if hora < 12:
            return "MANHA"
        elif hora < 18:
            return "TARDE"
        else:
            return "NOITE"

    df["periodo"] = df["hora"].apply(periodo)

    df = df.drop(columns=["ram_usada", "ram_total", "hora"])

    return df

# ================= LOAD ================= #
def load(df):
    if not os.path.exists(ARQUIVO_TRATADO):
        df.to_csv(ARQUIVO_TRATADO, index=False)
    else:
        df.to_csv(ARQUIVO_TRATADO, mode='a', header=False, index=False)

    print(df)

# =================EXECUÇÃO ================= #

def executar_etl():
    contador = 0

    while True:
        dados = extract()

        dados_tratados = transform(dados)

        load(dados_tratados)

        contador += 1

        if contador == 3:
            upload_file(ARQUIVO_TRATADO, BUCKET)
            contador = 0

        time.sleep(INTERVALO)

executar_etl()