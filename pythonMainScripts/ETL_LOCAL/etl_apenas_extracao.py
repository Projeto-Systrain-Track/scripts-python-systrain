from __future__ import annotations

from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from io import StringIO, BytesIO
import mysql.connector
import pandas as pd
import numpy as np
import boto3
import os
import datetime
load_dotenv()

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
    ultimas_n_linhas: Optional[int] = None,
) -> pd.DataFrame:
    """
    Baixa o CSV do S3 e devolve um DataFrame já com tipos básicos corrigidos.

    Parâmetros
    ----------
    bucket : str, opcional
        Nome do bucket. Se None, lê de S3_BUCKET no .env.
    key : str, opcional
        Caminho do arquivo dentro do bucket. Se None, lê de S3_KEY no .env.
    ultimas_n_linhas : int, opcional
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

    if ultimas_n_linhas:
        # Lê apenas as últimas N linhas sem carregar tudo na memória de uma vez
        linhas = conteudo_bytes.decode("utf-8").splitlines()
        cabecalho = linhas[0]
        dados = linhas[max(1, len(linhas) - ultimas_n_linhas):]
        conteudo_str = "\n".join([cabecalho] + dados)
        df = pd.read_csv(StringIO(conteudo_str), low_memory=False)
    else:
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
    ultimas_n_linhas: Optional[int] = None,
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
    ultimas_n_linhas : int, opcional
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
    # resolve ultimas_n_linhas a partir do .env se não informado
    if ultimas_n_linhas is None:
        last_n_env = os.getenv("LAST_N")
        ultimas_n_linhas = int(last_n_env) if last_n_env else None

    #  1. extração S3 
    df = extrair_csv_s3(bucket=bucket, key=key, ultimas_n_linhas=ultimas_n_linhas)

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
    df: pd.DataFrame = extrair_e_enriquecer()
    i = 1
    custos_por_empresa = {}

    # FILTRO DIÁRIO

    df = df.sort_values("data_hora_iso", ascending=True)
    df["data_hora_envio"] = pd.to_datetime(df["data_hora_envio"], errors="coerce")
    df["diff_envio"] = (
        df.groupby(["id_empresa", "id_linha", "id_rbc"])["data_hora_envio"]
        .diff()
    )
    df.drop(columns=["processos"], inplace=True, errors="ignore")

    df_diario = df[pd.to_datetime(df["data_hora_iso"], errors="coerce").dt.date == pd.Timestamp.now().date()]
    if (not df_diario.empty):
        df_diario.sort_values("data_hora_iso", ascending=False, inplace=True)
    else:
        print("Nenhum dado encontrado para o dia de hoje.")

        
    limite = pd.Timestamp.now().date() - pd.Timedelta(days=7)

    df.to_csv('dataframe_enriquecido.csv', index=False)

    df_semanal = df[pd.to_datetime(df["data_hora_iso"], errors="coerce").dt.date >= limite]
    if(not df_semanal.empty):
        for (idEmpresa, nomeEmpresa), tabelaEmpresa in df_semanal.groupby(["id_empresa", "nome_empresa"], dropna=True):
            print("Fazendo leitura da empresa: "+ str(nomeEmpresa))
            custo_empresa = {}
            for (idLinha, nomeLinha), tabelaLinha in df_semanal.groupby(["id_linha", "nome_linha"], dropna=True):
                print("Fazendo leitura da linha: " + str(nomeLinha))
                custo_linha = {}
                quantidade_servidores = buscarQuantidadeServidores(idEmpresa, idLinha)
                for (idRbc, nomeRbc), tabelaRbc in df_semanal.groupby(["id_rbc", "nome_rbc"], dropna=True):
                    tabelaRbc.sort_values("data_hora_iso", ascending=False, inplace=True)
                    ultima_captura = tabelaRbc.iloc[0]
                    
                    



#def lambda_handler(event, context):
#    df = extrair_e_enriquecer(
#        bucket=event.get("bucket"),
#        key=event.get("key"),
#        ultimas_n_linhas=event.get("ultimas_n_linhas"),
#        usar_banco=not event.get("no_db", False),
#    )
#    return {
#        "statusCode": 200,
#        "linhas": len(df),
#        "colunas": list(df.columns),
#    }


dashboardOperacao()