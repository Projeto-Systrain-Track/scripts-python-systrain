from __future__ import annotations

import os
from io import BytesIO
from typing import Any, Optional
from datetime import datetime
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

def calcular_score(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula um score de saúde (0–100) como média ponderada de CPU, RAM e Disco.
    Quanto maior o score, maior a pressão sobre o hardware.

    Usado no dashboard para ordenar servidores por criticidade
    e no gráfico de linha de saúde ao longo do dia.
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
    return pd.DataFrame(rows)



def buscar_limites_rbc(id_rbc) -> pd.DataFrame:
    """
    Busca no banco os limites de alerta e crItico de cada componente
    para os RBCs informados.

    Retorna um DataFrame com uma linha por id_rbc e uma coluna por limite.
    RBCs sem nenhum componente cadastrado não aparecem no resultado.
    """
    try: 
        id_formatado = float(id_rbc[0])
    except ValueError:
        print("Erro: id_rbc não é do tipo number")

    if not id_formatado:
        return pd.DataFrame()

    conn = conexao_mysql()
    try:
        cursor = conn.cursor(dictionary=True)
        sql = """
            SELECT
                rc.fkRbc     AS id_rbc,
                c.nome       AS codigo_componente,
                rc.definicao AS definicao
            FROM rbcComponente rc
            JOIN componente c ON c.idComponente = rc.fkComponente
            WHERE rc.fkRbc = %s
        """
        cursor.execute(sql, (id_formatado,))
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
    resultado: dict = {}
    for linha in resultado_select:
        id_rbc = linha["id_rbc"]
        codigo = linha["codigo_componente"]
        definicao_dicionario   = separar_definicao(linha["definicao"])

        if id_rbc not in resultado:
            resultado[id_rbc] = {
                "id_rbc": id_rbc
            }
        if codigo in mapa_colunas:
            coluna_atencao, coluna_critico = mapa_colunas[codigo]
            resultado[id_rbc][coluna_atencao] = definicao_dicionario.get("limite_alerta")
            resultado[id_rbc][coluna_critico] = definicao_dicionario.get("limite_critico")

        elif codigo == "PRS_STX":
            resultado[id_rbc]["limite_proc_sintaxe"] = definicao_dicionario.get("valor")

    return pd.DataFrame(resultado.values())

def classificar_alerta(valor: float, limite_atencao: Any, limite_critico: Any):
    try:
        
        v = float(valor)
        # CrItico tem prioridade sobre atenção
        if limite_critico is not None and v >= float(limite_critico):
            return "CRITICO", limite_critico
        if limite_atencao is not None and v >= float(limite_atencao):
            return "ATENÇÃO", limite_atencao
    except (TypeError, ValueError):
        pass
    return None, 0

def retornar_motivo_alerta(nome_coluna, status, limite):
    mensagem = ""
    if nome_coluna == "percentual_uso_cpu":
        mensagem = f"Percentual de CPU acima de {limite}% "
    elif nome_coluna == "percentual_uso_ram":
        mensagem = f"Percentual de RAM acima de {limite}% "
    elif nome_coluna == "percentual_uso_disco":
        mensagem = f"Percentual de DISCO acima de {limite}% "
    elif nome_coluna == "latencia_ping_ms":
        mensagem = f"Percentual de LATENCIA acima de {limite}ms "

    return mensagem
    
    


def aplicar_alertas(df: pd.DataFrame):
    colunas_limite = {
            "percentual_uso_cpu": ("limite_cpu_alerta", "limite_cpu_critico"),
            "percentual_uso_ram": ("limite_ram_alerta", "limite_ram_critico"),
            "percentual_uso_disco": ("limite_disco_alerta", "limite_disco_critico"),
            "latencia_ping_ms": ("limite_latencia_alerta", "limite_latencia_critico")
    }

    alertas_gerados = []
    qte_alertas_criticos = 0
    qte_alertas_atencao = 0
    for linha in df.itertuples():
        for nome_coluna, limites in colunas_limite.items():
            valor_captura = getattr(linha, nome_coluna)
            limite_atencao = getattr(linha, limites[0])
            limite_critico = getattr(linha, limites[1])
            status_alerta, limite_usado = classificar_alerta(valor_captura, limite_atencao, limite_critico)

            if status_alerta is None:
                continue
            else:
                alertas_gerados.append(
                    {
                        "id_empresa": linha.id_empresa,
                        "nome_empresa": linha.nome_empresa,
                        "id_linha": linha.id_linha,
                        "nome_linha":   linha.nome_linha,
                        "id_rbc": linha.id_rbc,
                        "nome_rbc": linha.nome_rbc,
                        "campo_alerta": nome_coluna,
                        "valor_medido": valor_captura,
                        "componente_afetado": limites[0].split("_")[1],
                        "tipo_alerta": status_alerta,
                        "motivo_alerta": retornar_motivo_alerta(nome_coluna=nome_coluna, status=status_alerta, limite=limite_usado), 
                        "data_captura": linha.data_hora_iso,
                        "limite_atencao": limite_atencao,
                        "limite_critico": limite_critico,
                        "url_jira": linha.url_jira,
                        "email_usuario_jira": linha.email_usuario_jira,
                        "token_usuario_jira": linha.token_usuario_jira
                    }
                )
                if status_alerta == "CRITICO":
                    qte_alertas_criticos+=1
                else:
                    qte_alertas_atencao+=1

    df["qte_alertas_critico"] = qte_alertas_criticos
    df["qte_alertas_atencao"] = qte_alertas_atencao
    alertas_gerados = pd.DataFrame(alertas_gerados)
    alertas_gerados.to_csv("alertas.csv", index=False)
    return df, alertas_gerados

def aplicar_status_online(df: pd.DataFrame) -> pd.DataFrame:
    """
    Marca o servidor como OFFLINE se a leitura mais recente do arquivo
    tiver mais de LIMITE_OFFLINE_MINUTOS em relação ao momento de execução da ETL.

    Isso detecta se o agente estava offline quando gerou o arquivo,
    ou se o arquivo chegou com atraso significativo.

    Colunas adicionadas:
      idade_ultima_leitura_minutos → minutos entre a leitura e agora
      rbc_status                   → 'ONLINE' ou 'OFFLINE'
      rbc_status_motivo            → texto explicando o motivo (só quando OFFLINE)
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
    
def caminho_para_tratado(df: pd.DataFrame):
    nome_empresa = df["nome_empresa"].dropna().unique()
    mac_adress = df["endereco_mac"].dropna().unique()
    mac_adress = mac_adress[0]
    nome_empresa = nome_empresa[0]
    data_atual = datetime.now()
    ano = data_atual.year
    mes = data_atual.month
    dia = data_atual.day
    
    caminho = f"trusted/{nome_empresa}/{ano}/{mes}/{dia}/{mac_adress}.csv"
    return caminho





def extrair_e_enriquecer(bucket: str, key: str) -> tuple[pd.DataFrame, pd.DataFrame]:

    df = extrair_csv_s3(bucket=bucket, key=key)
    mac_adress_servidor = df["endereco_mac"].dropna().unique().tolist()
    print(f"[banco] Buscando mapeamento para {len(mac_adress_servidor)} MAC(s)...")

    mapeamento = buscar_mapeamento_rbc(mac_adress_servidor)

    sem_cadastro = set(mac_adress_servidor) - set(mapeamento["endereco_mac"].tolist())
    if sem_cadastro:
        print(f"[banco] AVISO — MACs sem cadastro: {sem_cadastro}")

    df = df.merge(mapeamento, on="endereco_mac", how="left")

    df["nome_empresa"] = df["nome_empresa"].fillna("SEM_EMPRESA")
    df["nome_linha"] = df["nome_linha"].fillna("SEM_LINHA")
    df["id_rbc"] = df["id_rbc"].fillna(df["endereco_mac"])
    df["nome_rbc"] = df["nome_rbc"].fillna(df["endereco_mac"])

    print(f"[banco] Buscando limites para {df["id_rbc"].dropna().unique()} RBC(s)...")
    
    tabela_limites = buscar_limites_rbc(df["id_rbc"].dropna().unique())

    if tabela_limites.empty:
        # Sem limites cadastrados — colunas ficam NaN, alertas ficam None
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
            "limite_proc_sintaxe"
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
        # Remove colunas auxiliares do merge
        df.drop(columns=["_id_rbc_num", "id_rbc_lim"], errors="ignore", inplace=True)
        print(f"[banco] Limites aplicados para {tabela_limites['id_rbc'].nunique()} RBC(s).")

    #df = 
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

    df.drop(columns=["limite_cpu_alerta", "limite_cpu_critico", "limite_ram_alerta", "limite_ram_critico", "limite_disco_alerta", "limite_disco_critico", "limite_latencia_alerta", "limite_latencia_critico", "limite_proc_qtd_alerta", "limite_proc_qtd_critico", "limite_proc_sintaxe", "limite_proc_ram_alerta", "limite_proc_ram_critico", "limite_proc_ram_uso_alerta", "limite_proc_ram_uso_critico", "limite_proc_cpu_alerta", "limite_proc_cpu_critico", "processos","idade_ultima_leitura_minutos", "url_jira", "email_usuario_jira", "token_usuario_jira", "limite_proc_threads_alerta", "limite_proc_threads_critico"], inplace=True)

    return df, df_alertas
def salvar_csv_trusted(df: pd.DataFrame, bucket: str):
    print("Iniciando processo de salvamento do CSV...")

    # Gera o caminho onde o arquivo será salvo no S3
    caminho = caminho_para_tratado(df=df)
    print(f"Caminho gerado para o arquivo: {caminho}")

    # Tenta buscar um arquivo já existente no S3
    print("Verificando se já existe arquivo no S3...")
    arquivo = extrair_csv_s3(bucket=bucket, key=caminho)

    # Caso já exista arquivo
    if arquivo is not None:
        print("Arquivo existente encontrado!")
        try:
            print("Concatenando dataframe antigo com o novo...")

            # Junta os dados antigos com os novos
            df_novo = pd.concat([arquivo, df], ignore_index=True)

            # Atualiza o dataframe principal
            df = df_novo

            print("Concatenação realizada com sucesso!")
            print(f"Quantidade total de linhas após concatenação: {len(df)}")

        except Exception as e:
            print(f"Erro ao tentar concatenar os dataframes: {e}")

    else:
        print("Nenhum arquivo existente encontrado no S3.")

    # Obtém os endereços MAC únicos
    print("Obtendo endereços MAC únicos...")
    mac_adress = df["endereco_mac"].dropna().unique()
    mac_adress = mac_adress[0]

    print(f"MAC(s) encontrado(s): {mac_adress}")

    # Define nome do arquivo local
    nome_arquivo = f"{mac_adress}.csv"

    print(f"Salvando CSV localmente como: {nome_arquivo}")

    # Salva CSV local
    df.to_csv(nome_arquivo, index=False)

    print("CSV salvo localmente com sucesso!")

    # Cria cliente S3
    print("Criando cliente S3...")
    s3 = boto3.client("s3", **cfg_s3())

    print(f"Enviando arquivo para bucket '{bucket}'...")
    
    # Upload do arquivo para o S3
    s3.upload_file(
        Filename=nome_arquivo,
        Bucket=bucket,
        Key=caminho
    )

    print("Upload realizado com sucesso!")

    # Remove arquivo local
    print("Removendo arquivo local temporário...")
    os.remove(nome_arquivo)

    print("Arquivo local removido!")
    print("Processo finalizado com sucesso!")

    



    

def main():
    """
    Execução local para testes sem Lambda.
    Lê S3_BUCKET e S3_KEY do .env e grava localmente para inspeção.
    """
    bucket = os.getenv("S3_BUCKET")
    key    = os.getenv("S3_KEY")

    if not bucket or not key:
        raise ValueError("Defina S3_BUCKET e S3_KEY no .env para execução local.")

    df, df_alertas = extrair_e_enriquecer(bucket=bucket, key=key)


    print("\n" + "=" * 60)
    print("Resumo — DataFrame tratado")
    print("=" * 60)
    print(f"Linhas            : {len(df):,}")
    print(f"Colunas           : {len(df.columns)}")
    print(f"Empresas          : {df['id_empresa'].nunique(dropna=False)}")
    print(f"Linhas de produção: {df['id_linha'].nunique(dropna=False)}")
    print(f"RBCs              : {df['id_rbc'].nunique(dropna=False)}")
    print(f"AlertIs CRITICO   : {int(df['qte_alertas_critico'].sum())}")
    print(f"Alertas ATENÇÃO   : {int(df['qte_alertas_atencao'].sum())}")
    print(f"Servidores OFFLINE: {(df['rbc_status'] == 'OFFLINE').sum()}")
    print("=" * 60)

    if not df_alertas.empty:
        print("\nRegistros de alerta gerados:")
        print(df_alertas[["nome_rbc", "componente_afetado", "tipo_alerta", "valor_medido", "limite_atencao", "limite_critico"]].to_string(index=False))

    salvar_csv_trusted(df=df, bucket=bucket)


if __name__ == "__main__":
    main()
