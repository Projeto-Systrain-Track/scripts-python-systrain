from __future__ import annotations

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
            resultado[id_rbc_linha] = {
                "id_rbc": id_rbc_linha
            }

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
        # CrItico tem prioridade sobre atenção
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
            "percentual_uso_cpu": ("limite_cpu_alerta", "limite_cpu_critico"),
            "percentual_uso_ram": ("limite_ram_alerta", "limite_ram_critico"),
            "percentual_uso_disco": ("limite_disco_alerta", "limite_disco_critico"),
            "latencia_ping_ms": ("limite_latencia_alerta", "limite_latencia_critico")
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
            valor_captura = getattr(linha, nome_coluna)
            limite_atencao = getattr(linha, limites[0])
            limite_critico = getattr(linha, limites[1])
            status_alerta, limite_usado = classificar_alerta(valor_captura, limite_atencao, limite_critico)
            if status_alerta is None:
                continue
            else:
                motivo_descricao, motivo_resumo = retornar_motivo_alerta(nome_coluna=nome_coluna, status=status_alerta, limite=limite_usado)
                alertas_gerados.append(
                    {
                        "id_empresa": linha.id_empresa,
                        "nome_empresa": linha.nome_empresa,
                        "id_linha": linha.id_linha,
                        "nome_linha":   linha.nome_linha,
                        "id_rbc": linha.id_rbc,
                        "nome_rbc": linha.nome_rbc,
                        "endereco_mac": linha.endereco_mac,
                        "campo_alerta": nome_coluna,
                        "valor_medido": valor_captura,
                        "componente_afetado": limites[0].split("_")[1],
                        "tipo_alerta": status_alerta,
                        "motivo_alerta": motivo_descricao, 
                        "motivo_resumido": motivo_resumo, 
                        "data_hora_iso": linha.data_hora_iso,
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

                if nome_coluna == "percentual_uso_cpu":
                    qte_alertas_cpu += 1
                elif nome_coluna == "percentual_uso_ram":
                    qte_alertas_ram += 1
                elif nome_coluna == "percentual_uso_disco":
                    qte_alertas_disco += 1
                elif nome_coluna == "latencia_ping_ms":
                    qte_alertas_latencia += 1

    df["qte_alertas_critico"] = qte_alertas_criticos
    df["qte_alertas_atencao"] = qte_alertas_atencao
    df["qte_alertas_cpu"] = qte_alertas_cpu
    df["qte_alertas_ram"] = qte_alertas_ram
    df["qte_alertas_disco"] = qte_alertas_disco
    df["qte_alertas_latencia"] = qte_alertas_latencia
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
    
def caminho_para_tratado(df: pd.DataFrame, tipo: str):
    nome_empresa = df["nome_empresa"].dropna().unique()
    nome_empresa = nome_empresa[0]
    nome_empresa = nome_empresa.replace(" ", "_").lower()
    mac_adress = df["endereco_mac"].dropna().unique()
    mac_adress = mac_adress[0]
    data_atual = datetime.now()
    ano = data_atual.year
    mes = data_atual.month
    dia = data_atual.day
    
    if tipo == "alerta":
        caminho = f"trusted/{nome_empresa}/{ano}/{mes}/{dia}/alertas/abertos/{mac_adress}.csv"
    elif tipo == "tratado":
        caminho = f"trusted/{nome_empresa}/{ano}/{mes}/{dia}/tratados/{mac_adress}.csv"
    elif tipo == "semanal-tratados":
        caminho = f"trusted/{nome_empresa}/semanal/tratados/{mac_adress}.csv"
    elif tipo == "semanal-alertas":
        caminho = f"trusted/{nome_empresa}/semanal/alertas/{mac_adress}.csv"
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
    return None, None

def salvar_csv_trusted(df: pd.DataFrame, bucket: str, tipo: str):
    print("Iniciando processo de salvamento do CSV...")
    # Gera o caminho onde o arquivo será salvo no S3
    caminho = caminho_para_tratado(df=df, tipo=tipo)
    print(f"Caminho gerado para o arquivo: {caminho}")
    # Tenta buscar um arquivo já existente no S3
    print("Verificando se já existe arquivo no S3...")
    arquivo = extrair_csv_s3(bucket=bucket, key=caminho)
    # Caso já exista arquivo
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

    # Obtém os endereços MAC únicos
    print("Obtendo endereços MAC únicos para semanal...")
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
    try:
        s3.upload_file(
            Filename=nome_arquivo,
            Bucket=bucket,
            Key=caminho
        )
        print("Upload realizado com sucesso!")
        print("Removendo arquivo local temporário...")
        print("Arquivo local removido!")
        return True
    except Exception as e:
        print("Erro ao tentar subir o arquivo: ", e)
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
        print(f"[SEMANAL] Colunas do arquivo antigo: {list(arquivo_antigo.columns)}")

        print("[SEMANAL] Concatenando arquivo antigo + dataframe atual...")
        df_semanal = juntar_dataframes(df1=arquivo_antigo, df2=df)

        if df_semanal is None:
            raise ValueError("[SEMANAL] Erro: concatenação retornou None.")

        print(f"[SEMANAL] Linhas após concatenação: {len(df_semanal)}")

    else:
        print("[SEMANAL] Nenhum arquivo semanal antigo encontrado.")
        print("[SEMANAL] O semanal será criado apenas com o dataframe atual.")
        df_semanal = df.copy()

    print("[SEMANAL] Validando coluna de data...")

    if "data_hora_iso" not in df_semanal.columns:
        raise ValueError(
            "[SEMANAL] ERRO: coluna 'data_hora_iso' não existe no dataframe semanal."
        )

    print("[SEMANAL] Convertendo data_hora_iso para datetime...")
    df_semanal["data_hora_iso"] = pd.to_datetime(
        df_semanal["data_hora_iso"],
        errors="coerce"
    )

    datas_invalidas = df_semanal["data_hora_iso"].isna().sum()
    print(f"[SEMANAL] Datas inválidas após conversão: {datas_invalidas}")

    if datas_invalidas > 0:
        print("[SEMANAL] Removendo linhas com data inválida...")
        df_semanal = df_semanal.dropna(subset=["data_hora_iso"])
        print(f"[SEMANAL] Linhas após remover datas inválidas: {len(df_semanal)}")

    limite = pd.Timestamp.now() - pd.Timedelta(days=7)

    print(f"[SEMANAL] Data/hora atual: {pd.Timestamp.now()}")
    print(f"[SEMANAL] Limite mínimo para manter no semanal: {limite}")

    antes_filtro = len(df_semanal)

    print("[SEMANAL] Aplicando filtro dos últimos 7 dias...")
    df_semanal = df_semanal[df_semanal["data_hora_iso"] >= limite]

    depois_filtro = len(df_semanal)

    print(f"[SEMANAL] Linhas antes do filtro: {antes_filtro}")
    print(f"[SEMANAL] Linhas depois do filtro: {depois_filtro}")
    print(f"[SEMANAL] Linhas removidas por serem antigas: {antes_filtro - depois_filtro}")

    print("[SEMANAL] Ordenando por data_hora_iso...")
    df_semanal = df_semanal.sort_values("data_hora_iso")

    if not df_semanal.empty:
        print(f"[SEMANAL] Primeira data mantida: {df_semanal['data_hora_iso'].min()}")
        print(f"[SEMANAL] Última data mantida: {df_semanal['data_hora_iso'].max()}")
        print(f"[SEMANAL] MACs no semanal: {df_semanal['endereco_mac'].dropna().unique().tolist()}")
    else:
        print("[SEMANAL] AVISO: dataframe semanal ficou vazio após o filtro.")

    print("[SEMANAL] Atualização semanal finalizada com sucesso.")
    print("=" * 80 + "\n")
    return df_semanal


    
    
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
    if df is not None:
        df_semanal = atualizar_semanal(bucket=bucket, df=df)
        salvar_csv_trusted(bucket=bucket, df=df_semanal,tipo="semanal-tratados")
        salvar_csv_trusted(df=df, bucket=bucket, tipo="tratado")
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
        
    if df_alertas is not None and not df_alertas.empty:
        print("\nRegistros de alerta gerados:")
        print(df_alertas[["nome_rbc", "componente_afetado", "tipo_alerta", "valor_medido", "limite_atencao", "limite_critico"]].to_string(index=False))
        salvar_csv_trusted(df=df_alertas, bucket=bucket, tipo="alerta")
        salvar_csv_trusted(df=df_alertas, bucket=bucket, tipo="semanal-alertas")

if __name__ == "__main__":
    main()
