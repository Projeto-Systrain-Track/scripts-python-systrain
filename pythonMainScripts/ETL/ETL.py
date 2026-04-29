from typing import Dict, List, Tuple
from dotenv import load_dotenv
from pathlib import Path
from io import BytesIO
import mysql.connector
import pandas as pd
import numpy as np
import boto3
import json
import ast
import os

load_dotenv()

NOME_BUCKET = os.getenv("S3_BUCKET_NAME")

s3 = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_DEFAULT_REGION"),
    aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
    endpoint_url=os.getenv("S3_ENDPOINT_URL") or None #adivinha.
)

MYSQL_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "0623",
    "database": "systraintrack",
}

PROCESS_GAP_MINUTES = 5

OUTPUT_DIR = "trusted"




def ensure_output_dirs(base_dir: str) -> Dict[str, Path]:
    base = Path(base_dir)
    dirs = {
        "base": base,
        "empresas": base / "empresas",
        "maquinas": base / "maquinas",
        "processos": base / "processos",
        "correlacoes": base / "correlacoes",
        "sessoes_processos": base / "sessoes_processos",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def normalize_mac(mac: str) -> str:
    if pd.isna(mac):
        return mac
    return str(mac).strip().lower()


def bytes_to_human(value) -> str:
    if pd.isna(value):
        return None
    value = float(value)
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    return f"{value:.2f} {units[idx]}"


def mhz_to_human(value) -> str:
    if pd.isna(value):
        return None
    value = float(value)
    if value >= 1000:
        return f"{value / 1000:.2f} GHz"
    return f"{value:.2f} MHz"


def parse_processes(raw) -> List[dict]:
    if pd.isna(raw):
        return []
    if isinstance(raw, list):
        return raw
    raw = str(raw).strip()
    if not raw:
        return []
    try:
        parsed = ast.literal_eval(raw)
        if isinstance(parsed, list):
            return parsed
        return []
    except Exception:
        return []


def classify_score(score: float) -> str:
    if pd.isna(score):
        return None
    if score > 85:
        return "CRITICO"
    elif score > 70:
        return "ALTO"
    elif score > 50:
        return "MODERADO"
    return "BAIXO"


def safe_filename(value) -> str:
    text = str(value)
    for ch in r'\/:*?"<>| ':
        text = text.replace(ch, "_")
    return text


def to_native(value):
    if value is None:
        return None

    if isinstance(value, dict):
        return {k: to_native(v) for k, v in value.items()}

    if isinstance(value, list):
        return [to_native(v) for v in value]

    if isinstance(value, tuple):
        return tuple(to_native(v) for v in value)

    if isinstance(value, np.integer):
        return int(value)

    if isinstance(value, np.floating):
        return float(value)

    if isinstance(value, np.bool_):
        return bool(value)

    if isinstance(value, np.ndarray):
        return value.tolist()

    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    return value


def construir_json_client(df: pd.DataFrame, last_n: int = 10) -> List[dict]:
    if df.empty:
        return []

    df = df.copy()

    if "data_hora_iso" in df.columns:
        df["data_hora_iso"] = pd.to_datetime(df["data_hora_iso"], errors="coerce")

    jsons_list = []

    for mac, df_m in df.groupby("endereco_mac", dropna=False):
        df_last = df_m.sort_values("data_hora_iso").tail(last_n)
        metricas = []
        for _, row in df_last.iterrows():
            processos = row.get("processos_parsed", [])

            processos_json = []
            for proc in processos:
                if not isinstance(proc, dict):
                    continue
                processos_json.append({
                    "pid": to_native(proc.get("pid")),
                    "name": to_native(proc.get("name")),
                    "username": to_native(proc.get("username")),
                    "status": to_native(proc.get("status")),
                    "cpu_percent": to_native(proc.get("cpu_percent")),
                    "memory_percent": to_native(proc.get("memory_percent")),
                    "num_threads": to_native(proc.get("num_threads")),
                    "cmdline": to_native(proc.get("cmdline")),
                    "exe": to_native(proc.get("exe")),
                    "create_time": (
                        pd.to_datetime(proc.get("create_time"), unit="s", errors="coerce").isoformat()
                        if proc.get("create_time") else None
                    ),
                    "memory_info": {
                        "rss": to_native((proc.get("memory_info") or {}).get("rss")),
                        "vms": to_native((proc.get("memory_info") or {}).get("vms")),
                    },
                    "cpu_times": {
                        "user": to_native((proc.get("cpu_times") or {}).get("user")),
                        "system": to_native((proc.get("cpu_times") or {}).get("system")),
                    }
                })
            
            metricas.append({
                "data_hora": row["data_hora_iso"].isoformat() if pd.notna(row.get("data_hora_iso")) else None,

                "criticidade": to_native(row.get("criticidade")),
                "score": to_native(row.get("score")),
                "latencia_ping_ms": to_native(row.get("latencia_ping_ms")),

                "memoria_total_bytes_human": to_native(row.get("memoria_total_bytes_human")),
                "memoria_disponivel_bytes_human": to_native(row.get("memoria_disponivel_bytes_human")),

                "disco_livre_bytes_human": to_native(row.get("disco_livre_bytes_human")),
                "disco_usado_bytes_human": to_native(row.get("disco_usado_bytes_human")),

                "taxa_leitura_disco_bytes_por_segundo_human": to_native(row.get("taxa_leitura_disco_bytes_por_segundo_human")),
                "taxa_escrita_disco_bytes_por_segundo_human": to_native(row.get("taxa_escrita_disco_bytes_por_segundo_human")),

                "taxa_download_rede_bytes_por_segundo_human": to_native(row.get("taxa_download_rede_bytes_por_segundo_human")),
                "taxa_upload_rede_bytes_por_segundo_human": to_native(row.get("taxa_upload_rede_bytes_por_segundo_human")),

                "frequencia_cpu_atual_mhz_human": to_native(row.get("frequencia_cpu_atual_mhz_human")),
                "frequencia_cpu_minima_mhz_human": to_native(row.get("frequencia_cpu_minima_mhz_human")),
                "frequencia_cpu_maxima_mhz_human": to_native(row.get("frequencia_cpu_maxima_mhz_human")),

                "percentual_uso_cpu": to_native(row.get("percentual_uso_cpu")),
                "percentual_uso_ram": to_native(row.get("percentual_uso_ram")),
                "percentual_uso_disco": to_native(row.get("percentual_uso_disco")),
                "percentual_uso_swap": to_native(row.get("percentual_uso_swap")),

                "processos": processos_json
            })        

        first_row = df_last.iloc[-1] if not df_last.empty else None

        jsons_list.append({
            "endereco_mac": to_native(mac),
            "id_empresa": to_native(first_row.get("id_empresa")) if first_row is not None else None,
            "nome_empresa": to_native(first_row.get("nome_empresa")) if first_row is not None else None,
            "id_maquina": to_native(first_row.get("id_maquina")) if first_row is not None else None,
            "ultimas_metricas": metricas
        })

    return jsons_list



def load_csv_from_s3(bucket: str, key: str) -> pd.DataFrame:
    obj = s3.get_object(Bucket=bucket, Key=key)
    df = pd.read_csv(BytesIO(obj["Body"].read()))

    if "endereco_mac" not in df.columns:
        raise ValueError("Coluna 'endereco_mac' não encontrada no CSV.")

    if "data_hora_iso" not in df.columns:
        raise ValueError("Coluna 'data_hora_iso' não encontrada no CSV.")

    df["endereco_mac"] = df["endereco_mac"].apply(normalize_mac)
    df["data_hora_iso"] = pd.to_datetime(df["data_hora_iso"], errors="coerce")

    if "processos" in df.columns:
        df["processos_parsed"] = df["processos"].apply(parse_processes)
    else:
        df["processos_parsed"] = [[] for _ in range(len(df))]

    return df




def upload_directory_to_s3(local_dir: str, bucket: str, s3_prefix: str):
    local_path = Path(local_dir)

    for file_path in local_path.rglob("*"):
        if file_path.is_file():
            relative_path = file_path.relative_to(local_path)
            s3_key = f"{s3_prefix}/{relative_path}".replace("\\", "/")

            s3.upload_file(
                Filename=str(file_path),
                Bucket=bucket,
                Key=s3_key
            )

            print(f"Uploaded: s3://{bucket}/{s3_key}")





        
def get_mysql_connection():
    return mysql.connector.connect(**MYSQL_CONFIG)


def fetch_rbc_mapping(unique_macs: List[str]) -> pd.DataFrame:
    """
    Busca idRbc e fkEmpresa na tabela rbc com base no macAdress.
    Schema baseado no SQL enviado pelo usuário. :contentReference[oaicite:1]{index=1}
    """
    if not unique_macs:
        return pd.DataFrame(columns=["endereco_mac", "id_empresa", "id_maquina"])

    conn = get_mysql_connection()
    try:
        cursor = conn.cursor(dictionary=True)

        placeholders = ", ".join(["%s"] * len(unique_macs))

        query = f"""
            SELECT
                LOWER(TRIM(r.macAdress)) AS endereco_mac,
                r.fkEmpresa AS id_empresa,
                r.idRbc AS id_maquina
            FROM rbc r
            WHERE LOWER(TRIM(r.macAdress)) IN ({placeholders})
        """

        cursor.execute(query, unique_macs)
        rows = cursor.fetchall()

        mapping_df = pd.DataFrame(rows)
        if mapping_df.empty:
            mapping_df = pd.DataFrame(columns=["endereco_mac", "id_empresa", "id_maquina"])

        return mapping_df

    finally:
        conn.close()


def fetch_rbc_mapping_with_empresa_nome(unique_macs: List[str]) -> pd.DataFrame:
    """
    Versão enriquecida:
    - pega MAC
    - pega id da empresa
    - pega id da máquina (RBC)
    - pega razão social da empresa
    """
    if not unique_macs:
        return pd.DataFrame(columns=[
            "endereco_mac",
            "id_empresa",
            "nome_empresa",
            "id_maquina"
        ])

    conn = get_mysql_connection()
    try:
        cursor = conn.cursor(dictionary=True)

        placeholders = ", ".join(["%s"] * len(unique_macs))

        query = f"""
            SELECT
                LOWER(TRIM(r.macAdress)) AS endereco_mac,
                    l.fkEmpresa AS id_empresa,
                    e.razaoSocial AS nome_empresa,
                    r.idRbc AS id_maquina
                    FROM rbc r
                    JOIN linha l
                        ON r.fkLinha = l.idLinha
                        JOIN empresa e 
                            ON e.idEmpresa = l.fkEmpresa
            WHERE LOWER(TRIM(r.macAdress)) IN ({placeholders})
        """

        cursor.execute(query, unique_macs)
        rows = cursor.fetchall()

        mapping_df = pd.DataFrame(rows)
        if mapping_df.empty:
            mapping_df = pd.DataFrame(columns=[
                "endereco_mac",
                "id_empresa",
                "nome_empresa",
                "id_maquina"
            ])

        return mapping_df

    finally:
        conn.close()


def fetch_single_mac_info(mac: str) -> pd.DataFrame:
    """
    Exemplo de SELECT individual por MAC.
    """
    conn = get_mysql_connection()
    try:
        cursor = conn.cursor(dictionary=True)

        query = """
            SELECT
                LOWER(TRIM(r.macAdress)) AS endereco_mac,
                r.idRbc AS id_maquina,
                r.fkEmpresa AS id_empresa,
                e.razaoSocial AS nome_empresa,
                r.nomeServidor,
                r.fkLinha
            FROM rbc r
            INNER JOIN empresa e
                ON e.idEmpresa = r.fkEmpresa
            WHERE LOWER(TRIM(r.macAdress)) = %s
        """

        cursor.execute(query, (normalize_mac(mac),))
        rows = cursor.fetchall()
        return pd.DataFrame(rows)

    finally:
        conn.close()


def enrich_machine_dataframe(df: pd.DataFrame, mapping_df: pd.DataFrame) -> pd.DataFrame:
    merged = df.merge(mapping_df, on="endereco_mac", how="left")

    # print(mapping_df)

    if "uso_memoria" not in merged.columns:
        if "percentual_uso_ram" in merged.columns:
            merged["uso_memoria"] = merged["percentual_uso_ram"]
        else:
            merged["uso_memoria"] = np.nan

    merged["score"] = (
        merged["percentual_uso_cpu"].fillna(0) * 0.3
        + merged["uso_memoria"].fillna(0) * 0.3
        + merged["percentual_uso_disco"].fillna(0) * 0.2
        + merged["percentual_uso_swap"].fillna(0) * 0.2
    )

    merged["criticidade"] = merged["score"].apply(classify_score)

    byte_cols = [
        "memoria_total_bytes",
        "memoria_disponivel_bytes",
        "swap_total_bytes",
        "swap_usado_bytes",
        "swap_livre_bytes",
        "swap_entrada_bytes",
        "swap_saida_bytes",
        "disco_total_bytes",
        "disco_usado_bytes",
        "disco_livre_bytes",
        "taxa_leitura_disco_bytes_por_segundo",
        "taxa_escrita_disco_bytes_por_segundo",
        "taxa_download_rede_bytes_por_segundo",
        "taxa_upload_rede_bytes_por_segundo",
    ]

    for col in byte_cols:
        if col in merged.columns:
            merged[f"{col}_human"] = merged[col].apply(bytes_to_human)

    mhz_cols = [
        "frequencia_cpu_atual_mhz",
        "frequencia_cpu_minima_mhz",
        "frequencia_cpu_maxima_mhz",
    ]

    for col in mhz_cols:
        if col in merged.columns:
            merged[f"{col}_human"] = merged[col].apply(mhz_to_human)

    return merged


def build_process_dataframe(df_maquinas: pd.DataFrame) -> pd.DataFrame:
    process_rows = []

    for _, row in df_maquinas.iterrows():
        processos = row.get("processos_parsed", [])
        if not processos:
            continue

        for proc in processos:
            memory_info = proc.get("memory_info", {}) or {}
            cpu_times = proc.get("cpu_times", {}) or {}

            process_rows.append({
                "data_hora_iso": row["data_hora_iso"],
                "endereco_mac": row["endereco_mac"],
                "id_empresa": row.get("id_empresa"),
                "nome_empresa": row.get("nome_empresa"),
                "id_maquina": row.get("id_maquina"),
                "nome_usuario_maquina": row.get("nome_usuario"),

                "pid": proc.get("pid"),
                "pnome": proc.get("name"),
                "username_processo": proc.get("username"),
                "status": proc.get("status"),
                "create_time_epoch": proc.get("create_time"),
                "create_time": pd.to_datetime(proc.get("create_time"), unit="s", errors="coerce"),
                "cpu_percent": proc.get("cpu_percent"),
                "memory_percent": proc.get("memory_percent"),
                "rss_bytes": memory_info.get("rss"),
                "vms_bytes": memory_info.get("vms"),
                "num_threads": proc.get("num_threads"),
                "cmdline": " ".join(proc.get("cmdline", [])) if isinstance(proc.get("cmdline"), list) else proc.get("cmdline"),
                "exe": proc.get("exe"),
                "cpu_user_time": cpu_times.get("user"),
                "cpu_system_time": cpu_times.get("system"),
            })

    df_proc = pd.DataFrame(process_rows)

    if not df_proc.empty:
        df_proc["rss_human"] = df_proc["rss_bytes"].apply(bytes_to_human)
        df_proc["vms_human"] = df_proc["vms_bytes"].apply(bytes_to_human)

    return df_proc


def build_process_sessions(df_proc: pd.DataFrame, gap_minutes: int = 5) -> pd.DataFrame:
    if df_proc.empty:
        return pd.DataFrame()

    df = df_proc.copy()
    df = df.sort_values(["id_maquina", "pnome", "pid", "data_hora_iso"]).reset_index(drop=True)

    group_keys = ["id_maquina", "endereco_mac", "pid", "pnome"]
    df["prev_time"] = df.groupby(group_keys)["data_hora_iso"].shift(1)
    df["delta_min"] = (df["data_hora_iso"] - df["prev_time"]).dt.total_seconds() / 60.0
    df["nova_sessao"] = df["delta_min"].isna() | (df["delta_min"] > gap_minutes)
    df["session_seq"] = df.groupby(group_keys)["nova_sessao"].cumsum()

    session_df = (
        df.groupby(group_keys + ["session_seq"], dropna=False)
        .agg(
            id_empresa=("id_empresa", "first"),
            nome_empresa=("nome_empresa", "first"),
            inicio=("data_hora_iso", "min"),
            fim=("data_hora_iso", "max"),
            observacoes=("data_hora_iso", "count"),
            status_mais_recente=("status", "last"),
            cpu_percent_medio=("cpu_percent", "mean"),
            cpu_percent_max=("cpu_percent", "max"),
            memory_percent_medio=("memory_percent", "mean"),
            memory_percent_max=("memory_percent", "max"),
            rss_max_bytes=("rss_bytes", "max"),
            vms_max_bytes=("vms_bytes", "max"),
            num_threads_max=("num_threads", "max"),
            username_processo=("username_processo", "last"),
            exe=("exe", "last"),
            cmdline=("cmdline", "last"),
            create_time=("create_time", "first"),
        )
        .reset_index()
    )

    session_df["duracao_segundos"] = (session_df["fim"] - session_df["inicio"]).dt.total_seconds()
    session_df["rss_max_human"] = session_df["rss_max_bytes"].apply(bytes_to_human)
    session_df["vms_max_human"] = session_df["vms_max_bytes"].apply(bytes_to_human)

    return session_df


def calculate_correlations(df_maquinas: pd.DataFrame) -> pd.DataFrame:
    numeric_cols = [
        "percentual_uso_cpu",
        "uso_memoria",
        "percentual_uso_disco",
        "percentual_uso_swap",
        "latencia_ping_ms",
        "score",
        "frequencia_cpu_atual_mhz",
        "percentual_uso_ram",
    ]

    existing = [c for c in numeric_cols if c in df_maquinas.columns]
    if len(existing) < 2:
        return pd.DataFrame()

    corr = df_maquinas[existing].corr(numeric_only=True)
    corr = corr.reset_index().rename(columns={"index": "variavel"})
    return corr


def split_by_company(df_maquinas: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    result = {}
    for empresa_id, df_emp in df_maquinas.groupby("id_empresa", dropna=False):
        key = "SEM_EMPRESA" if pd.isna(empresa_id) else str(empresa_id)
        result[key] = df_emp.sort_values(["data_hora_iso", "id_maquina"])
    return result


def split_by_machine(df_maquinas: pd.DataFrame) -> Dict[Tuple, pd.DataFrame]:
    result = {}
    for keys, df_m in df_maquinas.groupby(["id_empresa", "id_maquina", "endereco_mac"], dropna=False):
        result[keys] = df_m.sort_values("data_hora_iso")

  
    return result


def split_processes_by_machine(df_proc: pd.DataFrame) -> Dict[Tuple, pd.DataFrame]:
    result = {}
    if df_proc.empty:
        return result

    for keys, df_p in df_proc.groupby(["id_empresa", "id_maquina", "endereco_mac"], dropna=False):
        result[keys] = df_p.sort_values(["data_hora_iso", "pid", "pnome"])
    return result


def export_all(    dirs: Dict[str, Path],    df_maquinas: pd.DataFrame,    df_proc: pd.DataFrame,    df_sessions: pd.DataFrame,    corr_df: pd.DataFrame,    empresas: Dict[str, pd.DataFrame], maquinas: Dict[Tuple, pd.DataFrame],   processos_por_maquina: Dict[Tuple, pd.DataFrame],) -> None:

    df_maquinas.to_csv(dirs["base"] / "maquinas_enriquecido.csv", index=False)
    df_proc.to_csv(dirs["base"] / "processos_explodidos.csv", index=False)
    df_sessions.to_csv(dirs["sessoes_processos"] / "sessoes_processos.csv", index=False)

    if not corr_df.empty:
        corr_df.to_csv(dirs["correlacoes"] / "correlacao_maquinas.csv", index=False)

    for empresa_id, df_emp in empresas.items():
        df_emp.to_csv(
            dirs["empresas"] / f"empresa_{safe_filename(empresa_id)}.csv",
            index=False
        )

    for (empresa_id, id_maquina, mac), df_m in maquinas.items():
        nome = (
            f"empresa_{safe_filename(empresa_id)}"
            f"__maquina_{safe_filename(id_maquina)}"
            f"__mac_{safe_filename(mac)}.csv"
        )
        df_m.to_csv(dirs["maquinas"] / nome, index=False)

    for (empresa_id, id_maquina, mac), df_p in processos_por_maquina.items():
        nome = (
            f"processos__empresa_{safe_filename(empresa_id)}"
            f"__maquina_{safe_filename(id_maquina)}"
            f"__mac_{safe_filename(mac)}.csv"
        )
        df_p.to_csv(dirs["processos"] / nome, index=False)


def main():
    dirs = ensure_output_dirs(OUTPUT_DIR)

    INPUT_S3_KEY = os.getenv("S3_INPUT_KEY", "df.csv")
    OUTPUT_S3_PREFIX = os.getenv("S3_OUTPUT_PREFIX", "trusted")

    df = load_csv_from_s3(NOME_BUCKET, INPUT_S3_KEY)

    unique_macs = sorted(df["endereco_mac"].dropna().unique().tolist())

    mapping_df = fetch_rbc_mapping_with_empresa_nome(unique_macs)

    df_maquinas = enrich_machine_dataframe(df, mapping_df)

    json_client = construir_json_client(df_maquinas, last_n=10)

    json_dir = dirs["base"] / "json_client"
    json_dir.mkdir(parents=True, exist_ok=True)

    for index, item in enumerate(json_client):
        filename = json_dir / f"element_{index}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(item, f, indent=4, ensure_ascii=False)

        print(f"Saved: {filename}")

    df_proc = build_process_dataframe(df_maquinas)
    df_sessions = build_process_sessions(df_proc, gap_minutes=PROCESS_GAP_MINUTES)
    corr_df = calculate_correlations(df_maquinas)

    empresas = split_by_company(df_maquinas)
    maquinas = split_by_machine(df_maquinas)
    processos_por_maquina = split_processes_by_machine(df_proc)

    export_all(
        dirs=dirs,
        df_maquinas=df_maquinas,
        df_proc=df_proc,
        df_sessions=df_sessions,
        corr_df=corr_df,
        empresas=empresas,
        maquinas=maquinas,
        processos_por_maquina=processos_por_maquina,
    )

    upload_directory_to_s3(
        local_dir=OUTPUT_DIR,
        bucket=NOME_BUCKET,
        s3_prefix=OUTPUT_S3_PREFIX
    )

    print("Processamento finalizado e enviado para o S3.")




if __name__ == "__main__":
    main()