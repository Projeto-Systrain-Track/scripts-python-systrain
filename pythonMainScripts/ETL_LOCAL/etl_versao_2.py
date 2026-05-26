from __future__ import annotations

import os
from io import BytesIO
from typing import Any, Optional
from datetime import datetime, timedelta
import boto3
from botocore.exceptions import ClientError
import numpy as np
import pandas as pd
from dotenv import load_dotenv
import json

load_dotenv()


def cfg_s3() -> dict:
    """Lê credenciais AWS a partir de variáveis de ambiente."""
    return {
        "region_name":           "us-east-1",
        "aws_access_key_id":     os.getenv("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
        "aws_session_token":     os.getenv("AWS_SESSION_TOKEN"),
    }
    
def limpar_mac(valor: Any) -> Any:
    """Normaliza endereço MAC: lowercase e sem espaços."""
    if pd.isna(valor):
        return valor
    return str(valor).strip().lower().replace(":", "-")


def buscar_e_juntar_arquivos_s3(bucket: str):
    s3 = boto3.client("s3", **cfg_s3())
    empresas = s3.list_objects_v2(Bucket=bucket, Prefix="trusted/", Delimiter="/")
    # print("Empresas: ", empresas["CommonPrefixes"])
    df_principal_tratado = []
    df_principal_alertas = []
    
    for empresa in empresas.get("CommonPrefixes", []):
        caminho_semanal = f"{empresa.get("Prefix")}semanal/"
        arquivos_semanal = s3.list_objects_v2(Bucket=bucket, Prefix=f"{caminho_semanal}", Delimiter="/")
        ano = pd.Timestamp.now().year
        mes = pd.Timestamp.now().month
        dia = pd.Timestamp.now().day
        
        caminho_alertas = f"{empresa.get("Prefix")}{ano}/{mes}/{dia}/alertas/abertos/"
        arquivos_alertas = s3.list_objects_v2(Bucket=bucket, Prefix=f"{caminho_alertas}", Delimiter="/")
        # print(arquivos_semanal.get("Contents"))
        for arquivo_tratado in arquivos_semanal.get("Contents", []):
            caminho_semanal = arquivo_tratado.get("Key")
            df_tratado = extrair_csv_s3(bucket=bucket, key=caminho_semanal)
            df_principal_tratado.append(df_tratado)
        for arquivo_alerta in arquivos_alertas.get("Contents", []):
            caminho_alerta = arquivo_alerta.get("Key")
            df_alertas = extrair_csv_s3(bucket=bucket, key=caminho_alerta)
            
            df_principal_alertas.append(df_alertas)

    df_principal_tratado = pd.concat(df_principal_tratado, ignore_index=True)
    df_principal_alertas = pd.concat(df_principal_alertas, ignore_index=True)
    # print(df_principal_tratado)
    
    return df_principal_tratado, df_principal_alertas

def arquivo_existe(bucket, key):
    s3 = boto3.client("s3", **cfg_s3())
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        else:
            raise e
        

def extrair_csv_s3(bucket: str, key: str) -> pd.DataFrame:
    s3 = boto3.client("s3", **cfg_s3())
    # print(f"[S3] Baixando s3://{bucket}/{key} ...")
    verificar_existe = arquivo_existe(bucket=bucket, key=key)
    if verificar_existe:
        resposta = s3.get_object(Bucket=bucket, Key=key)
        conteudo = resposta["Body"].read()
        # print(f"[S3] {len(conteudo):,} bytes recebidos.")
        df = pd.read_csv(BytesIO(conteudo))
        obrigatorias = ["endereco_mac", "data_hora_iso"]
        ausentes = [c for c in obrigatorias if c not in df.columns]
        if ausentes:
            raise ValueError(f"Colunas obrigatórias ausentes no CSV: {ausentes}")
        df["endereco_mac"]  = df["endereco_mac"].map(limpar_mac)
        df["data_hora_iso"] = pd.to_datetime(df["data_hora_iso"], errors="coerce")

        # print(f"[S3] {len(df):,} linhas | {df['endereco_mac'].nunique()} MAC(s).")
        return df
    return None


def dashboardOperacao(df_tratado: pd.DataFrame, df_alertas: pd.DataFrame):
    df_tratado["data_hora_envio"] = pd.to_datetime(df_tratado["data_hora_envio"], errors="coerce")
    df_tratado = df_tratado.sort_values(
        ["id_empresa", "id_linha", "id_rbc", "data_hora_envio"]
    )
    df_tratado["diff_envio_segundos"] = (
        df_tratado.groupby(["id_empresa", "id_linha", "id_rbc"])["data_hora_envio"]
        .diff()
    ).dt.total_seconds()

    TEMPO_COLETA = 5
    TOLERANCIA = 30
    CUSTO_SEGUNDO = 31.25

    df_tratado["segundos_excesso"] = (
        df_tratado["diff_envio_segundos"] - TEMPO_COLETA - TOLERANCIA
    ).clip(lower=0)
    
    df_tratado["qtd_servidores"] = df_tratado.groupby(
        ["id_empresa", "id_linha"]
    )["id_rbc"].transform("nunique")
    
    df_tratado["custo_desperdicado"] = df_tratado["segundos_excesso"] * CUSTO_SEGUNDO / df_tratado["qtd_servidores"]
    df_tratado.to_csv("df_tratado.csv", index=False)
    resultado = {}
    
    for (id_empresa, nome_empresa), df_tratado_empresa in df_tratado.groupby(["id_empresa", "nome_empresa"]):
        # TRANSFORMANDO O DF TRATADO
        custo_empresa = df_tratado_empresa["custo_desperdicado"].sum()
        resultado[id_empresa] = {
            "nome": nome_empresa,
            "custo_total_semana": float(custo_empresa),
            "custo_por_dia": {},
            "linhas": {},
            "graficos": {}
        }
        df_tratado_lote_custo = (
            df_tratado_empresa
                .groupby(["data_hora_envio"], as_index=False)
                .agg(
                    custo_desperdicado=("custo_desperdicado", "sum"),
                    objetivoFinanceiro=("objetivoFinanceiro", "mean")
                )
                .sort_values("data_hora_envio")
        )
        resultado[id_empresa]["graficos"]["custo_ao_longo_tempo"] = [
            {
                "data": str(linha["data_hora_envio"]),
                "custo": float(linha["custo_desperdicado"]),
                "objetivoFinanceiro": str(linha["objetivoFinanceiro"])
            }
            for indice, linha in df_tratado_lote_custo.iterrows()
        ]
        for dia, df_diario_empresa in df_tratado_empresa.groupby(df_tratado_empresa["data_hora_envio"].dt.date):
            data = str(dia)
            dia_semana = pd.Timestamp(dia).day_name()
            custo_dia = df_diario_empresa["custo_desperdicado"].sum()

            resultado[id_empresa]["custo_por_dia"][data] = {
                "dia_semana": str(dia_semana), 
                "custo_dia": str(custo_dia)
            }
            
        for (id_linha, nome_linha), df_tratado_linha in df_tratado_empresa.groupby(["id_linha", "nome_linha"]):
            custo_linha = df_tratado_linha["custo_desperdicado"].sum()
            resultado[id_empresa]["linhas"][id_linha] = {
                "nome": nome_linha,
                "custo_total": float(custo_linha),
                "custo_por_dia": {},
                "servidores": {}
            }
            for dia, df_diario_linha in df_tratado_linha.groupby(df_tratado_linha["data_hora_envio"].dt.date):
                data = str(dia)
                dia_semana = pd.Timestamp(dia).day_name()
                custo_dia = df_diario_linha["custo_desperdicado"].sum()
                resultado[id_empresa]["linhas"][id_linha]["custo_por_dia"][data] = {
                    "dia_semana": str(dia_semana), 
                    "custo_dia": str(custo_dia)
                }

            for (id_rbc, nome_rbc), df_tratado_rbc in df_tratado_linha.groupby(["id_rbc", "nome_rbc"]):
                custo_rbc = df_tratado_rbc["custo_desperdicado"].sum()
                resultado[id_empresa]["linhas"][id_linha]["servidores"][id_rbc] = {
                    "nome": nome_rbc,
                    "custo_total": float(custo_rbc)
                }
    
    # TRANSFORMANDO O DF DE ALERTAS
    for (id_empresa, nome_empresa), df_alertas_empresa in df_alertas.groupby(["id_empresa", "nome_empresa"]):
        print(df_alertas_empresa)
        
    
    with open("saida.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, indent=2, ensure_ascii=False)
        


def main():
    bucket = os.getenv("S3_BUCKET")
    df_principal_tratado, df_principal_alertas = buscar_e_juntar_arquivos_s3(bucket=bucket)
    dashboardOperacao(df_tratado=df_principal_tratado, df_alertas=df_principal_alertas)
    



main()


