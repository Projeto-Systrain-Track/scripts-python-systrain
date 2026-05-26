from __future__ import annotations

from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from io import StringIO, BytesIO
import mysql.connector
import pandas as pd
import numpy as np
import json
import boto3
import os
import datetime
load_dotenv()

import uuid

# 
# Configuração
# 

def cfg_mysql() -> dict:
    return {
        "host":     os.getenv("MYSQL_HOST"),
        "port":     int(os.getenv("MYSQL_PORT", 3306)),
        "user":     os.getenv("MYSQL_USER"),
        "password": os.getenv("MYSQL_PASSWORD"),
        "database": os.getenv("MYSQL_DATABASE"),
    }

def cfg_s3() -> dict:
    return {
        "region_name":"us-east-1",
        "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
        "aws_session_token": os.getenv("AWS_SESSION_TOKEN"),
    }
    
def limpar_mac(valor: Any) -> Any:
    if pd.isna(valor):
        return valor
    return str(valor).strip().lower()


def fix_numpy(valor: Any) -> Any:
    """Converte tipos numpy/pandas para tipos Python nativos (para JSON)."""
    if valor is None:
        return None
    if isinstance(valor, dict):
        return {k: fix_numpy(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [fix_numpy(v) for v in valor]
    if isinstance(valor, np.integer):
        return int(valor)
    if isinstance(valor, np.floating):
        return None if np.isnan(valor) else float(valor)
    if isinstance(valor, np.bool_):
        return bool(valor)
    if isinstance(valor, np.ndarray):
        return valor.tolist()
    if isinstance(valor, pd.Timestamp):
        return None if pd.isna(valor) else valor.isoformat()
    try:
        if pd.isna(valor):
            return None
    except Exception:
        pass
    return valor


def separar_definicao(definicao: Any) -> dict:
    """Parseia 'limite_alerta=80;limite_critico=95' → dict com floats."""
    if not definicao:
        return {}
    definicao = str(definicao).strip()
    if "=" not in definicao:
        return {"valor": definicao}
    resultado: dict = {}
    for parte in definicao.split(";"):
        parte = parte.strip()
        if not parte or "=" not in parte:
            continue
        chave, valor = parte.split("=", 1)
        chave = chave.strip()
        valor = valor.strip()
        try:
            resultado[chave] = float(valor)
        except Exception:
            resultado[chave] = valor
    return resultado


def extrair_csv_s3(
    bucket: Optional[str] = None,
    key: Optional[str] = None,
) -> pd.DataFrame:
    """
    Baixa o CSV do S3 e devolve um DataFrame já com tipos básicos corrigidos.

    Parâmetros
    ----------
    bucket : str, opcional
        Nome do bucket. Se None, lê de S3_BUCKET no .env.
    key : str, opcional
        Caminho do arquivo dentro do bucket. Se None, lê de S3_KEY no .env.
        Quando informado, carrega apenas as últimas N linhas de dados
        (mantém o cabeçalho). Útil para janelas de monitoramento.

    Retorna
    -------
    pd.DataFrame
        DataFrame com colunas tipadas e endereço MAC normalizado.
    """
    cfg = cfg_s3()
    bucket = os.getenv("S3_BUCKET")
    key = os.getenv("S3_KEY")

    if not bucket or not key:
        raise ValueError(
            "Informe bucket/key S3_BUCKET e S3_KEY no .env"
        )

    s3 = boto3.client("s3", **cfg)

    print(f"[S3] Baixando s3://{bucket}/{key} …")
    resp = s3.get_object(Bucket=bucket, Key=key)
    conteudo_bytes: bytes = resp["Body"].read()
    print(f"[S3] Download concluído ({len(conteudo_bytes):,} bytes).")

    df = pd.read_csv(BytesIO(conteudo_bytes), low_memory=False)

    #  validação de colunas obrigatórias 
    obrigatorias = ["endereco_mac", "data_hora_iso"]
    ausentes = [c for c in obrigatorias if c not in df.columns]
    if ausentes:
        raise ValueError(f"Colunas obrigatórias ausentes no CSV: {', '.join(ausentes)}")

    #  normalização básica
    df["endereco_mac"]  = df["endereco_mac"].map(limpar_mac)
    df["data_hora_iso"] = pd.to_datetime(df["data_hora_iso"], errors="coerce")

    colunas_numericas = [
        "percentual_uso_cpu", "memoria_total_bytes", "memoria_disponivel_bytes",
        "percentual_uso_ram", "swap_total_bytes", "swap_usado_bytes", "swap_livre_bytes",
        "swap_entrada_bytes", "swap_saida_bytes", "percentual_uso_swap",
        "disco_total_bytes", "disco_usado_bytes", "disco_livre_bytes", "percentual_uso_disco",
        "frequencia_cpu_atual_mhz", "frequencia_cpu_minima_mhz", "frequencia_cpu_maxima_mhz",
        "taxa_leitura_disco_bytes_por_segundo", "taxa_escrita_disco_bytes_por_segundo",
        "latencia_ping_ms", "taxa_download_rede_bytes_por_segundo",
        "taxa_upload_rede_bytes_por_segundo",
    ]
    for col in colunas_numericas:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce", downcast="float")

    print(f"[S3] {len(df):,} linhas carregadas | {df['endereco_mac'].nunique()} MACs únicos.")
    return df

def conexao_mysql():
    return mysql.connector.connect(**cfg_mysql())


def buscar_mapeamento_rbc(macs: List[str]) -> pd.DataFrame:
    """
    Retorna id_empresa, nome_empresa, id_linha, nome_linha, id_rbc, nome_rbc
    para cada MAC informado.
    """
    if not macs:
        return pd.DataFrame(columns=[
            "endereco_mac", "id_empresa", "nome_empresa",
            "id_linha", "nome_linha", "id_rbc", "nome_rbc",
        ])

    conn = conexao_mysql()
    try:
        cursor = conn.cursor(dictionary=True)
        placeholders = ", ".join(["%s"] * len(macs))
        sql = f"""
            SELECT
                LOWER(TRIM(r.macAdress))  AS endereco_mac,
                e.idEmpresa               AS id_empresa,
                e.razaoSocial             AS nome_empresa,
                l.idLinha                 AS id_linha,
                CONCAT('Linha ', l.idLinha) AS nome_linha,
                r.idRbc                   AS id_rbc,
                r.nomeServidor            AS nome_rbc,
                r.objetivoFinanceiro 
            FROM rbc r
            JOIN linha    l ON r.fkLinha   = l.idLinha
            JOIN empresa  e ON e.idEmpresa = l.fkEmpresa
            WHERE LOWER(TRIM(r.macAdress)) IN ({placeholders})
        """
        cursor.execute(sql, macs)
        rows = cursor.fetchall()
    finally:
        conn.close()

    if not rows:
        return pd.DataFrame(columns=[
            "endereco_mac", "id_empresa", "nome_empresa",
            "id_linha", "nome_linha", "id_rbc", "nome_rbc", "objetivoFinanceiro ",
        ])
    return pd.DataFrame(rows)


def buscar_limites_rbc(ids_rbc: List[int]) -> pd.DataFrame:
    """
    Retorna um DataFrame com id_rbc e limites_componentes (dict aninhado)
    para cada RBC informado.

    Estrutura de limites_componentes:
    {
      "CPU_PER": {"limite_alerta": 80.0, "limite_critico": 95.0, ...},
      "RAM_PER": {...},
      ...
    }
    """
    ids_limpos = sorted({int(i) for i in ids_rbc if i is not None and not (isinstance(i, float) and np.isnan(i))})
    if not ids_limpos:
        return pd.DataFrame(columns=["id_rbc", "limites_componentes"])

    conn = conexao_mysql()
    try:
        cursor = conn.cursor(dictionary=True)
        placeholders = ", ".join(["%s"] * len(ids_limpos))
        sql = f"""
            SELECT
                rc.fkRbc        AS id_rbc,
                c.nome          AS codigo_componente,
                c.tipo          AS tipo_componente,
                c.parametros    AS parametros,
                c.unidade       AS unidade,
                rc.definicao    AS definicao
            FROM rbcComponente rc
            JOIN componente c ON c.idComponente = rc.fkComponente
            WHERE rc.fkRbc IN ({placeholders})
        """
        cursor.execute(sql, ids_limpos)
        rows = cursor.fetchall()
    finally:
        conn.close()

    limites_por_rbc: Dict[int, dict] = {}
    for row in rows:
        id_rbc   = row["id_rbc"]
        codigo   = str(row.get("codigo_componente") or "").strip()
        if not codigo:
            continue
        limites_por_rbc.setdefault(id_rbc, {})
        definicao = separar_definicao(row.get("definicao"))
        limites_por_rbc[id_rbc][codigo] = {
            "tipo_componente": row.get("tipo_componente"),
            "parametros":      row.get("parametros"),
            "unidade":         row.get("unidade"),
            "definicao":       row.get("definicao"),
            "limite_alerta":   definicao.get("limite_alerta"),
            "limite_critico":  definicao.get("limite_critico")
        }

    if not limites_por_rbc:
        return pd.DataFrame(columns=["id_rbc", "limites_componentes"])

    return pd.DataFrame([
        {"id_rbc": id_rbc, "limites_componentes": limites}
        for id_rbc, limites in limites_por_rbc.items()
    ])



def extrair_e_enriquecer(
    bucket: Optional[str] = None,
    key: Optional[str] = None,
    usar_banco: bool = True,
) -> pd.DataFrame:
    """
    Pipeline completo:
      1. Extrai o CSV único do S3.
      2. Enriquece com id_empresa, nome_empresa, id_linha, nome_linha,
         id_rbc, nome_rbc (via JOIN no MySQL).
      3. Adiciona coluna `limites_componentes` (dict) por RBC.

    Parâmetros
    ----------
    bucket : str, opcional
        Nome do bucket S3. Padrão: variável de ambiente S3_BUCKET.
    key : str, opcional
        Chave (caminho) do arquivo no bucket. Padrão: variável S3_KEY.
        Carrega apenas as últimas N linhas do CSV (útil para monitoramento).
        Padrão: carrega tudo (ou LAST_N do .env quando não informado).
    usar_banco : bool
        Se False, pula o enriquecimento do MySQL (modo offline/teste).

    Retorna
    -------
    pd.DataFrame
        DataFrame com todas as colunas originais + colunas do banco.
        Nunca salva nada em disco nem no S3.
    """
    
    #  1. extração S3 
    df = extrair_csv_s3(bucket=bucket, key=key)
    if not usar_banco:
        # modo offline: colunas do banco com valores nulos
        for col in ("id_empresa", "nome_empresa", "id_linha", "nome_linha", "id_rbc", "nome_rbc"):
            df[col] = df.get(col, None)
        df["limites_componentes"] = [{} for _ in range(len(df))]
        print("[banco] Modo offline (usar_banco=False). Colunas do banco preenchidas com nulos.")
        return df

    #  2. mapeamento MAC → RBC/linha/empresa --
    macs_unicos = sorted(df["endereco_mac"].dropna().unique().tolist())
    print(f"[banco] Buscando mapeamento para {len(macs_unicos)} MAC(s) …")
    mapeamento = buscar_mapeamento_rbc(macs_unicos)

    sem_cadastro = set(macs_unicos) - set(mapeamento["endereco_mac"].tolist())
    if sem_cadastro:
        print(f"[banco] {len(sem_cadastro)} MAC(s) sem cadastro no banco: {sem_cadastro}")

    df = df.merge(mapeamento, on="endereco_mac", how="left")    
        
    df["id_empresa"] = df.get("id_empresa", None)
    df["nome_empresa"] = df["nome_empresa"].fillna("SEM_EMPRESA") if "nome_empresa" in df.columns else "SEM_EMPRESA"
    df["id_linha"] = df.get("id_linha", None)
    df["nome_linha"] = df["nome_linha"].fillna("SEM_LINHA")     if "nome_linha"   in df.columns else "SEM_LINHA"
    df["id_rbc"] = df["id_rbc"].fillna(df["endereco_mac"])  if "id_rbc"       in df.columns else df["endereco_mac"]
    df["nome_rbc"] = df["nome_rbc"].fillna(df["endereco_mac"]) if "nome_rbc"    in df.columns else df["endereco_mac"]

    limiteMinutosSemLeitura = 10

    df["data_hora_iso"] = pd.to_datetime(df["data_hora_iso"], errors="coerce")
    horarioAtualEtl = pd.Timestamp.now()
    if df["data_hora_iso"].dt.tz is not None:
        horarioAtualEtl = pd.Timestamp.now(tz=df["data_hora_iso"].dt.tz)
    df["horario_atual_etl"] = horarioAtualEtl

    df["idade_ultima_leitura_minutos"] = (
        horarioAtualEtl - df["data_hora_iso"]
    ).dt.total_seconds() / 60.0

    df["idade_ultima_leitura_segundos"] = (
        df["idade_ultima_leitura_minutos"] * 60.0
    )
    df["rbc_status"] = np.where(
        df["idade_ultima_leitura_minutos"].fillna(float("inf")) >= limiteMinutosSemLeitura,
        "OFFLINE",
        "ONLINE",
    )
    df["rbc_status_motivo"] = np.where(
        df["rbc_status"].eq("OFFLINE"),
        f"RBC sem leitura recente há {limiteMinutosSemLeitura}+ minutos",
        None
    )
    
    df["gap_leitura_anterior_minutos"] = df["idade_ultima_leitura_minutos"]
    df["custo_leitura_anterior_minutos"] = df["idade_ultima_leitura_minutos"] * 1875
    df["custo_leitura_anterior_segundos"] = df["idade_ultima_leitura_segundos"] * 1875/60
    df["horario_atual_etl"] = horarioAtualEtl.isoformat()

    df["score"] = (
        df["percentual_uso_cpu"].fillna(0) * 0.4
        + df["percentual_uso_ram"].fillna(0) * 0.4  
        + df["percentual_uso_disco"].fillna(0) * 0.2
    )


    print(f"[banco] Mapeamento concluído: {mapeamento['id_empresa'].nunique()} empresa(s), "
          f"{mapeamento['id_linha'].nunique()} linha(s), {mapeamento['id_rbc'].nunique()} RBC(s).")

    ids_rbc = [int(i) for i in df["id_rbc"].dropna().unique() if str(i).lstrip("-").isdigit()]
    print(f"[banco] Buscando limites de componentes para {len(ids_rbc)} RBC(s) …")
    tabela_limites = buscar_limites_rbc(ids_rbc)

    if tabela_limites.empty:
        df["limites_componentes"] = [{} for _ in range(len(df))]
        print("[banco] Nenhum limite de componente encontrado; coluna preenchida com dicts vazios.")
    else:
        tabela_limites["id_rbc"] = pd.to_numeric(tabela_limites["id_rbc"])
        df["id_rbc_num"] = pd.to_numeric(df["id_rbc"], errors="coerce")
        df = df.merge(tabela_limites, left_on="id_rbc_num", right_on="id_rbc", how="left", suffixes=("", "_lim"))
        df.drop(columns=["id_rbc_num", "id_rbc_lim"], errors="ignore", inplace=True)
        df["limites_componentes"] = [
            v if isinstance(v, dict) else {}
            for v in df["limites_componentes"]
        ]
        rbcs_com_limite = tabela_limites["id_rbc"].nunique()
        print(f"[banco] Limites aplicados para {rbcs_com_limite} RBC(s).")

    return df

def buscarQuantidadeServidores(idEmpresa, idLinha):
    conn = conexao_mysql()
    try:
        cursor = conn.cursor(True)
        sql = """
                SELECT
                    COUNT(r.idRbc) AS quantidade_servidores
                    FROM rbc as r
                        JOIN linha  as  l ON r.fkLinha   = l.idLinha
                        JOIN empresa as e ON e.idEmpresa = l.fkEmpresa
                    WHERE e.idEmpresa = %s and l.idLinha = %s;
            """
        cursor.execute(sql, (idEmpresa, idLinha))
        resultado = cursor.fetchall()
    finally:
        conn.close()

    if not resultado:
        return pd.DataFrame(columns=[
            "quantidade_servidores"
        ])
    return pd.DataFrame(resultado, columns=["quantidade_servidores"])


def main():
    df = extrair_e_enriquecer()

    print("\n" + "=" * 60)
    print("DataFrame enriquecido — resumo")
    print("=" * 60)
    print(f"Linhas          : {len(df):,}")
    print(f"Colunas         : {len(df.columns)}")
    print(f"Empresas        : {df['id_empresa'].nunique(dropna=False)}")
    print(f"Linhas de prod. : {df['id_linha'].nunique(dropna=False)}")
    print(f"RBCs            : {df['id_rbc'].nunique(dropna=False)}")
    com_limite = df["limites_componentes"].apply(lambda x: bool(x)).sum()
    print(f"Leituras c/ limites do banco: {com_limite:,}")
    print(df)
    df.to_csv('dataframe_enriquecido.csv', index=False)
    print("=" * 60)
    return df


def dashboardOperacao():
    df = extrair_e_enriquecer()

    df["data_hora_envio"] = pd.to_datetime(df["data_hora_envio"], errors="coerce")

    df = df.sort_values(
        ["id_empresa", "id_linha", "id_rbc", "data_hora_envio"]
    )
    
    df["diff_envio_segundos"] = (
        df.groupby(["id_empresa", "id_linha", "id_rbc"])["data_hora_envio"]
        .diff()
    ).dt.total_seconds()

    TEMPO_COLETA = 5
    TOLERANCIA = 30
    CUSTO_SEGUNDO = 31.25

    df["segundos_excesso"] = (
        df["diff_envio_segundos"] - TEMPO_COLETA - TOLERANCIA
    ).clip(lower=0)
    
    df["qtd_servidores"] = df.groupby(
        ["id_empresa", "id_linha"]
    )["id_rbc"].transform("nunique")
    
    df.drop(columns=["processos", "limites_componentes", "idade_ultima_leitura_minutos", "idade_ultima_leitura_segundos"], inplace=True)
        
    df["custo_desperdicado"] = df["segundos_excesso"] * CUSTO_SEGUNDO / df["qtd_servidores"]
    
    df.to_csv("df.csv", index=False)
    resultado = {}
    for (id_empresa, nome_empresa), df_empresa in df.groupby(["id_empresa", "nome_empresa"]):
        custo_empresa = df_empresa["custo_desperdicado"].sum()
        resultado[id_empresa] = {
            "nome": nome_empresa,
            "custo_total": float(custo_empresa),
            "linhas": {},
            "graficos": {}
        }
        df_lote_custo = (
            df_empresa
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
            for indice, linha in df_lote_custo.iterrows()
        ]
        
        for (id_linha, nome_linha), df_lin in df_empresa.groupby(["id_linha", "nome_linha"]):
            custo_linha = df_lin["custo_desperdicado"].sum()
            resultado[id_empresa]["linhas"][id_linha] = {
                "nome": nome_linha,
                "custo_total": float(custo_linha),
                "servidores": {}
            }
            for (id_rbc, nome_rbc), df_rbc in df_lin.groupby(["id_rbc", "nome_rbc"]):
                custo_rbc = df_rbc["custo_desperdicado"].sum()
                resultado[id_empresa]["linhas"][id_linha]["servidores"][id_rbc] = {
                    "nome": nome_rbc,
                    "custo_total": float(custo_rbc)
                }
    print("Resultado: ", resultado)
    
    with open("saida.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, indent=2, ensure_ascii=False)
        
        
#===
def gerar_id_incidente():
    return str(uuid.uuid4())


def converter_float(valor, padrao=0.0):
    try:
        if pd.isna(valor):
            return padrao
        return float(valor)
    except Exception:
        return padrao


#deteccões dos incidentes e atribuir tipo
def detectar_offline(row):
    if row.get("rbc_status") != "OFFLINE":
        return None

    return {
        "titulo": "RBC offline",
        "descricao": row.get(
            "rbc_status_motivo",
            "Servidor sem comunicação."
        ),
        "nivel": "Crítico",
        "tipo": "OFFLINE"
    }


def detectar_cpu(row, limites):
    cpu = converter_float(row.get("percentual_uso_cpu"))
    
   
    config_comp = limites.get("CPU_PER", {})
    limite_padrao = converter_float(os.getenv("LIMITE_PADRAO_CPU", 90.0))
    limite = config_comp.get("limite_critico", limite_padrao)

    if cpu < limite:
        return None

    unidade = config_comp.get("unidade", "%")
    tipo = config_comp.get("tipo_componente", "Processador")

    return {
        "titulo": f"Alerta Crítico: {tipo} sobrecarregado",
        "descricao": (
            f"O servidor '{row.get('nome_rbc')}' ultrapassou o limite operacional seguro de {limite}{unidade} "
            f"Valor coletado no momento: {cpu:.1f}{unidade}" #deixa as descrições dinamicas com base na etl grandona
            
        ),
        "nivel": "Alto",
        "tipo": "CPU"
    }


def detectar_ram(row, limites):
    ram = converter_float(row.get("percentual_uso_ram"))
    
    limite_padrao = converter_float(os.getenv("LIMITE_PADRAO_RAM", 85.0))
    limite = limites.get("RAM_PER", {}).get("limite_critico", limite_padrao)

    if ram < limite:
        return None

    return {
        "titulo": "Consumo elevado de RAM",
        "descricao": f"Servidor {row.get('nome_rbc')} está consumindo {ram:.1f}% da RAM",
        "nivel": "Médio",
        "tipo": "RAM"
    }


def detectar_disco(row, limites):
    disco = converter_float(row.get("percentual_uso_disco"))
    
    limite_padrao = converter_float(os.getenv("LIMITE_PADRAO_DISCO", 90.0))
    limite = limites.get("DISK_PER", {}).get("limite_critico", limite_padrao)

    if disco < limite:
        return None

    return {
        "titulo": "Uso crítico de disco",
        "descricao": f"Servidor {row.get('nome_rbc')} está utilizando {disco:.1f}% do disco",
        "nivel": "Alto",
        "tipo": "DISCO"
    }


def detectar_latencia(row):
    latencia = converter_float(row.get("latencia_ping_ms"))
    
    limite_latencia = converter_float(os.getenv("LIMITE_PADRAO_LATENCIA", 200.0))

    if latencia < limite_latencia:
        return None

    return {
        "titulo": "Alta latência de rede",
        "descricao": f"Servidor {row.get('nome_rbc')} está com latência de {latencia:.1f} ms",
        "nivel": "Alto",
        "tipo": "LATENCIA"
    }


def montar_incidente(row, deteccao):
    horario_evento = row.get("data_hora_iso")
    if isinstance(horario_evento, pd.Timestamp):
        horario_evento = horario_evento.isoformat()

    return {
        "id": gerar_id_incidente(),

        "empresa": {
            "id": row.get("id_empresa"),
            "nome": row.get("nome_empresa")
        },

        "linha": {
            "id": row.get("id_linha"),
            "nome": row.get("nome_linha")
        },

        "rbc": {
            "id": row.get("id_rbc"),
            "nome": row.get("nome_rbc")
        },
        
        #tudo q vai do incidente para o dash
        "tipo": deteccao["tipo"],
        "titulo": deteccao["titulo"],
        "descricao": deteccao["descricao"],
        "nivel": deteccao["nivel"],
        "status": "ABERTO",
        "responsavel": "NÃO ATRIBUIDO", 

        "horario_evento": str(horario_evento),
        "horario_processamento": str(row.get("horario_atual_etl")), 

        "hardware": { 
            "cpu": converter_float(row.get("percentual_uso_cpu")),
            "ram": converter_float(row.get("percentual_uso_ram")),
            "disco": converter_float(row.get("percentual_uso_disco")),
            "latencia": converter_float(row.get("latencia_ping_ms"))
        },

        "score_operacional": converter_float(row.get("score")),
        "offline": (row.get("rbc_status") == "OFFLINE")
    }


#principal de tudo
def gerar_incidentes(df: pd.DataFrame):
    incidentes = []

    for _, row in df.iterrows():
        limites = row.get("limites_componentes", {})
        if not isinstance(limites, dict):
            limites = {}

        deteccoes = [
            detectar_offline(row),
            detectar_cpu(row, limites),
            detectar_ram(row, limites),
            detectar_disco(row, limites),
            detectar_latencia(row)
        ]

    
        deteccoes_ativas = [d for d in deteccoes if d is not None]

        for deteccao in deteccoes_ativas:
            incidente = montar_incidente(row, deteccao)
            incidentes.append(incidente)

    return incidentes

def salvar_incidentes_json(incidentes, caminho="incidentes.json"): #trocar dps
    try:
        with open(caminho, "w", encoding="utf-8") as indvLetuca:
            json.dump(
                fix_numpy(incidentes),
                indvLetuca,
                indent=2,
                ensure_ascii=False
            )
        print(f"[incidentes] {len(incidentes)} incidentes salvos com sucesso em '{caminho}'")
    except Exception as e:
        print(f"Erro: falha ao salvar o arquivo JSON de incidentes: {e}")
        
        
def dashboardIncidentes():
    print("\nTESTE INCIDENTES")
    print("=" * 60)

    #pode ser um problema dps pq chama o banco mais uma vez (?)
    df = extrair_e_enriquecer().head(10)


    print(f"[incidentes] Processando {len(df)} leituras...")
    incidentes = gerar_incidentes(df)
    
    if not incidentes:
        print("[incidentes] Nenhum incidente crítico detectado no momento")

    salvar_incidentes_json(incidentes, "incidentes.json")
    print(f"[incidentes] Concluído - {len(incidentes)} incidentes gerados")

    return incidentes 


#def lambda_handler(event, context):
#    df = extrair_e_enriquecer(
#        bucket=event.get("bucket"),
#        key=event.get("key"),
#        usar_banco=not event.get("no_db", False),
#    )
#    return {
#        "statusCode": 200,
#        "linhas": len(df),
#        "colunas": list(df.columns),
#    }


dashboardOperacao()
dashboardIncidentes()