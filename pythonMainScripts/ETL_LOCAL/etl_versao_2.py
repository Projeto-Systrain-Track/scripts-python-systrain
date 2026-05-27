from __future__ import annotations

import os
from io import BytesIO
from typing import Any
import boto3
from botocore.exceptions import ClientError
import pandas as pd
from dotenv import load_dotenv
import json

# Carrega as variáveis do arquivo .env para o ambiente do Python.
# Exemplo esperado no .env:
# AWS_ACCESS_KEY_ID=...
# AWS_SECRET_ACCESS_KEY=...
# AWS_SESSION_TOKEN=...
# S3_BUCKET=...
load_dotenv()


def cfg_s3() -> dict:
    """
    Monta o dicionário de configuração usado pelo boto3 para acessar o S3.

    OBS:
    - As credenciais vêm das variáveis de ambiente.
    - Se alguma variável estiver vazia, o boto3 pode falhar ao tentar acessar o bucket.
    """
    print("[cfg_s3] Lendo credenciais AWS das variáveis de ambiente...")

    config = {
        "region_name": "us-east-1",
        "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
        "aws_session_token": os.getenv("AWS_SESSION_TOKEN"),
    }

    print("[cfg_s3] Região configurada:", config["region_name"])
    print("[cfg_s3] Access key encontrada?", bool(config["aws_access_key_id"]))
    print("[cfg_s3] Secret key encontrada?", bool(config["aws_secret_access_key"]))
    print("[cfg_s3] Session token encontrado?", bool(config["aws_session_token"]))

    return config


def limpar_mac(valor: Any) -> Any:
    """
    Padroniza o endereço MAC.

    O padrão usado no código é:
    - minúsculo
    - sem espaços no começo/fim
    - usando hífen no lugar de dois-pontos

    Exemplo:
    '0C:CC:47:E3:5F:90' vira '0c-cc-47-e3-5f-90'
    """
    if pd.isna(valor):
        return valor

    mac_limpo = str(valor).strip().lower().replace(":", "-")
    return mac_limpo


def buscar_e_juntar_arquivos_s3(bucket: str):
    """
    Busca arquivos dentro do bucket S3 e junta tudo em dois DataFrames:

    1. df_principal_tratado:
       Arquivos CSV semanais dentro de:
       trusted/<empresa>/semanal/

    2. df_principal_alertas:
       Arquivos CSV de alertas abertos do dia atual dentro de:
       trusted/<empresa>/<ano>/<mes>/<dia>/alertas/abertos/

    Retorna:
    - df_principal_tratado
    - df_principal_alertas
    """
    print("\n[buscar_e_juntar_arquivos_s3] Iniciando busca no S3...")
    print("[buscar_e_juntar_arquivos_s3] Bucket recebido:", bucket)

    s3 = boto3.client("s3", **cfg_s3())

    # Lista as "pastas" de empresas dentro de trusted/
    empresas = s3.list_objects_v2(Bucket=bucket, Prefix="trusted/", Delimiter="/")

    print("[buscar_e_juntar_arquivos_s3] Empresas encontradas:")
    for empresa in empresas.get("CommonPrefixes", []):
        print(" -", empresa.get("Prefix"))

    df_principal_tratado = []
    df_principal_alertas = []

    # Percorre cada empresa encontrada no S3
    for empresa in empresas.get("CommonPrefixes", []):
        prefix_empresa = empresa.get("Prefix")

        print("\n[buscar_e_juntar_arquivos_s3] Processando empresa/prefixo:", prefix_empresa)

        # Caminho dos arquivos semanais tratados
        caminho_semanal = f"{prefix_empresa}semanal/tratados/"
        print("[buscar_e_juntar_arquivos_s3] Caminho semanal:", caminho_semanal)

        arquivos_semanal = s3.list_objects_v2(
            Bucket=bucket,
            Prefix=caminho_semanal,
            Delimiter="/"
        )

        # Pega a data atual para montar o caminho dos alertas do dia
        hoje = pd.Timestamp.now()
        ano = hoje.year
        mes = hoje.month
        dia = hoje.day

        # Caminho dos alertas abertos do dia
        caminho_alertas = f"{prefix_empresa}semanal/alertas/"
        print("[buscar_e_juntar_arquivos_s3] Caminho alertas:", caminho_alertas)

        arquivos_alertas = s3.list_objects_v2(
            Bucket=bucket,
            Prefix=caminho_alertas,
            Delimiter="/"
        )

        print(
            "[buscar_e_juntar_arquivos_s3] Qtd arquivos semanais:",
            len(arquivos_semanal.get("Contents", []))
        )
        print(
            "[buscar_e_juntar_arquivos_s3] Qtd arquivos de alertas:",
            len(arquivos_alertas.get("Contents", []))
        )

        # Lê e adiciona cada arquivo semanal tratado
        for arquivo_tratado in arquivos_semanal.get("Contents", []):
            key_semanal = arquivo_tratado.get("Key")
            print("[buscar_e_juntar_arquivos_s3] Lendo CSV semanal:", key_semanal)

            df_tratado = extrair_csv_s3(bucket=bucket, key=key_semanal)

            if df_tratado is not None:
                print("[buscar_e_juntar_arquivos_s3] Linhas lidas no tratado:", len(df_tratado))
                df_principal_tratado.append(df_tratado)
            else:
                print("[buscar_e_juntar_arquivos_s3] AVISO: arquivo semanal não retornou DataFrame.")

        # Lê e adiciona cada arquivo de alerta aberto
        for arquivo_alerta in arquivos_alertas.get("Contents", []):
            key_alerta = arquivo_alerta.get("Key")
            print("[buscar_e_juntar_arquivos_s3] Lendo CSV de alerta:", key_alerta)

            df_alertas = extrair_csv_s3(bucket=bucket, key=key_alerta)

            if df_alertas is not None:
                print("[buscar_e_juntar_arquivos_s3] Linhas lidas em alertas:", len(df_alertas))
                df_principal_alertas.append(df_alertas)
            else:
                print("[buscar_e_juntar_arquivos_s3] AVISO: arquivo de alerta não retornou DataFrame.")

    # Evita erro no pd.concat quando não houver nenhum DataFrame na lista
    if df_principal_tratado:
        df_principal_tratado = pd.concat(df_principal_tratado, ignore_index=True)
    else:
        print("[buscar_e_juntar_arquivos_s3] AVISO: nenhum arquivo tratado encontrado.")
        df_principal_tratado = pd.DataFrame()

    if df_principal_alertas:
        df_principal_alertas = pd.concat(df_principal_alertas, ignore_index=True)
    else:
        print("[buscar_e_juntar_arquivos_s3] AVISO: nenhum arquivo de alerta encontrado.")
        df_principal_alertas = pd.DataFrame()

    print("\n[buscar_e_juntar_arquivos_s3] DataFrame tratado final:", df_principal_tratado.shape)
    print("[buscar_e_juntar_arquivos_s3] DataFrame alertas final:", df_principal_alertas.shape)

    return df_principal_tratado, df_principal_alertas

def arquivo_existe(bucket: str, key: str) -> bool:
    """
    Verifica se um arquivo existe no S3 usando head_object.

    Retorna:
    - True se existir
    - False se não existir
    - relança erro se for outro problema diferente de 404
    """
    print(f"[arquivo_existe] Verificando se existe: s3://{bucket}/{key}")

    s3 = boto3.client("s3", **cfg_s3())

    try:
        s3.head_object(Bucket=bucket, Key=key)
        print("[arquivo_existe] Arquivo encontrado.")
        return True

    except ClientError as e:
        codigo_erro = e.response["Error"]["Code"]
        print("[arquivo_existe] Erro recebido:", codigo_erro)

        if codigo_erro == "404":
            print("[arquivo_existe] Arquivo não existe.")
            return False

        # Se for outro erro, como permissão ou credencial, não escondemos o problema
        raise e


def extrair_csv_s3(bucket: str, key: str) -> pd.DataFrame | None:
    """
    Baixa um CSV do S3, transforma em DataFrame e faz tratamentos básicos:

    - Verifica se o arquivo existe.
    - Lê o conteúdo em bytes.
    - Converte para DataFrame com pandas.
    - Valida colunas obrigatórias.
    - Limpa endereço MAC.
    - Converte data_hora_iso para datetime.
    """
    print(f"\n[extrair_csv_s3] Preparando extração do CSV: s3://{bucket}/{key}")

    s3 = boto3.client("s3", **cfg_s3())

    verificar_existe = arquivo_existe(bucket=bucket, key=key)

    if not verificar_existe:
        print("[extrair_csv_s3] Arquivo não encontrado. Retornando None.")
        return None

    print("[extrair_csv_s3] Baixando arquivo do S3...")
    resposta = s3.get_object(Bucket=bucket, Key=key)

    conteudo = resposta["Body"].read()
    print(f"[extrair_csv_s3] Bytes recebidos: {len(conteudo):,}")

    df = pd.read_csv(BytesIO(conteudo))
    print("[extrair_csv_s3] DataFrame carregado com shape:", df.shape)
    print("[extrair_csv_s3] Colunas encontradas:", list(df.columns))

    # Colunas mínimas necessárias para esse script conseguir tratar o CSV
    obrigatorias = ["endereco_mac", "data_hora_iso"]

    # Lista quais colunas obrigatórias estão faltando
    ausentes = [c for c in obrigatorias if c not in df.columns]

    if ausentes:
        raise ValueError(f"Colunas obrigatórias ausentes no CSV: {ausentes}")

    # Normaliza o MAC
    df["endereco_mac"] = df["endereco_mac"].map(limpar_mac)

    # Converte a data ISO para datetime.
    # errors="coerce" transforma valores inválidos em NaT.
    df["data_hora_iso"] = pd.to_datetime(df["data_hora_iso"], errors="coerce")

    print(
        f"[extrair_csv_s3] {len(df):,} linhas | "
        f"{df['endereco_mac'].nunique()} MAC(s) único(s)."
    )

    qtd_datas_invalidas = df["data_hora_iso"].isna().sum()
    print("[extrair_csv_s3] Datas inválidas em data_hora_iso:", qtd_datas_invalidas)

    return df

def salvar_json_client(json_dashboard: dict, bucket: str, tipo: str):
    
    print("Iniciando processo de salvamento do CSV...")
    # Gera o caminho onde o arquivo será salvo no S3
    if tipo == "operacao":
        nome_arquivo = "dashboard_operacao.json"
    elif tipo == "incidentes":
        nome_arquivo = "dashboard_incidentes.json"
    elif tipo == "visao_geral":
        nome_arquivo = "dashboard_visao_geral.json"
    elif tipo == "detalhe_linha":
        nome_arquivo = "dashboard_detalhe_linha.json"
    else:
        print("Sem tipo de arquivo!")
        return
    
    caminho = f"client/{nome_arquivo}"

    print(f"Salvando JSON localmente como: {nome_arquivo}")
    
    # Salva o resultado final em JSON
    with open(f"{nome_arquivo}", "w", encoding="utf-8") as f:
        json.dump(json_dashboard, f, indent=2, ensure_ascii=False)

    print("JSON salvo localmente com sucesso!")
    print("Criando cliente S3...")
    s3 = boto3.client("s3", **cfg_s3())
    print(f"Enviando arquivo para bucket '{bucket}'...")
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

def dashboardOperacao(df_tratado: pd.DataFrame, df_alertas: pd.DataFrame):
    """
    Gera o objeto final do dashboard operacional.

    O cálculo principal é baseado no atraso entre envios dos dados:
    - calcula a diferença entre um envio e outro por empresa/linha/RBC
    - desconta o tempo esperado de coleta e a tolerância
    - transforma segundos excedentes em custo desperdiçado

    Também organiza o resultado por:
    - empresa
    - dia
    - linha
    - servidor/RBC
    - gráfico de custo ao longo do tempo
    """
    print("\n[dashboardOperacao] Iniciando montagem do dashboard...")
    print("[dashboardOperacao] Shape df_tratado recebido:", df_tratado.shape)
    print("[dashboardOperacao] Shape df_alertas recebido:", df_alertas.shape)

    # Segurança: se vier vazio, evita quebrar no restante do processamento
    if df_tratado.empty:
        print("[dashboardOperacao] ERRO: df_tratado está vazio. Não há dados para processar.")
        return

    # Converte a coluna de envio para datetime
    df_tratado["data_hora_envio"] = pd.to_datetime(
        df_tratado["data_hora_envio"],
        errors="coerce"
    )

    print(
        "[dashboardOperacao] Datas inválidas em data_hora_envio:",
        df_tratado["data_hora_envio"].isna().sum()
    )

    # Ordena os dados para o diff() calcular corretamente o intervalo entre registros
    df_tratado = df_tratado.sort_values(
        ["id_empresa", "id_linha", "id_rbc", "data_hora_envio"]
    )

    print("[dashboardOperacao] Dados ordenados por empresa, linha, RBC e data.")

    # Calcula a diferença, em segundos, entre uma coleta e a anterior
    df_tratado["diff_envio_segundos"] = (
        df_tratado.groupby(["id_empresa", "id_linha", "id_rbc"])["data_hora_envio"]
        .diff()
    ).dt.total_seconds()

    print("[dashboardOperacao] Coluna diff_envio_segundos criada.")
    print("[dashboardOperacao] Exemplo de diferenças:")
    print(df_tratado[["id_empresa", "id_linha", "id_rbc", "data_hora_envio", "diff_envio_segundos"]].head())

    # Regras de negócio para calcular desperdício
    TEMPO_COLETA = 5       # tempo esperado entre coletas, em segundos
    TOLERANCIA = 30        # tolerância extra antes de considerar atraso
    CUSTO_SEGUNDO = 31.25  # custo financeiro por segundo excedente

    print("[dashboardOperacao] TEMPO_COLETA:", TEMPO_COLETA)
    print("[dashboardOperacao] TOLERANCIA:", TOLERANCIA)
    print("[dashboardOperacao] CUSTO_SEGUNDO:", CUSTO_SEGUNDO)

    # Se o intervalo passou do tempo esperado + tolerância, calcula o excesso.
    # clip(lower=0) impede valores negativos.
    df_tratado["segundos_excesso"] = (
        df_tratado["diff_envio_segundos"] - TEMPO_COLETA - TOLERANCIA
    ).clip(lower=0)

    print("[dashboardOperacao] Coluna segundos_excesso criada.")

    # Conta quantos servidores/RBCs existem por empresa e linha
    df_tratado["qtd_servidores"] = df_tratado.groupby(
        ["id_empresa", "id_linha"]
    )["id_rbc"].transform("nunique")

    print("[dashboardOperacao] Coluna qtd_servidores criada.")

    # Divide o custo pelo número de servidores da linha
    df_tratado["custo_desperdicado"] = (
        df_tratado["segundos_excesso"] * CUSTO_SEGUNDO / df_tratado["qtd_servidores"]
    )

    print("[dashboardOperacao] Coluna custo_desperdicado criada.")
    print("[dashboardOperacao] Custo total calculado:", df_tratado["custo_desperdicado"].sum())

    # Salva uma cópia do DataFrame tratado para conferência
    print("[dashboardOperacao] Arquivo df_tratado.csv salvo.")

    resultado = {}
    

    # Agrupa por empresa para montar o JSON final
    for (id_empresa, nome_empresa), df_tratado_empresa in df_tratado.groupby(["id_empresa", "nome_empresa"]):
        print(f"\n[dashboardOperacao] Processando empresa {id_empresa} - {nome_empresa}")

        custo_empresa = df_tratado_empresa["custo_desperdicado"].sum()
        print("[dashboardOperacao] Custo total da empresa:", custo_empresa)
        
        resultado[id_empresa] = {
            "nome": nome_empresa,
            "data_hora": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
            "custo_total_semana": float(custo_empresa),
            "custo_por_dia": {},
            "linhas": {},
            "custo_ao_longo_tempo": {}
        }

        # Monta dados para gráfico de custo ao longo do tempo
        df_tratado_lote_custo = (
            df_tratado_empresa
            .groupby(["data_hora_envio"], as_index=False)
            .agg(
                custo_desperdicado=("custo_desperdicado", "sum"),
                objetivoFinanceiro=("objetivoFinanceiro", "mean")
            )
            .sort_values("data_hora_envio")
        )

        print(
            "[dashboardOperacao] Pontos no gráfico custo_ao_longo_tempo:",
            len(df_tratado_lote_custo)
        )

        resultado[id_empresa]["custo_ao_longo_tempo"] = [
            {
                "data": str(linha["data_hora_envio"]),
                "custo": float(linha["custo_desperdicado"]),
                "objetivoFinanceiro": str(linha["objetivoFinanceiro"])
            }
            for indice, linha in df_tratado_lote_custo.iterrows()
        ]

        # Custo por dia da empresa
        for dia, df_diario_empresa in df_tratado_empresa.groupby(df_tratado_empresa["data_hora_envio"].dt.date):
            data = str(dia)
            dia_semana = pd.Timestamp(dia).day_name()
            custo_dia = df_diario_empresa["custo_desperdicado"].sum()

            print(f"[dashboardOperacao] Empresa {id_empresa} | Dia {data} | Custo {custo_dia}")

            resultado[id_empresa]["custo_por_dia"][data] = {
                "dia_semana": str(dia_semana),
                "custo_dia": str(custo_dia)
            }

        # Agrupa por linha dentro da empresa
        for (id_linha, nome_linha), df_tratado_linha in df_tratado_empresa.groupby(["id_linha", "nome_linha"]):
            print(f"[dashboardOperacao] Processando linha {id_linha} - {nome_linha}")

            custo_linha = df_tratado_linha["custo_desperdicado"].sum()

            resultado[id_empresa]["linhas"][id_linha] = {
                "nome": nome_linha,
                "custo_total": float(custo_linha),
                "custo_por_dia": {},
                "servidores": {}
            }

            print("[dashboardOperacao] Custo total da linha:", custo_linha)

            # Custo por dia da linha
            for dia, df_diario_linha in df_tratado_linha.groupby(df_tratado_linha["data_hora_envio"].dt.date):
                data = str(dia)
                dia_semana = pd.Timestamp(dia).day_name()
                custo_dia = df_diario_linha["custo_desperdicado"].sum()

                print(f"[dashboardOperacao] Linha {id_linha} | Dia {data} | Custo {custo_dia}")

                resultado[id_empresa]["linhas"][id_linha]["custo_por_dia"][data] = {
                    "dia_semana": str(dia_semana),
                    "custo_dia": str(custo_dia)
                }
            # Agrupa por servidor/RBC dentro da linha
            for (id_rbc, nome_rbc), df_tratado_rbc in df_tratado_linha.groupby(["id_rbc", "nome_rbc"]):
                custo_rbc = df_tratado_rbc["custo_desperdicado"].sum()
                print(f"[dashboardOperacao] RBC {id_rbc} - {nome_rbc} | Custo {custo_rbc}")
                resultado[id_empresa]["linhas"][id_linha]["servidores"][id_rbc] = {
                    "nome": nome_rbc,
                    "custo_total": float(custo_rbc)
                }

    # Parte ainda não finalizada: transformação do DataFrame de alertas
    print("\n[dashboardOperacao] Iniciando leitura dos alertas...")

    if df_alertas.empty:
        print("[dashboardOperacao] Nenhum alerta encontrado para processar.")
    else:
        df_alertas["data_hora_iso"] = pd.to_datetime(df_alertas["data_hora_iso"], errors="coerce")
        for (id_empresa, nome_empresa), df_empresa_alertas in df_alertas.groupby(["id_empresa", "nome_empresa"]):
            print(f"[dashboardOperacao] Alertas da empresa {id_empresa} - {nome_empresa}")
            resultado[id_empresa]["alertas_por_motivo"] = (
                df_empresa_alertas["motivo_resumido"]
                .value_counts()
                .to_dict()
            )
            resultado[id_empresa]["alertas_por_dia"] = {}
            for dia, df_diario_alertas in df_empresa_alertas.groupby(df_empresa_alertas["data_hora_iso"].dt.date):
                data = str(dia)
                dia_semana = pd.Timestamp(dia).day_name()
                resultado[id_empresa]["alertas_por_dia"][data] = {
                    "qte_alertas": float(len(df_diario_alertas)),
                    "dia_semana": str(dia_semana),
                }
                
            for (id_linha, nome_linha), df_linha_alertas in df_empresa_alertas.groupby(["id_linha", "nome_linha"]):
                print(f"[dashboardOperacao] Processando linha {id_linha} - {nome_linha}")
                qte_alertas = len(df_linha_alertas)
                resultado[id_empresa]["linhas"][id_linha]["qte_alertas"] = int(qte_alertas)
                print("[dashboardOperacao] Quantidade de alertas da linha: ", qte_alertas)

                # Custo por dia da linha
                resultado[id_empresa]["linhas"][id_linha]["alertas_por_motivo"] = (
                    df_linha_alertas["motivo_resumido"]
                    .value_counts()
                    .to_dict()
                )
                
                resultado[id_empresa]["linhas"][id_linha]["qte_alertas_por_dia"] = {}
                for dia, df_diario_linha in df_linha_alertas.groupby(df_linha_alertas["data_hora_iso"].dt.date):
                    data = str(dia)
                    dia_semana = pd.Timestamp(dia).day_name()
                    qte_alertas = len(df_diario_linha)
                    
                    print(f"[dashboardOperacao] Linha: {id_linha} | Dia: {data} | Quantidade: {qte_alertas}")
                    

                    resultado[id_empresa]["linhas"][id_linha]["qte_alertas_por_dia"][data] = {
                        "dia_semana": str(dia_semana),
                        "qte_alertas": str(qte_alertas)
                    }
                    # Agrupa por servidor/RBC dentro da linha
                
                for (id_rbc, nome_rbc), df_rbc_alertas in df_linha_alertas.groupby(["id_rbc", "nome_rbc"]):
                    qte_alertas_rbc = len(df_rbc_alertas)
                    print(f"[dashboardOperacao] RBC {id_rbc} - {nome_rbc} | Alertas {qte_alertas_rbc}")
                    resultado[id_empresa]["linhas"][id_linha]["servidores"][id_rbc]["qte_alertas"] = float(qte_alertas_rbc)
                    resultado[id_empresa]["linhas"][id_linha]["servidores"][id_rbc]["alertas_por_motivo"] = (
                        df_rbc_alertas["motivo_resumido"]
                        .value_counts()
                        .to_dict()
                    )                                  
    bucket = os.getenv("S3_BUCKET")   
    salvar_json_client(json_dashboard=resultado, bucket=bucket, tipo="operacao")


    print("[dashboardOperacao] Arquivo saida.json salvo com sucesso.")
    print("[dashboardOperacao] Processo finalizado.")

def main():
    """
    Função principal do script.

    Fluxo:
    1. Lê o nome do bucket no .env.
    2. Busca os arquivos do S3.
    3. Junta os arquivos em DataFrames.
    4. Gera o dashboard operacional.
    """
    print("\n[main] Iniciando script...")

    bucket = os.getenv("S3_BUCKET")
    print("[main] Bucket carregado do .env:", bucket)

    if not bucket:
        raise ValueError("Variável de ambiente S3_BUCKET não encontrada.")

    df_principal_tratado, df_principal_alertas = buscar_e_juntar_arquivos_s3(bucket=bucket)

    print("[main] Chamando dashboardOperacao...")
    dashboardOperacao(
        df_tratado=df_principal_tratado,
        df_alertas=df_principal_alertas
    )

# Garante que o main só rode quando o arquivo for executado diretamente.
# Isso evita execução automática caso esse arquivo seja importado por outro script.
if __name__ == "__main__":
    main()
