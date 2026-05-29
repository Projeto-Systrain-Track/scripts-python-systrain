from __future__ import annotations

import os
from io import BytesIO
from typing import Any
import boto3
from botocore.exceptions import ClientError
import pandas as pd
from dotenv import load_dotenv
import json

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEMPO_COLETA   = 5    # segundos entre coletas esperadas
TOLERANCIA     = 30   # segundos de tolerância antes de considerar gap
CUSTO_SEGUNDO  = 31.25


# ---------------------------------------------------------------------------
# AWS / S3 helpers
# ---------------------------------------------------------------------------

def cfg_s3() -> dict:
    """Monta o dicionário de configuração usado pelo boto3 para acessar o S3."""
    return {
        "region_name":           "us-east-1",
        "aws_access_key_id":     os.getenv("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
        "aws_session_token":     os.getenv("AWS_SESSION_TOKEN"),
    }


def arquivo_existe(bucket: str, key: str) -> bool:
    """Retorna True se o objeto existir no S3, False se não (404)."""
    s3 = boto3.client("s3", **cfg_s3())
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        raise


def limpar_mac(valor: Any) -> Any:
    """Padroniza o endereço MAC: minúsculo, hífens, sem espaços."""
    if pd.isna(valor):
        return valor
    return str(valor).strip().lower().replace(":", "-")


def extrair_csv_s3(bucket: str, key: str) -> pd.DataFrame | None:
    """
    Baixa um CSV do S3 e devolve um DataFrame com tratamentos básicos.
    Retorna None se o arquivo não existir.
    """
    if not arquivo_existe(bucket=bucket, key=key):
        print(f"[extrair_csv_s3] Não encontrado: s3://{bucket}/{key}")
        return None

    s3 = boto3.client("s3", **cfg_s3())
    resposta = s3.get_object(Bucket=bucket, Key=key)
    conteudo = resposta["Body"].read()
    print(f"[extrair_csv_s3] {len(conteudo):,} bytes — s3://{bucket}/{key}")

    df = pd.read_csv(BytesIO(conteudo))

    ausentes = [c for c in ["endereco_mac", "data_hora_iso"] if c not in df.columns]
    if ausentes:
        raise ValueError(f"Colunas obrigatórias ausentes no CSV: {ausentes}")

    df["endereco_mac"]  = df["endereco_mac"].map(limpar_mac)
    df["data_hora_iso"] = pd.to_datetime(df["data_hora_iso"], errors="coerce")

    print(f"[extrair_csv_s3] {len(df):,} linhas | {df['endereco_mac'].nunique()} MAC(s).")
    return df


# ---------------------------------------------------------------------------
# S3 reader — trusted/
# ---------------------------------------------------------------------------

def buscar_e_juntar_arquivos_s3(bucket: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Varre trusted/<empresa>/semanal/ e devolve dois DataFrames:

    df_tratado  → trusted/<empresa>/semanal/tratados/*.csv
    df_alertas  → trusted/<empresa>/semanal/alertas/*.csv
    """
    print("\n[buscar] Iniciando busca em trusted/ ...")
    s3 = boto3.client("s3", **cfg_s3())

    empresas_resp = s3.list_objects_v2(
        Bucket=bucket, Prefix="trusted/", Delimiter="/"
    )
    prefixos = [p["Prefix"] for p in empresas_resp.get("CommonPrefixes", [])]
    print(f"[buscar] {len(prefixos)} empresa(s) encontrada(s).")

    listas_tratados: list[pd.DataFrame] = []
    listas_alertas:  list[pd.DataFrame] = []

    for prefix_empresa in prefixos:
        for subtipo, lista_destino in [
            ("tratados", listas_tratados),
            ("alertas",  listas_alertas),
        ]:
            prefixo = f"{prefix_empresa}semanal/{subtipo}/"
            resp = s3.list_objects_v2(Bucket=bucket, Prefix=prefixo)
            arquivos = resp.get("Contents", [])
            print(f"[buscar] {prefixo} → {len(arquivos)} arquivo(s).")

            for obj in arquivos:
                df = extrair_csv_s3(bucket=bucket, key=obj["Key"])
                if df is not None:
                    lista_destino.append(df)

    df_tratado = (
        pd.concat(listas_tratados, ignore_index=True)
        if listas_tratados else pd.DataFrame()
    )
    df_alertas = (
        pd.concat(listas_alertas, ignore_index=True)
        if listas_alertas else pd.DataFrame()
    )

    print(f"[buscar] df_tratado: {df_tratado.shape} | df_alertas: {df_alertas.shape}")
    return df_tratado, df_alertas


# ---------------------------------------------------------------------------
# S3 writer — client/
# ---------------------------------------------------------------------------

def _slug_empresa(nome: str) -> str:
    return str(nome).strip().replace(" ", "_").lower()


def caminho_client(nome_empresa: str, tipo: str) -> str:
    """
    Gera o caminho S3 dentro de client/.

    Paths produzidos:
      client/{empresa}/dashboard_operacao.json
      client/{empresa}/dashboard_incidentes.json
      client/{empresa}/dashboard_visao_geral.json
      client/{empresa}/dashboard_detalhe_linha.json
    """
    slug = _slug_empresa(nome_empresa)
    nomes = {
        "operacao":     "dashboard_operacao.json",
        "incidentes":   "dashboard_incidentes.json",
        "visao_geral":  "dashboard_visao_geral.json",
        "detalhe_linha":"dashboard_detalhe_linha.json",
    }
    if tipo not in nomes:
        raise ValueError(f"Tipo de dashboard desconhecido: {tipo!r}")
    return f"client/{slug}/{nomes[tipo]}"


def salvar_json_client(payload: dict, bucket: str, nome_empresa: str, tipo: str) -> bool:
    """
    Serializa `payload` como JSON e faz upload para
    client/{nome_empresa}/dashboard_{tipo}.json.

    Parâmetros
    ----------
    payload       : dicionário já montado pelo builder
    bucket        : nome do bucket S3
    nome_empresa  : usado para derivar o sub-prefixo dentro de client/
    tipo          : chave de dashboard ('operacao', 'incidentes', etc.)
    """
    caminho = caminho_client(nome_empresa=nome_empresa, tipo=tipo)
    print(f"[JSON] Salvando: s3://{bucket}/{caminho}")

    nome_local = caminho.replace("/", "_")
    with open(nome_local, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)

    s3 = boto3.client("s3", **cfg_s3())
    try:
        s3.upload_file(
            Filename=nome_local,
            Bucket=bucket,
            Key=caminho,
            ExtraArgs={"ContentType": "application/json"},
        )
        print(f"[JSON] Upload concluído: s3://{bucket}/{caminho}")
        return True
    except Exception as e:
        print(f"[JSON] Erro no upload: {e}")
        return False


# ---------------------------------------------------------------------------
# Dashboard builder
# ---------------------------------------------------------------------------

def _estrutura_resumo_empresa(nome_empresa: str) -> dict:
    return {
        "nome": nome_empresa,
        "data_hora": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "resumo": {
            "custo_opex_desperdicado_semana": 0.0,
            "qte_alertas_semana":             0,
            "alertas_por_motivo":             {},
            "tipo_alertas":                   {},
        },
        "dias":               {},
        "linhas":             {},
        "custo_ao_longo_tempo": [],
    }


def _estrutura_resumo_linha(nome_linha: str) -> dict:
    return {
        "nome": nome_linha,
        "resumo": {
            "custo_opex_desperdicado": 0.0,
            "qte_alertas":             0,
            "alertas_por_motivo":      {},
            "tipo_alertas":            {},
        },
        "dias":       {},
        "servidores": {},
    }


def _estrutura_resumo_rbc(nome_rbc: str) -> dict:
    return {
        "nome": nome_rbc,
        "resumo": {
            "custo_opex_desperdicado": 0.0,
            "qte_alertas":             0,
            "alertas_por_motivo":      {},
            "tipo_alertas":            {},
        },
        "dias": {},
    }


def _estrutura_dia(dia_semana: str) -> dict:
    return {
        "dia_semana":             str(dia_semana),
        "custo_opex_desperdicado": 0.0,
        "qte_alertas":             0,
        "alertas_por_motivo":      {},
        "tipo_alertas":            {},
    }


def _calcular_custo(df: pd.DataFrame) -> pd.DataFrame:
    """
    Acrescenta a coluna `custo_desperdicado` ao DataFrame de leituras tratadas.
    Lógica: detecta gaps entre envios consecutivos do mesmo RBC e multiplica
    os segundos excedentes pelo custo por segundo.
    """
    df = df.copy()
    df["data_hora_envio"] = pd.to_datetime(df["data_hora_envio"], errors="coerce")
    df = df.sort_values(["id_empresa", "id_linha", "id_rbc", "data_hora_envio"])

    df["diff_envio_segundos"] = (
        df.groupby(["id_empresa", "id_linha", "id_rbc"])["data_hora_envio"]
        .diff()
        .dt.total_seconds()
    )

    df["segundos_excesso"] = (
        df["diff_envio_segundos"] - TEMPO_COLETA - TOLERANCIA
    ).clip(lower=0)

    df["qtd_servidores"] = df.groupby(["id_empresa", "id_linha"])["id_rbc"].transform("nunique")

    df["custo_desperdicado"] = (
        df["segundos_excesso"] * CUSTO_SEGUNDO / df["qtd_servidores"]
    )

    return df


def dashboardOperacao(df_tratado: pd.DataFrame, df_alertas: pd.DataFrame, bucket: str):
    """
    Constrói o dashboard de operação e salva um JSON por empresa em
    client/{nome_empresa}/dashboard_operacao.json.
    """
    if df_tratado.empty:
        print("[dashboardOperacao] df_tratado vazio — nada a processar.")
        return

    df_tratado = _calcular_custo(df_tratado)
    resultado: dict = {}

    # ── Custo por empresa / linha / rbc / dia ─────────────────────────────
    for (id_empresa, nome_empresa), df_emp in df_tratado.groupby(["id_empresa", "nome_empresa"]):

        resultado[id_empresa] = _estrutura_resumo_empresa(nome_empresa)
        resultado[id_empresa]["resumo"]["custo_opex_desperdicado_semana"] = float(
            df_emp["custo_desperdicado"].sum()
        )

        # Série temporal de custo
        serie = (
            df_emp.groupby("data_hora_envio", as_index=False)
            .agg(
                custo_desperdicado=("custo_desperdicado", "sum"),
                objetivoFinanceiro=("objetivoFinanceiro", "mean"),
            )
            .sort_values("data_hora_envio")
        )
        resultado[id_empresa]["custo_ao_longo_tempo"] = [
            {
                "data":                    str(r["data_hora_envio"]),
                "custo_opex_desperdicado": float(r["custo_desperdicado"]),
                "objetivoFinanceiro":      float(r["objetivoFinanceiro"]),
            }
            for _, r in serie.iterrows()
        ]

        # Por dia (empresa)
        for dia, df_dia in df_emp.groupby(df_emp["data_hora_envio"].dt.date):
            data       = str(dia)
            dia_semana = pd.Timestamp(dia).day_name()
            resultado[id_empresa]["dias"].setdefault(data, _estrutura_dia(dia_semana))
            resultado[id_empresa]["dias"][data]["custo_opex_desperdicado"] = float(
                df_dia["custo_desperdicado"].sum()
            )

        # Por linha
        for (id_linha, nome_linha), df_lin in df_emp.groupby(["id_linha", "nome_linha"]):
            resultado[id_empresa]["linhas"].setdefault(
                id_linha, _estrutura_resumo_linha(nome_linha)
            )
            resultado[id_empresa]["linhas"][id_linha]["resumo"]["custo_opex_desperdicado"] = float(
                df_lin["custo_desperdicado"].sum()
            )

            for dia, df_dia_lin in df_lin.groupby(df_lin["data_hora_envio"].dt.date):
                data       = str(dia)
                dia_semana = pd.Timestamp(dia).day_name()
                resultado[id_empresa]["linhas"][id_linha]["dias"].setdefault(
                    data, _estrutura_dia(dia_semana)
                )
                resultado[id_empresa]["linhas"][id_linha]["dias"][data]["custo_opex_desperdicado"] = float(
                    df_dia_lin["custo_desperdicado"].sum()
                )

            # Por RBC
            for (id_rbc, nome_rbc), df_rbc in df_lin.groupby(["id_rbc", "nome_rbc"]):
                resultado[id_empresa]["linhas"][id_linha]["servidores"].setdefault(
                    id_rbc, _estrutura_resumo_rbc(nome_rbc)
                )
                resultado[id_empresa]["linhas"][id_linha]["servidores"][id_rbc]["resumo"][
                    "custo_opex_desperdicado"
                ] = float(df_rbc["custo_desperdicado"].sum())

                for dia, df_dia_rbc in df_rbc.groupby(df_rbc["data_hora_envio"].dt.date):
                    data       = str(dia)
                    dia_semana = pd.Timestamp(dia).day_name()
                    resultado[id_empresa]["linhas"][id_linha]["servidores"][id_rbc]["dias"].setdefault(
                        data, _estrutura_dia(dia_semana)
                    )
                    resultado[id_empresa]["linhas"][id_linha]["servidores"][id_rbc]["dias"][data][
                        "custo_opex_desperdicado"
                    ] = float(df_dia_rbc["custo_desperdicado"].sum())

    # ── Alertas ───────────────────────────────────────────────────────────
    if not df_alertas.empty:
        df_alertas = df_alertas.copy()
        df_alertas["data_hora_iso"] = pd.to_datetime(df_alertas["data_hora_iso"], errors="coerce")

        for (id_empresa, nome_empresa), df_emp_al in df_alertas.groupby(["id_empresa", "nome_empresa"]):

            if id_empresa not in resultado:
                resultado[id_empresa] = _estrutura_resumo_empresa(nome_empresa)

            res_emp = resultado[id_empresa]
            res_emp["resumo"]["qte_alertas_semana"]    = int(len(df_emp_al))
            res_emp["resumo"]["alertas_por_motivo"]    = df_emp_al["motivo_resumido"].value_counts().to_dict()
            res_emp["resumo"]["tipo_alertas"]          = df_emp_al["tipo_alerta"].value_counts().to_dict()

            for dia, df_dia_al in df_emp_al.groupby(df_emp_al["data_hora_iso"].dt.date):
                data       = str(dia)
                dia_semana = pd.Timestamp(dia).day_name()
                res_emp["dias"].setdefault(data, _estrutura_dia(dia_semana))
                res_emp["dias"][data]["qte_alertas"]         = int(len(df_dia_al))
                res_emp["dias"][data]["alertas_por_motivo"]  = df_dia_al["motivo_resumido"].value_counts().to_dict()
                res_emp["dias"][data]["tipo_alertas"]        = df_dia_al["tipo_alerta"].value_counts().to_dict()

            for (id_linha, nome_linha), df_lin_al in df_emp_al.groupby(["id_linha", "nome_linha"]):
                res_emp["linhas"].setdefault(id_linha, _estrutura_resumo_linha(nome_linha))
                res_lin = res_emp["linhas"][id_linha]

                res_lin["resumo"]["qte_alertas"]        = int(len(df_lin_al))
                res_lin["resumo"]["alertas_por_motivo"] = df_lin_al["motivo_resumido"].value_counts().to_dict()
                res_lin["resumo"]["tipo_alertas"]       = df_lin_al["tipo_alerta"].value_counts().to_dict()

                for dia, df_dia_lin_al in df_lin_al.groupby(df_lin_al["data_hora_iso"].dt.date):
                    data       = str(dia)
                    dia_semana = pd.Timestamp(dia).day_name()
                    res_lin["dias"].setdefault(data, _estrutura_dia(dia_semana))
                    res_lin["dias"][data]["qte_alertas"]         = int(len(df_dia_lin_al))
                    res_lin["dias"][data]["alertas_por_motivo"]  = df_dia_lin_al["motivo_resumido"].value_counts().to_dict()
                    res_lin["dias"][data]["tipo_alertas"]        = df_dia_lin_al["tipo_alerta"].value_counts().to_dict()

                for (id_rbc, nome_rbc), df_rbc_al in df_lin_al.groupby(["id_rbc", "nome_rbc"]):
                    res_lin["servidores"].setdefault(id_rbc, _estrutura_resumo_rbc(nome_rbc))
                    res_rbc = res_lin["servidores"][id_rbc]

                    res_rbc["resumo"]["qte_alertas"]        = int(len(df_rbc_al))
                    res_rbc["resumo"]["alertas_por_motivo"] = df_rbc_al["motivo_resumido"].value_counts().to_dict()
                    res_rbc["resumo"]["tipo_alertas"]       = df_rbc_al["tipo_alerta"].value_counts().to_dict()

                    for dia, df_dia_rbc_al in df_rbc_al.groupby(df_rbc_al["data_hora_iso"].dt.date):
                        data       = str(dia)
                        dia_semana = pd.Timestamp(dia).day_name()
                        res_rbc["dias"].setdefault(data, _estrutura_dia(dia_semana))
                        res_rbc["dias"][data]["qte_alertas"]         = int(len(df_dia_rbc_al))
                        res_rbc["dias"][data]["alertas_por_motivo"]  = df_dia_rbc_al["motivo_resumido"].value_counts().to_dict()
                        res_rbc["dias"][data]["tipo_alertas"]        = df_dia_rbc_al["tipo_alerta"].value_counts().to_dict()

    # ── Um JSON por empresa em client/ ───────────────────────────────────
    for id_empresa, dados_empresa in resultado.items():
        nome_empresa = dados_empresa.get("nome", str(id_empresa))
        salvar_json_client(
            payload=dados_empresa,
            bucket=bucket,
            nome_empresa=nome_empresa,
            tipo="operacao",
        )

    print("[dashboardOperacao] Finalizado.")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def main(event: dict) -> dict:
    bucket = event.get("bucket") or os.getenv("S3_BUCKET")
    if not bucket:
        raise ValueError("Bucket não informado no evento nem em S3_BUCKET.")

    print(f"[main] Bucket: {bucket}")

    df_tratado, df_alertas = buscar_e_juntar_arquivos_s3(bucket=bucket)

    dashboardOperacao(
        df_tratado=df_tratado,
        df_alertas=df_alertas,
        bucket=bucket,
    )

    return {"ok": True, "bucket": bucket}


def lambda_handler(event, context):
    try:
        print("[LAMBDA] Evento recebido:", json.dumps(event, ensure_ascii=False, default=str))
        result = main(event or {})
        return {
            "statusCode": 200,
            "body": json.dumps(result, ensure_ascii=False, default=str),
        }
    except Exception as e:
        print(f"[ERRO] {e}")
        return {                          # ← return and dict on the same line (bug fix)
            "statusCode": 500,
            "body": json.dumps({"ok": False, "erro": str(e)}, ensure_ascii=False),
        }
