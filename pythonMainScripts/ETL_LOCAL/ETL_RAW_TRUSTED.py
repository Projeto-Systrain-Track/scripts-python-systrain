from __future__ import annotations

import json
import os
from io import BytesIO
from typing import Any, Optional
from datetime import datetime, timedelta
import boto3
from botocore.exceptions import ClientError
import numpy as np
import pandas as pd
import mysql.connector
from dotenv import load_dotenv

load_dotenv()


LIMITE_OFFLINE_MINUTOS = 10
PESO_CPU = 0.4
PESO_RAM = 0.4
PESO_DISCO = 0.2

CFG = {
    "last_n": 10,  # quantas últimas leituras incluir por RBC no JSON
}


#p evitar chamadas repetidas p a mesma cidade na mesma rodada
CACHE_CLIMA: dict[str, dict] = {}

#mapeamento geográfico aprox. p consultas na api
COORDENADAS_REGIOES = {
    "NORTE": {"lat": -23.4842, "lon": -46.6256},
    "SUL":   {"lat": -23.6822, "lon": -46.6917},
    "LESTE": {"lat": -23.5514, "lon": -46.5015},
    "OESTE": {"lat": -23.5593, "lon": -46.7214},
    "CENTRO": {"lat": -23.5489, "lon": -46.6388}
}
def cfg_mysql() -> dict:
    """Lê credenciais do MySQL a partir de variáveis de ambiente."""
    return {
        "host":     os.getenv("MYSQL_HOST"),
        "port":     int(os.getenv("MYSQL_PORT", 3306)),
        "user":     os.getenv("MYSQL_USER"),
        "password": os.getenv("MYSQL_PASSWORD"),
        "database": os.getenv("MYSQL_DATABASE"),
    }


def cfg_s3() -> dict:
    """Lê credenciais AWS a partir de variáveis de ambiente."""
    return {
        "region_name":           "us-east-1",
        "aws_access_key_id":     os.getenv("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
        "aws_session_token":     os.getenv("AWS_SESSION_TOKEN"),
    }


def conexao_mysql():
    """Abre e retorna uma conexão MySQL. Sempre fechar no finally."""
    return mysql.connector.connect(**cfg_mysql())


def limpar_mac(valor: Any) -> Any:
    """Normaliza endereço MAC: lowercase e sem espaços."""
    if pd.isna(valor):
        return valor
    return str(valor).strip().lower().replace(":", "-")


def separar_definicao(definicao: Any) -> dict:
    """
    Parseia a string de definição do banco no formato
    'limite_alerta=80;limite_critico=95' → {'limite_alerta': 80.0, 'limite_critico': 95.0}
    """
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
        try:
            resultado[chave.strip()] = float(valor.strip())
        except ValueError:
            resultado[chave.strip()] = valor.strip()
    return resultado


def native(valor: Any) -> Any:
    """
    Converte tipos NumPy/Pandas para tipos nativos Python,
    garantindo que o json.dumps não quebre.
    Retorna None para NaN/NaT/pd.NA.
    """
    if valor is None:
        return None
    if isinstance(valor, float) and np.isnan(valor):
        return None
    if isinstance(valor, (np.integer,)):
        return int(valor)
    if isinstance(valor, (np.floating,)):
        return float(valor)
    if isinstance(valor, (np.bool_,)):
        return bool(valor)
    if isinstance(valor, pd.Timestamp):
        return valor.isoformat() if not pd.isna(valor) else None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    return valor


def calcular_score(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula um score de saúde (0–100) como média ponderada de CPU, RAM e Disco.
    Quanto maior o score, maior a pressão sobre o hardware.
    """
    df["score_saude"] = (
          df["percentual_uso_cpu"].fillna(0)   * PESO_CPU
        + df["percentual_uso_ram"].fillna(0)   * PESO_RAM
        + df["percentual_uso_disco"].fillna(0) * PESO_DISCO
    )
    return df


def buscar_mapeamento_rbc(mac_adress: list[str]) -> pd.DataFrame:
    if not mac_adress:
        return pd.DataFrame(columns=[
            "endereco_mac", "id_empresa", "nome_empresa",
            "id_linha", "nome_linha", "id_rbc", "nome_rbc", "objetivoFinanceiro",
        ])

    conn = conexao_mysql()
    try:
        print(mac_adress)
        cursor = conn.cursor(dictionary=True)
        sql = """
            SELECT
                LOWER(TRIM(r.macAdress)) AS endereco_mac,
                e.idEmpresa AS id_empresa,
                e.razaoSocial AS nome_empresa,
                e.url_jira,
                e.email_usuario_jira,
                e.token_usuario_jira,
                l.idLinha AS id_linha,
                CONCAT('Linha ', l.idLinha) AS nome_linha,
                r.idRbc AS id_rbc,
                r.nomeServidor AS nome_rbc,
                
                r.objetivoFinanceiro AS objetivoFinanceiro

            FROM rbc r
            JOIN linha   l ON r.fkLinha   = l.idLinha
            JOIN empresa e ON e.idEmpresa = l.fkEmpresa
            WHERE LOWER(TRIM(r.macAdress)) = %s
        """
        cursor.execute(sql, (mac_adress[0],))
        rows = cursor.fetchall()
    finally:
        conn.close()

    if not rows:
        return pd.DataFrame(columns=[
            "endereco_mac", "id_empresa", "nome_empresa",
            "id_linha", "nome_linha", "id_rbc", "nome_rbc", "objetivoFinanceiro",
        ])
    # return pd.DataFrame(rows)

    #adicionando a coluna manualmente enquanto nao existe no banco ainda (adicionar no select dps)
    df_map = pd.DataFrame(rows)
    df_map["regiao"] = "CENTRO"
    
    return df_map

def buscar_limites_rbc(id_rbc) -> pd.DataFrame:
    """
    Busca no banco os limites de alerta e crítico de cada componente
    para os RBCs informados.
    """
    ids_validos = pd.to_numeric(pd.Series(id_rbc), errors="coerce").dropna().astype(int).unique().tolist()

    if not ids_validos:
        print("[banco] AVISO — nenhum id_rbc numérico válido para buscar limites.")
        return pd.DataFrame()

    conn = conexao_mysql()
    try:
        cursor = conn.cursor(dictionary=True)
        placeholders = ",".join(["%s"] * len(ids_validos))
        sql = f"""
            SELECT
                rc.fkRbc     AS id_rbc,
                c.nome       AS codigo_componente,
                rc.definicao AS definicao
            FROM rbcComponente rc
            JOIN componente c ON c.idComponente = rc.fkComponente
            WHERE rc.fkRbc IN ({placeholders})
        """
        cursor.execute(sql, ids_validos)
        resultado_select = cursor.fetchall()
    finally:
        conn.close()

    if not resultado_select:
        return pd.DataFrame()

    mapa_colunas = {
        "CPU_PER":     ("limite_cpu_alerta", "limite_cpu_critico"),
        "RAM_PER":     ("limite_ram_alerta", "limite_ram_critico"),
        "VOL_PER":     ("limite_disco_alerta", "limite_disco_critico"),
        "WEB_NUM":     ("limite_latencia_alerta", "limite_latencia_critico"),
        "PRS_CPU_PER": ("limite_proc_cpu_alerta", "limite_proc_cpu_critico"),
        "PRS_RAM_PER": ("limite_proc_ram_alerta", "limite_proc_ram_critico"),
        "PRS_CPU_THR": ("limite_proc_threads_alerta", "limite_proc_threads_critico"),
        "PRS_NUM":     ("limite_proc_qtd_alerta", "limite_proc_qtd_critico"),
        "PRS_RAM_USE": ("limite_proc_ram_uso_alerta", "limite_proc_ram_uso_critico"),
    }

    resultado = {}

    for linha in resultado_select:
        id_rbc_linha = linha["id_rbc"]
        codigo = linha["codigo_componente"]
        definicao_dicionario = separar_definicao(linha["definicao"])

        if id_rbc_linha not in resultado:
            resultado[id_rbc_linha] = {"id_rbc": id_rbc_linha}

        if codigo in mapa_colunas:
            coluna_atencao, coluna_critico = mapa_colunas[codigo]
            resultado[id_rbc_linha][coluna_atencao] = definicao_dicionario.get("limite_alerta")
            resultado[id_rbc_linha][coluna_critico] = definicao_dicionario.get("limite_critico")

        elif codigo == "PRS_STX":
            resultado[id_rbc_linha]["limite_proc_sintaxe"] = definicao_dicionario.get("valor")

    return pd.DataFrame(resultado.values())


def classificar_alerta(valor: float, limite_atencao: Any, limite_critico: Any):
    try:
        v = float(valor)
        if limite_critico is not None and v >= float(limite_critico):
            return "CRITICO", limite_critico
        if limite_atencao is not None and v >= float(limite_atencao):
            return "ATENÇÃO", limite_atencao
    except (TypeError, ValueError):
        pass
    return None, 0


def retornar_motivo_alerta(nome_coluna, status, limite):
    motivo_descricao = ""
    motivo_resumido = ""
    if nome_coluna == "percentual_uso_cpu":
        motivo_descricao = f"Percentual de CPU acima de {limite}% "
        motivo_resumido = f"CPU acima de {limite}% "
    elif nome_coluna == "percentual_uso_ram":
        motivo_descricao = f"Percentual de RAM acima de {limite}% "
        motivo_resumido = f"RAM acima de {limite}% "
    elif nome_coluna == "percentual_uso_disco":
        motivo_descricao = f"Percentual de DISCO acima de {limite}% "
        motivo_resumido = f"DISCO acima de {limite}% "
    elif nome_coluna == "latencia_ping_ms":
        motivo_descricao = f"Percentual de LATENCIA acima de {limite}ms "
        motivo_resumido = f"LATENCIA acima de {limite}ms "
    return motivo_descricao, motivo_resumido

def aplicar_alertas(df: pd.DataFrame):
    colunas_limite = {
        "percentual_uso_cpu":   ("limite_cpu_alerta",      "limite_cpu_critico"),
        "percentual_uso_ram":   ("limite_ram_alerta",      "limite_ram_critico"),
        "percentual_uso_disco": ("limite_disco_alerta",    "limite_disco_critico"),
        "latencia_ping_ms":     ("limite_latencia_alerta", "limite_latencia_critico"),
    }
    alertas_gerados = []
    qte_alertas_criticos = 0
    qte_alertas_atencao = 0
    qte_alertas_cpu = 0
    qte_alertas_ram = 0
    qte_alertas_disco = 0
    qte_alertas_latencia = 0

    for linha in df.itertuples():
        for nome_coluna, limites in colunas_limite.items():
            valor_captura = getattr(linha, nome_coluna, None)
            limite_atencao = getattr(linha, limites[0], None)
            limite_critico = getattr(linha, limites[1], None)
            status_alerta, limite_usado = classificar_alerta(valor_captura, limite_atencao, limite_critico)
            if status_alerta is None:
                continue
            motivo_descricao, motivo_resumo = retornar_motivo_alerta(
                nome_coluna=nome_coluna, status=status_alerta, limite=limite_usado
            )
            alertas_gerados.append({
                "id_empresa":          linha.id_empresa,
                "nome_empresa":        linha.nome_empresa,
                "id_linha":            linha.id_linha,
                "nome_linha":          linha.nome_linha,
                "id_rbc":              linha.id_rbc,
                "nome_rbc":            linha.nome_rbc,
                "endereco_mac":        linha.endereco_mac,
                "campo_alerta":        nome_coluna,
                "valor_medido":        valor_captura,
                "componente_afetado":  limites[0].split("_")[1],
                "tipo_alerta":         status_alerta,
                "motivo_alerta":       motivo_descricao,
                "motivo_resumido":     motivo_resumo,
                "data_hora_iso":       linha.data_hora_iso,
                "limite_atencao":      limite_atencao,
                "limite_critico":      limite_critico,
                "url_jira":            linha.url_jira,
                "email_usuario_jira":  linha.email_usuario_jira,
                "token_usuario_jira":  linha.token_usuario_jira,
            })
            if status_alerta == "CRITICO":
                qte_alertas_criticos += 1
            else:
                qte_alertas_atencao += 1

            if nome_coluna == "percentual_uso_cpu":
                qte_alertas_cpu += 1
            elif nome_coluna == "percentual_uso_ram":
                qte_alertas_ram += 1
            elif nome_coluna == "percentual_uso_disco":
                qte_alertas_disco += 1
            elif nome_coluna == "latencia_ping_ms":
                qte_alertas_latencia += 1

    df["qte_alertas_critico"]  = qte_alertas_criticos
    df["qte_alertas_atencao"]  = qte_alertas_atencao
    df["qte_alertas_cpu"]      = qte_alertas_cpu
    df["qte_alertas_ram"]      = qte_alertas_ram
    df["qte_alertas_disco"]    = qte_alertas_disco
    df["qte_alertas_latencia"] = qte_alertas_latencia

    alertas_gerados = pd.DataFrame(alertas_gerados)
    alertas_gerados.to_csv("alertas.csv", index=False)
    return df, alertas_gerados


def aplicar_status_online(df: pd.DataFrame) -> pd.DataFrame:
    """
    Marca o servidor como OFFLINE se a leitura mais recente do arquivo
    tiver mais de LIMITE_OFFLINE_MINUTOS em relação ao momento de execução da ETL.
    """
    agora = pd.Timestamp.now()

    df["data_hora_iso"] = pd.to_datetime(df["data_hora_iso"], errors="coerce")

    df["idade_ultima_leitura_minutos"] = (
        agora - df["data_hora_iso"]
    ).dt.total_seconds() / 60

    df["rbc_status"] = np.where(
        df["idade_ultima_leitura_minutos"] >= LIMITE_OFFLINE_MINUTOS,
        "OFFLINE",
        "ONLINE",
    )
    df["rbc_status_motivo"] = np.where(
        df["rbc_status"] == "OFFLINE",
        f"Sem leitura há {LIMITE_OFFLINE_MINUTOS}+ min",
        None,
    )
    return df


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
    print(f"[S3] Baixando s3://{bucket}/{key} ...")
    verificar_existe = arquivo_existe(bucket=bucket, key=key)
    if verificar_existe:
        resposta = s3.get_object(Bucket=bucket, Key=key)
        conteudo = resposta["Body"].read()
        print(f"[S3] {len(conteudo):,} bytes recebidos.")
        df = pd.read_csv(BytesIO(conteudo))
        obrigatorias = ["endereco_mac", "data_hora_iso"]
        ausentes = [c for c in obrigatorias if c not in df.columns]
        if ausentes:
            raise ValueError(f"Colunas obrigatórias ausentes no CSV: {ausentes}")
        df["endereco_mac"]  = df["endereco_mac"].map(limpar_mac)
        df["data_hora_iso"] = pd.to_datetime(df["data_hora_iso"], errors="coerce")
        print(f"[S3] {len(df):,} linhas | {df['endereco_mac'].nunique()} MAC(s).")
        return df
    return None


def caminho_para_tratado(df: pd.DataFrame, tipo: str):
    nome_empresa = df["nome_empresa"].dropna().unique()
    nome_empresa = nome_empresa[0]
    nome_empresa = nome_empresa.replace(" ", "_").lower()
    mac_adress = df["endereco_mac"].dropna().unique()
    mac_adress = mac_adress[0]
    data_atual = datetime.now()
    ano  = data_atual.year
    mes  = data_atual.month
    dia  = data_atual.day

    if tipo == "alerta":
        return f"trusted/{nome_empresa}/{ano}/{mes}/{dia}/alertas/abertos/{mac_adress}.csv"
    elif tipo == "tratado":
        return f"trusted/{nome_empresa}/{ano}/{mes}/{dia}/tratados/{mac_adress}.csv"
    elif tipo == "semanal-tratados":
        return f"trusted/{nome_empresa}/semanal/tratados/{mac_adress}.csv"
    elif tipo == "semanal-alertas":
        return f"trusted/{nome_empresa}/semanal/alertas/{mac_adress}.csv"
    elif tipo == "json":
        return f"trusted/{nome_empresa}/{ano}/{mes}/{dia}/json/{mac_adress}.json"
    elif tipo == "semanal-json":
        return f"trusted/{nome_empresa}/semanal/json/{mac_adress}.json"
    elif tipo == "incidentes":
        caminho = f"trusted/{nome_empresa}/{ano}/{mes}/{dia}/incidentes/incidentes_{ano}-{mes}-{dia}.csv"
    else:
        raise ValueError(f"Tipo desconhecido: {tipo}")
    return caminho
        

def extrair_e_enriquecer(bucket: str, key: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = extrair_csv_s3(bucket=bucket, key=key)
    if df is not None:
        mac_adress_servidor = df["endereco_mac"].dropna().unique().tolist()
        print(f"[banco] Buscando mapeamento para {len(mac_adress_servidor)} MAC(s)...")

        mapeamento = buscar_mapeamento_rbc(mac_adress_servidor)

        sem_cadastro = set(mac_adress_servidor) - set(mapeamento["endereco_mac"].tolist())
        if sem_cadastro:
            print(f"[banco] AVISO — MACs sem cadastro: {sem_cadastro}")

        df = df.merge(mapeamento, on="endereco_mac", how="left")

        df["nome_empresa"] = df["nome_empresa"].fillna("SEM_EMPRESA")
        df["nome_linha"]   = df["nome_linha"].fillna("SEM_LINHA")
        df["id_rbc"]       = df["id_rbc"].fillna(df["endereco_mac"])
        df["nome_rbc"]     = df["nome_rbc"].fillna(df["endereco_mac"])

        print(f"[banco] Buscando limites para {df['id_rbc'].dropna().unique()} RBC(s)...")

        tabela_limites = buscar_limites_rbc(df["id_rbc"].dropna().unique())
        if tabela_limites.empty:
            print("[banco] AVISO — nenhum limite encontrado. Alertas não serão gerados.")
            colunas_limite = [
                "limite_cpu_alerta", "limite_cpu_critico",
                "limite_ram_alerta", "limite_ram_critico",
                "limite_disco_alerta", "limite_disco_critico",
                "limite_latencia_alerta", "limite_latencia_critico",
                "limite_proc_cpu_alerta", "limite_proc_cpu_critico",
                "limite_proc_ram_alerta", "limite_proc_ram_critico",
                "limite_proc_threads_alerta", "limite_proc_threads_critico",
                "limite_proc_qtd_alerta", "limite_proc_qtd_critico",
                "limite_proc_ram_uso_alerta", "limite_proc_ram_uso_critico",
                "limite_proc_sintaxe",
            ]
            for col in colunas_limite:
                df[col] = np.nan
        else:
            tabela_limites["id_rbc"] = pd.to_numeric(tabela_limites["id_rbc"], errors="coerce")
            df["_id_rbc_num"] = pd.to_numeric(df["id_rbc"], errors="coerce")
            df = df.merge(
                tabela_limites,
                left_on="_id_rbc_num",
                right_on="id_rbc",
                how="left",
                suffixes=("", "_lim"),
            )
            df.drop(columns=["_id_rbc_num", "id_rbc_lim"], errors="ignore", inplace=True)
            print(f"[banco] Limites aplicados para {tabela_limites['id_rbc'].nunique()} RBC(s).")

        df, df_alertas = aplicar_alertas(df)
        df = calcular_score(df)
        df = aplicar_status_online(df)

        if df_alertas.empty:
            print("[alertas] Nenhum alerta nesta leitura.")
        else:
            print(
                f"[alertas] {len(df_alertas)} alerta(s) gerado(s): "
                f"{df_alertas['tipo_alerta'].value_counts().to_dict()}"
            )

        df.drop(columns=[
            "limite_cpu_alerta", "limite_cpu_critico",
            "limite_ram_alerta", "limite_ram_critico",
            "limite_disco_alerta", "limite_disco_critico",
            "limite_latencia_alerta", "limite_latencia_critico",
            "limite_proc_qtd_alerta", "limite_proc_qtd_critico",
            "limite_proc_sintaxe",
            "limite_proc_ram_alerta", "limite_proc_ram_critico",
            "limite_proc_ram_uso_alerta", "limite_proc_ram_uso_critico",
            "limite_proc_cpu_alerta", "limite_proc_cpu_critico",
            "processos",
            "idade_ultima_leitura_minutos",
            "url_jira", "email_usuario_jira", "token_usuario_jira",
            "limite_proc_threads_alerta", "limite_proc_threads_critico",
        ], errors="ignore", inplace=True)

        return df, df_alertas
    return None, None


def salvar_csv_trusted(df: pd.DataFrame, bucket: str, tipo: str):
    print("Iniciando processo de salvamento do CSV...")
    caminho = caminho_para_tratado(df=df, tipo=tipo)
    print(f"Caminho gerado para o arquivo: {caminho}")
    print("Verificando se já existe arquivo no S3...")
    arquivo = extrair_csv_s3(bucket=bucket, key=caminho)
    if arquivo is not None:
        print("Arquivo existente encontrado!")
        if tipo != "semanal":
            try:
                print("Concatenando dataframe antigo com o novo...")
                df = juntar_dataframes(df1=arquivo, df2=df)
                print("Concatenação realizada com sucesso!")
                print(f"Quantidade total de linhas após concatenação: {len(df)}")
            except Exception as e:
                print(f"Erro ao tentar concatenar os dataframes: {e}")
    else:
        print("Nenhum arquivo existente encontrado no S3.")

    mac_adress = df["endereco_mac"].dropna().unique()[0]
    nome_arquivo = f"{mac_adress}.csv"
    print(f"Salvando CSV localmente como: {nome_arquivo}")
    df.to_csv(nome_arquivo, index=False)

    s3 = boto3.client("s3", **cfg_s3())
    print(f"Enviando arquivo para bucket '{bucket}'...")
    try:
        s3.upload_file(Filename=nome_arquivo, Bucket=bucket, Key=caminho)
        print("Upload realizado com sucesso!")
        return True
    except Exception as e:
        print("Erro ao tentar subir o arquivo: ", e)
    return False


def salvar_json_trusted(payload: dict, df_ref: pd.DataFrame, bucket: str, tipo: str = "json"):
    """
    Serializa `payload` como JSON e faz upload para o S3.
    `df_ref` é usado apenas para derivar o caminho (nome_empresa / mac).
    """
    print(f"[JSON] Iniciando salvamento do JSON (tipo={tipo})...")
    caminho = caminho_para_tratado(df=df_ref, tipo=tipo)
    print(f"[JSON] Caminho: s3://{bucket}/{caminho}")

    conteudo = json.dumps(payload, ensure_ascii=False, default=str, indent=2).encode("utf-8")
    nome_arquivo_local = caminho.replace("/", "_") + ".json"

    with open(nome_arquivo_local, "wb") as f:
        f.write(conteudo)

    s3 = boto3.client("s3", **cfg_s3())
    try:
        s3.upload_file(
            Filename=nome_arquivo_local,
            Bucket=bucket,
            Key=caminho,
            ExtraArgs={"ContentType": "application/json"},
        )
        print(f"[JSON] Upload concluído: s3://{bucket}/{caminho}")
        return True
    except Exception as e:
        print(f"[JSON] Erro no upload: {e}")
    return False


def juntar_dataframes(df1: pd.DataFrame, df2: pd.DataFrame):
    try:
        print("Concatenando dataframe antigo com o novo...")
        df = pd.concat([df1, df2], ignore_index=True)
        print("Concatenação realizada com sucesso!")
        print(f"Quantidade total de linhas após concatenação: {len(df)}")
        return df
    except Exception as e:
        print(f"Erro ao tentar concatenar os dataframes: {e}")
    return None


def atualizar_semanal(bucket: str, df: pd.DataFrame) -> pd.DataFrame:
    print("\n" + "=" * 80)
    print("[SEMANAL] INICIANDO ATUALIZAÇÃO DO ARQUIVO SEMANAL")
    print("=" * 80)

    print(f"[SEMANAL] Linhas recebidas do dataframe atual: {len(df)}")
    print(f"[SEMANAL] Colunas recebidas: {list(df.columns)}")

    caminho = caminho_para_tratado(df=df, tipo="semanal-tratados")
    print(f"[SEMANAL] Caminho semanal gerado: s3://{bucket}/{caminho}")

    print("[SEMANAL] Tentando buscar arquivo semanal existente no S3...")
    arquivo_antigo = extrair_csv_s3(bucket=bucket, key=caminho)

    if arquivo_antigo is not None:
        print("[SEMANAL] Arquivo semanal antigo encontrado!")
        print(f"[SEMANAL] Linhas no arquivo antigo: {len(arquivo_antigo)}")
        df_semanal = juntar_dataframes(df1=arquivo_antigo, df2=df)
        if df_semanal is None:
            raise ValueError("[SEMANAL] Erro: concatenação retornou None.")
    else:
        print("[SEMANAL] Nenhum arquivo semanal antigo encontrado.")
        df_semanal = df.copy()

    if "data_hora_iso" not in df_semanal.columns:
        raise ValueError("[SEMANAL] ERRO: coluna 'data_hora_iso' não existe no dataframe semanal.")

    df_semanal["data_hora_iso"] = pd.to_datetime(df_semanal["data_hora_iso"], errors="coerce")

    datas_invalidas = df_semanal["data_hora_iso"].isna().sum()
    if datas_invalidas > 0:
        df_semanal = df_semanal.dropna(subset=["data_hora_iso"])

    limite = pd.Timestamp.now() - pd.Timedelta(days=7)
    antes_filtro = len(df_semanal)
    df_semanal = df_semanal[df_semanal["data_hora_iso"] >= limite]
    depois_filtro = len(df_semanal)
    print(f"[SEMANAL] Linhas removidas por serem antigas: {antes_filtro - depois_filtro}")

    df_semanal = df_semanal.sort_values("data_hora_iso")

    if not df_semanal.empty:
        print(f"[SEMANAL] Primeira data mantida: {df_semanal['data_hora_iso'].min()}")
        print(f"[SEMANAL] Última data mantida:   {df_semanal['data_hora_iso'].max()}")
        print(f"[SEMANAL] MACs no semanal: {df_semanal['endereco_mac'].dropna().unique().tolist()}")
    else:
        print("[SEMANAL] AVISO: dataframe semanal ficou vazio após o filtro.")

    print("[SEMANAL] Atualização semanal finalizada com sucesso.")
    print("=" * 80 + "\n")
    return df_semanal


# ---------------------------------------------------------------------------
# JSON builders
# ---------------------------------------------------------------------------
#================================================================================================================================
def obter_clima_por_regiao(regiao: str) -> Optional[dict]:
    """Busca o clima atualizado por coordenadas usando a região de do rbc como chave."""
    if not regiao or pd.isna(regiao):
        return None
        
    regiao_chave = str(regiao).strip().upper()
    
    if regiao_chave in COORDENADAS_REGIOES:
        lat = COORDENADAS_REGIOES[regiao_chave]["lat"]
        lon = COORDENADAS_REGIOES[regiao_chave]["lon"]
        cache_key = f"{lat}_{lon}"
    else:
        cache_key = regiao_chave
        lat, lon = None, None

    # Se já estiver no cache retorna
    if cache_key in CACHE_CLIMA and isinstance(CACHE_CLIMA[cache_key], dict):
        return CACHE_CLIMA[cache_key]
        
    api_key = os.getenv("OPENWEATHER_API_KEY")
    if not api_key:
        return None
        
    try:
        import requests
        if lat and lon:
            url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units=metric&lang=pt_br"
        else:
            #vai servir p as estações que ficam fora de SP (Osasco, Suzano, Mogi...)
            url = f"https://api.openweathermap.org/data/2.5/weather?q={cache_key}&appid={api_key}&units=metric&lang=pt_br"
            
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            dados = res.json()
           
            CACHE_CLIMA[cache_key] = {
                "temp": dados["main"]["temp"],
                "cond": dados["weather"][0]["description"].capitalize(),
                "umidade": dados["main"]["humidity"],
                "velocidade_vento": dados["wind"]["speed"],
                "clima_icone": dados["weather"][0]["icon"]
            }
            return CACHE_CLIMA[cache_key]
    except Exception:
        pass
    return None

#=================================================================================================================================== 
#=================================================================================================================================== 

def processar_e_salvar_incidentes_csv(df_tratado: pd.DataFrame, df_alertas: pd.DataFrame, bucket: str):
    """
    Consolida incidentes capturando o estado do hardware/ping no momento do evento,
    enriquece geograficamente via OpenWeather por coordenadas regionais (dentro ou fora de SP) e grava em CSV por dia.
    """
    print("\n" + "=" * 50)
    print("[INCIDENTES] INICIANDO PROCESSAMENTO DE EVENTOS")
    print("=" * 50)
    
    incidentes_lista = []
    # data_atual = datetime.now().strftime("%Y-%m-%d")
    
    #OFFLINE
    df_offline = df_tratado[df_tratado["rbc_status"] == "OFFLINE"]
    for row in df_offline.itertuples():
        regiao_servidor = getattr(row, "regiao", "CENTRO") # coluna região ou assume centro de sp
        info_clima = obter_clima_por_regiao(regiao_servidor)
        
        incidentes_lista.append({
            "id_empresa": row.id_empresa, "nome_empresa": row.nome_empresa,
            "id_linha": row.id_linha, "nome_linha": row.nome_linha,
            "id_rbc": row.id_rbc, "nome_rbc": row.nome_rbc,
            "tipo_incidente": "OFFLINE", "criticidade": "CRÍTICO",
            "componente_afetado": "CONEXÃO", "descricao": "Servidor perdeu a comunicação com a central de telemetria.",
            "data_hora_evento": row.data_hora_iso,
            
            # capturado no momento da queda
            "metrica_cpu_momento": getattr(row, "percentual_uso_cpu", np.nan),
            "metrica_ram_momento": getattr(row, "percentual_uso_ram", np.nan),
            "metrica_disco_momento": getattr(row, "percentual_uso_disco", np.nan),
            "metrica_ping_momento": getattr(row, "latencia_ping_ms", np.nan),
            "score_saude_momento": getattr(row, "score_saude", np.nan),
            
            "limite_atencao_definido": None,
            "limite_critico_definido": None,
            "valor_estouro_momento": None,
            "resumo_excesso_metrica": "Servidor inativo (Timeout de rede)",
            
            #preciso por coordenadas da região
            "clima_temperatura": info_clima["temp"] if info_clima else None, 
            "clima_condicao": info_clima["cond"] if info_clima else "Erro na Consulta",
            "clima_umidade": info_clima["umidade"] if info_clima else None,
            "clima_vento": info_clima["velocidade_vento"] if info_clima else None,
            "clima_icone": info_clima["clima_icone"] if info_clima else None
        })

    #ALERTAS CRÍTICOS DE HARDWARE
    if df_alertas is not None and not df_alertas.empty:
        df_criticos = df_alertas[df_alertas["tipo_alerta"] == "CRITICO"]
        for row in df_criticos.itertuples():
            # buscando o registro original correspondente no df_tratado p pegar as outras métricas padrao
            registro_orig = df_tratado[(df_tratado["endereco_mac"] == row.endereco_mac) & 
                                       (df_tratado["data_hora_iso"] == row.data_hora_iso)]
            
            regiao_servidor = registro_orig["regiao"].iloc[0] if (not registro_orig.empty and "regiao" in registro_orig.columns) else "CENTRO"
            info_clima = obter_clima_por_regiao(regiao_servidor)
            
            # métricas paralelas do hardware
            cpu_val = registro_orig["percentual_uso_cpu"].iloc[0] if not registro_orig.empty else row.valor_medido if row.componente_afetado == "cpu" else np.nan
            ram_val = registro_orig["percentual_uso_ram"].iloc[0] if not registro_orig.empty else row.valor_medido if row.componente_afetado == "ram" else np.nan
            disco_val = registro_orig["percentual_uso_disco"].iloc[0] if not registro_orig.empty else row.valor_medido if row.componente_afetado == "disco" else np.nan
            ping_val = registro_orig["latencia_ping_ms"].iloc[0] if not registro_orig.empty else row.valor_medido if row.componente_afetado == "latencia" else np.nan
            score_val = registro_orig["score_saude"].iloc[0] if not registro_orig.empty else np.nan

            #calc do excesso
            excesso_texto = "Métrica em limite crítico"
            if pd.notna(row.valor_medido) and pd.notna(row.limite_critico):
                if row.valor_medido > row.limite_critico:
                    diferenca = row.valor_medido - row.limite_critico
                    excesso_texto = f"{diferenca:.1f}% acima do limite crítico de {row.limite_critico:.1f}%"

            incidentes_lista.append({
                "id_empresa": row.id_empresa, "nome_empresa": row.nome_empresa,
                "id_linha": row.id_linha, "nome_linha": row.nome_linha,
                "id_rbc": row.id_rbc, "nome_rbc": row.nome_rbc,
                "tipo_incidente": "HARDWARE", "criticidade": "ALTO",
                "componente_afetado": str(row.componente_afetado).upper(), "descricao": str(row.motivo_alerta).strip(),
                "data_hora_evento": row.data_hora_iso,
                
                "metrica_cpu_momento": cpu_val, 
                "metrica_ram_momento": ram_val,
                "metrica_disco_momento": disco_val, 
                "metrica_ping_momento": ping_val,
                "score_saude_momento": score_val,
            
                "limite_atencao_definido": row.limite_atencao,
                "limite_critico_definido": row.limite_critico,
                "valor_estouro_momento": row.valor_medido,
                "resumo_excesso_metrica": excesso_texto,
                
                "clima_temperatura": info_clima["temp"] if info_clima else None, 
                "clima_condicao": info_clima["cond"] if info_clima else "Erro na Consulta",
                "clima_umidade": info_clima["umidade"] if info_clima else None,
                "clima_vento": info_clima["velocidade_vento"] if info_clima else None,
                "clima_icone": info_clima["clima_icone"] if info_clima else None
            })

    if not incidentes_lista:
        print("[INCIDENTES] Sem ocorrências críticas pendentes de registro para esta execução.")
        return

    #CSV
    df_novos_incidentes = pd.DataFrame(incidentes_lista)
    caminho_s3 = caminho_para_tratado(df_tratado, tipo="incidentes")
    
    df_existente = extrair_csv_s3(bucket=bucket, key=caminho_s3)
    if df_existente is not None:
        df_final = pd.concat([df_existente, df_novos_incidentes], ignore_index=True)
        df_final.drop_duplicates(subset=["id_rbc", "componente_afetado", "data_hora_evento"], keep="last", inplace=True)
    else:
        df_final = df_novos_incidentes

    try:
        s3_client = boto3.client("s3", **cfg_s3())
        buffer = BytesIO()
        df_final.to_csv(buffer, index=False)
        s3_client.put_object(Bucket=bucket, Key=caminho_s3, Body=buffer.getvalue(), ContentType="text/csv")
        print(f"[INCIDENTES] Upload concluído: {len(df_novos_incidentes)} linhas salvas em s3://{bucket}/{caminho_s3}")
    except Exception as e:
        print(f"[INCIDENTES] Falha crítica de persistência no S3: {e}")
        
#=====================================================================================================================================        
    
def main():
    """
    Execução local para testes sem Lambda.
    Lê S3_BUCKET e S3_KEY do .env e grava localmente para inspeção.
    """
    bucket = os.getenv("S3_BUCKET")
    key    = os.getenv("S3_KEY")

def reading_json(row):
    """Converte uma linha do DataFrame em um dicionário de leitura."""
    return {
        "data_hora":                         row["data_hora_iso"].isoformat() if pd.notna(row.get("data_hora_iso")) else None,
        "rbc_status":                        native(row.get("rbc_status")),
        "gap_leitura_anterior_minutos":      native(row.get("gap_leitura_anterior_minutos")),
        "gap_leitura_anterior_segundos":     native(row.get("gap_leitura_anterior_segundos")),
        "idade_ultima_leitura_minutos":      native(row.get("idade_ultima_leitura_minutos")),
        "idade_ultima_leitura_segundos":     native(row.get("idade_ultima_leitura_segundos")),
        "criticidade":                       native(row.get("criticidade")),
        "score":                             native(row.get("score_saude")),
        "latencia_ping_ms":                  native(row.get("latencia_ping_ms")),
        "cpu": {
            "percentual_uso_cpu": native(row.get("percentual_uso_cpu")),
            "frequencia_atual":   native(row.get("frequencia_cpu_atual_mhz_human")),
        },
        "memoria": {
            "percentual_uso_ram": native(row.get("percentual_uso_ram")),
            "total":              native(row.get("memoria_total_bytes_human")),
            "disponivel":         native(row.get("memoria_disponivel_bytes_human")),
        },
        "disco": {
            "percentual_uso_disco": native(row.get("percentual_uso_disco")),
            "livre":                native(row.get("disco_livre_bytes_human")),
            "usado":                native(row.get("disco_usado_bytes_human")),
        },
        "rede": {
            "download_por_segundo": native(row.get("taxa_download_rede_bytes_por_segundo_human")),
            "upload_por_segundo":   native(row.get("taxa_upload_rede_bytes_por_segundo_human")),
        },
    }


def build_json(df: pd.DataFrame) -> dict:
    """
    Monta a estrutura hierárquica empresa → linha → rbc → últimas leituras
    e retorna um dicionário pronto para json.dumps.
    """
    empresas = []
    for (id_emp, nome_emp), edf in df.groupby(["id_empresa", "nome_empresa"], dropna=False):
        linhas = []
        for (id_lin, nome_lin), ldf in edf.groupby(["id_linha", "nome_linha"], dropna=False):
            rbcs = []
            for id_rbc, rdf in ldf.groupby("id_rbc", dropna=False):
                last = rdf.sort_values("data_hora_iso").tail(CFG["last_n"])
                lr   = last.iloc[-1]
                rbcs.append({
                    "id_rbc":                              native(id_rbc),
                    "nome_rbc":                            native(lr.get("nome_rbc")),
                    "endereco_mac":                        native(lr.get("endereco_mac")),
                    "status_atual":                        native(lr.get("rbc_status")),
                    "ultimo_gap_leitura_anterior_minutos": native(lr.get("gap_leitura_anterior_minutos")),
                    "ultimo_gap_leitura_anterior_segundos":native(lr.get("gap_leitura_anterior_segundos")),
                    "ultimas_leituras":                    [reading_json(row) for _, row in last.iterrows()],
                })
            rbcs.sort(key=lambda x: str(x.get("id_rbc") or ""))
            linhas.append({
                "id_linha":   native(id_lin),
                "nome_linha": native(nome_lin),
                "rbc":        rbcs,
            })
        linhas.sort(key=lambda x: str(x.get("id_linha") or x.get("nome_linha") or ""))
        empresas.append({
            "id_empresa":   native(id_emp),
            "nome_empresa": native(nome_emp),
            "linhas":       linhas,
        })
    empresas.sort(key=lambda x: str(x.get("id_empresa") or x.get("nome_empresa") or ""))
    return {"empresas": empresas}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def main(event):
    bucket = event.get("bucket")
    key    = event.get("key")

    df, df_alertas = extrair_e_enriquecer(bucket=bucket, key=key)

    if df is not None:
        # ── CSV diário e semanal ──────────────────────────────────────────
        df_semanal = atualizar_semanal(bucket=bucket, df=df)
        salvar_csv_trusted(bucket=bucket, df=df_semanal, tipo="semanal-tratados")
        salvar_csv_trusted(df=df, bucket=bucket, tipo="tratado")

        # ── JSON diário ───────────────────────────────────────────────────
        print("[JSON] Construindo JSON diário...")
        payload_diario = build_json(df)
        salvar_json_trusted(payload=payload_diario, df_ref=df, bucket=bucket, tipo="json")

        # ── JSON semanal ──────────────────────────────────────────────────
        print("[JSON] Construindo JSON semanal...")
        payload_semanal = build_json(df_semanal)
        salvar_json_trusted(payload=payload_semanal, df_ref=df_semanal, bucket=bucket, tipo="semanal-json")

    if df_alertas is not None and not df_alertas.empty:
        print("\n" + "=" * 60)
        print("Resumo — DataFrame tratado")
        print("=" * 60)
        print(f"Linhas            : {len(df):,}")
        print(f"Colunas           : {len(df.columns)}")
        print(f"Empresas          : {df['id_empresa'].nunique(dropna=False)}")
        print(f"Linhas de produção: {df['id_linha'].nunique(dropna=False)}")
        print(f"RBCs              : {df['id_rbc'].nunique(dropna=False)}")
        print(f"Alertas CRITICO   : {int(df['qte_alertas_critico'].sum())}")
        print(f"Alertas ATENÇÃO   : {int(df['qte_alertas_atencao'].sum())}")
        print(f"Servidores OFFLINE: {(df['rbc_status'] == 'OFFLINE').sum()}")
        print("=" * 60)
        
    if df_alertas is not None :
        print("\nRegistros de alerta gerados:")
        print(
            df_alertas[[
                "nome_rbc", "componente_afetado", "tipo_alerta",
                "valor_medido", "limite_atencao", "limite_critico",
            ]].to_string(index=False)
        )
        salvar_csv_trusted(df=df_alertas, bucket=bucket, tipo="alerta")
        salvar_csv_trusted(df=df_alertas, bucket=bucket, tipo="semanal-alertas")
        
        processar_e_salvar_incidentes_csv(df_tratado=df, df_alertas=df_alertas, bucket=bucket)

    return payload_diario if df is not None else {}


def lambda_handler(event, context):
    try:
        result = main(event or {})
        return {
            "statusCode": 200,
            "body": json.dumps(result, ensure_ascii=False, default=str),
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"ok": False, "erro": str(e)}, ensure_ascii=False),
        }