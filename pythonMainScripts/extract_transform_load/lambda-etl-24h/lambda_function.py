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

TEMPO_COLETA   = 5    
TOLERANCIA     = 30   
CUSTO_SEGUNDO  = 31.25






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
            dashboardIncidentes(bucket="systrain-bucket-csv", prefix_empresa=prefix_empresa)
            
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

def limpar_chaves_json(val):
    """Converte recursivamente chaves não-nativas (como int64) para tipos aceitos pelo JSON."""
    tipos_aceitos = (str, int, float, bool, type(None))
    
    if isinstance(val, dict):
        
        return {
            (int(k) if hasattr(k, "dtype") and "int" in str(k.dtype) else str(k)) 
            if not isinstance(k, tipos_aceitos) else k: limpar_chaves_json(v) 
            for k, v in val.items()
        }
    elif isinstance(val, list):
        return [limpar_chaves_json(item) for item in val]
    return val

def salvar_json_client(payload: dict, bucket: str, nome_empresa: str, tipo: str) -> bool:
    """
    Serializa `payload` como JSON e faz upload para
    client/{nome_empresa}/dashboard_{tipo}.json.
    """
    
    caminho = caminho_client(nome_empresa=nome_empresa, tipo=tipo)
    print(f"[JSON] Tratando dados e preparando upload: s3://{bucket}/{caminho}")

    
    payload_limpo = limpar_chaves_json(payload)

    
    nome_local = os.path.join("/tmp", caminho.replace("/", "_"))

    try:
        
        with open(nome_local, "w", encoding="utf-8") as f:
            json.dump(payload_limpo, f, indent=2, ensure_ascii=False, default=str)

        s3 = boto3.client("s3", **cfg_s3())

        
        s3.upload_file(
            Filename=nome_local,
            Bucket=bucket,
            Key=caminho,
            ExtraArgs={"ContentType": "application/json"},
        )
        print(f"[JSON] Upload concluído: s3://{bucket}/{caminho}")
        
        
        if os.path.exists(nome_local):
            os.remove(nome_local)
            
        return True
    except Exception as e:
        print(f"[JSON] Erro no upload: {e}")
        
        if os.path.exists(nome_local):
            os.remove(nome_local)
        return False




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

    
    for (id_empresa, nome_empresa), df_emp in df_tratado.groupby(["id_empresa", "nome_empresa"]):

        resultado[id_empresa] = _estrutura_resumo_empresa(nome_empresa)
        resultado[id_empresa]["resumo"]["custo_opex_desperdicado_semana"] = float(
            df_emp["custo_desperdicado"].sum()
        )
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

        
        for dia, df_dia in df_emp.groupby(df_emp["data_hora_envio"].dt.date):
            data       = str(dia)
            dia_semana = pd.Timestamp(dia).day_name()
            resultado[id_empresa]["dias"].setdefault(data, _estrutura_dia(dia_semana))
            resultado[id_empresa]["dias"][data]["custo_opex_desperdicado"] = float(
                df_dia["custo_desperdicado"].sum()
            )

        
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

    
    for id_empresa, dados_empresa in resultado.items():
        nome_empresa = dados_empresa.get("nome", str(id_empresa))
        salvar_json_client(
            payload=dados_empresa,
            bucket=bucket,
            nome_empresa=nome_empresa,
            tipo="operacao",
        )

    print("[dashboardOperacao] Finalizado.")

def dashboardIncidentes(bucket: str, prefix_empresa: str):
    """
    Lê o CSV da ETL 1 e gera o dashboard_incidentes.json estruturado
    """
    print(f"\n[dashboardIncidentes] Iniciando processamento para: {prefix_empresa}")
   
    s3 = boto3.client("s3", **cfg_s3())
   
    hoje = pd.Timestamp.now()
    ano = hoje.year
    mes = hoje.month
    dia = hoje.day

    caminho_incidentes = f"{prefix_empresa}{ano}/{mes}/{dia}/incidentes/"
   
    try:
        lista_arquivos = s3.list_objects_v2(Bucket=bucket, Prefix=caminho_incidentes)
        if "Contents" not in lista_arquivos:
            print(f"[dashboardIncidentes] AVISO: Nenhum arquivo encontrado em {caminho_incidentes}")
            return
       
        caminho_csv_incidentes = lista_arquivos["Contents"][0]["Key"]
        resposta = s3.get_object(Bucket=bucket, Key=caminho_csv_incidentes)
        df_incidentes = pd.read_csv(BytesIO(resposta["Body"].read()))
       
    except Exception as e:
        print(f"[dashboardIncidentes] Erro ao ler seu CSV do S3: {e}")
        return

    if df_incidentes.empty:
        return

    incidentes_lista = []
    total_alto, total_medio, total_baixo = 0, 0, 0
   
    for row in df_incidentes.itertuples():
       
        #vai definir o badge de prioridade
        score_atual = float(getattr(row, "score_saude_momento", 0))
        if score_atual >= 80.0:
            nivel_formatado = "Alto"
            total_alto += 1
        elif score_atual >= 50.0:
            nivel_formatado = "Médio"
            total_medio += 1
        else:
            nivel_formatado = "Baixo"
            total_baixo += 1
           
        data_hora_bruta = str(getattr(row, "data_hora_evento", ""))
        horario_formatado = data_hora_bruta.split(" ")[1].split(".")[0] if " " in data_hora_bruta else data_hora_bruta

        vento_ms = float(row.clima_vento) if hasattr(row, "clima_vento") and pd.notna(row.clima_vento) else 0.0
        vento_kmh = vento_ms * 3.6
       
        componente_gatilho = str(getattr(row, "componente_afetado", "GERAL")).upper()
       
        id_empresa_atual = int(getattr(row, "id_empresa", 0))
        nome_empresa_atual = str(getattr(row, "nome_empresa", "empresa desconhecida"))

        incidentes_lista.append({
            #parte q alimenta o front
            "detalhes_tela": {
                "statusSLA": "risco" if nivel_formatado == "Alto" else "atencao",
                "titulo": str(getattr(row, "descricao", "Alerta operacional")),
                "linha": str(getattr(row, "nome_linha", "Linha Desconhecida")),
                "nivel": nivel_formatado,
                "horario": horario_formatado,
                "descricao": str(getattr(row, "resumo_excesso_metrica", "Métrica fora dos limites")),
                "responsavel": "NAO ATRIBUIDO",
                "status": "ABERTO",
                "componente": componente_gatilho,
                "tipo": str(getattr(row, "tipo_incidente", "HARDWARE")),
                "clima": {
                    "temperatura": float(row.clima_temperatura) if hasattr(row, "clima_temperatura") and pd.notna(row.clima_temperatura) else None,
                    "condicao": str(getattr(row, "clima_condicao", "Sem Registro")),
                    "vento_kmh": f"{vento_kmh:.1f}km/h",
                    "icone": str(getattr(row, "clima_icone", ""))
                }
            },
           
            "metricas_formatadas": {
                    "cpu": f"{float(getattr(row, 'metrica_cpu_momento', 0)):.1f}%",
                    "ram": f"{float(getattr(row, 'metrica_ram_momento', 0)):.1f}%",
                    "disco": f"{float(getattr(row, 'metrica_disco_momento', 0)):.1f}%",
                    "latencia": f"{int(getattr(row, 'metrica_ping_momento', 0))} ms",
                    "disparo": str(getattr(row, "resumo_excesso_metrica", "Métrica fora dos limites"))
                },  
            #dados cru do incidente
            "dados_brutos": {
                "id_rbc": int(getattr(row, "id_rbc", 0)),
                "nome_rbc": str(getattr(row, "nome_rbc", "Desconhecido")),
                "score_saude_original": score_atual,
                "data_hora_completa": data_hora_bruta,
                "id_empresa": id_empresa_atual,
                "nome_empresa": nome_empresa_atual,
            }
        })

    resultado_json = {
        "atualizado_em": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "resumo_cards": {
            "total_incidentes_dia": len(incidentes_lista),
            "incidentes_abertos": len(incidentes_lista),        
            "incidentes_sem_responsavel": len(incidentes_lista),  
            "sla_em_risco": len([i for i in incidentes_lista if i["detalhes_tela"]["statusSLA"] == "risco"]),                                    
            "impacto_alto": total_alto,
            "impacto_medio": total_medio,
            "impacto_baixo": total_baixo
        },
        "lista_incidentes": incidentes_lista
    }
    nome_empresa = prefix_empresa.split("/")[1]
    salvar_json_client(payload=resultado_json, nome_empresa= nome_empresa, bucket=bucket, tipo=f"incidentes")  


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
        return {                          
            "statusCode": 500,
            "body": json.dumps({"ok": False, "erro": str(e)}, ensure_ascii=False),
        }