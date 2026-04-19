from datetime import datetime
import pandas as pd
import psutil
import time
import os
import boto3
import logging
from botocore.exceptions import ClientError
import mysql.connector
from mysql.connector import Error

# ================= CONFIG ================= #
INTERVALO = 5
ARQUIVO_TRATADO = "dados_tratados.csv"
BUCKET = "s3-raw-lab-202604061333"
DIRETORIO = "/teste/"

# ================= LOAD (S3) ================= #
def upload_file(file_name, bucket, object_name=None):
    if object_name is None:
        object_name = os.path.basename(file_name)

    s3_client = boto3.client(
        's3',
        aws_access_key_id=,
        aws_secret_access_key=,
        aws_session_token=
    )

    resposta = s3_client.list_objects_v2(bucket = BUCKET, prefix = DIRETORIO)

    try:
        s3_client.upload_file(file_name, bucket, object_name)
        print(f"Upload realizado: {object_name}")
    except ClientError as e:
        logging.error(e)
        return False
    return True

# ================= EXTRACT ================= #
def extract():
    try:
        conexao = mysql.connector.connect(
        host='localhost',
        database='systraintrack',
        user='root',
        password='@GOSTY0210will0511'
        )
        
        if conexao.is_connected():
            informacoes_bd = conexao.get_server_info()
            print(f"Conecção com o MySQLServer, versão:  {informacoes_bd} realizada com sucesso!")

            cursor = conexao.cursor()

            query = ""

            retorno = cursor.fetchall()
            print(f"Total de linhas retornadas: {cursor.rowcount}")

            for row in retorno:
                print(row)
            
    except Error as e:
        print(f"Erro ao conectar ao MySQL {e}")

    finally:
        if 'conexao' in locals() and conexao.is_connected():
            cursor.close()
            conexao.close()
            print(f"Conxão encerrada")


    if 'contents' in resposta:
        for obj in resposta['Contents']:
            print(obj['key'])
    else:
        print("O diretório está vazio ou não existe.")




# ================= TRANSFORM ================= #

def transform(dados):
    df = pd.DataFrame([dados])

    
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