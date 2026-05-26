from __future__ import annotations
import ast, json, os
from pathlib import Path
from typing import Any, Optional
import boto3
import mysql.connector
import numpy as np
import pandas as pd

s3 = boto3.client("s3")

def b(name, default=False):
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "sim", "on", "s"}

def i(name, default):
    try: return int(os.getenv(name, str(default)))
    except Exception: return default

def f(name, default):
    try: return float(os.getenv(name, str(default)))
    except Exception: return default

CFG = {
    "last_n": i("LAST_N", 2),
    "indent": i("JSON_INDENT", 2),
    "offline_min": f("RBC_OFFLINE_GAP_MINUTES", 5),
    "max_proc": i("MAX_PROCESSES_PER_READING", 10),
    "skip_proc": b("SKIP_PROCESS_ALERTS", False),
    "proc_cpu": f("PROCESS_CPU_ALERT", 15),
    "proc_mem": f("PROCESS_MEMORY_PERCENT_ALERT", 10),
    "proc_rss": f("PROCESS_RSS_MB_ALERT", 200),
    "proc_threads": i("PROCESS_THREADS_ALERT", 75),
    "hi_prefix": tuple(x.strip().lower() for x in os.getenv("HIGH_PRIORITY_PROCESS_PREFIXES", "RBC_").split(",") if x.strip()),
    "hi_cpu": f("HIGH_PRIORITY_PROCESS_CPU_ALERT", 2),
    "hi_mem": f("HIGH_PRIORITY_PROCESS_MEMORY_PERCENT_ALERT", 5),
    "hi_rss": f("HIGH_PRIORITY_PROCESS_RSS_MB_ALERT", 20),
    "cpu_spike": f("PROCESS_CPU_SPIKE_ALERT", 15),
    "mem_spike": f("PROCESS_MEMORY_SPIKE_ALERT", 1),
    "rss_growth": f("PROCESS_RSS_GROWTH_MB_ALERT", 10),
    "keywords": tuple(x.strip().lower() for x in os.getenv("IMPORTANT_PROCESS_KEYWORDS", "java,node,python,postgres,mysql,nginx,docker,chrome,firefox").split(",") if x.strip()),
}

def db_cfg():
    return {
        "host": os.environ["DB_HOST"],
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
        "database": os.environ["DB_NAME"],
        "connection_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "5")),
    }

def native(v):
    if v is None: return None
    if isinstance(v, dict): return {k: native(x) for k, x in v.items()}
    if isinstance(v, list): return [native(x) for x in v]
    if isinstance(v, tuple): return [native(x) for x in v]
    if isinstance(v, np.integer): return int(v)
    if isinstance(v, np.floating):
        return None if np.isnan(v) else float(v)
    if isinstance(v, np.bool_): return bool(v)
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else v.isoformat()
    try:
        if pd.isna(v): return None
    except Exception:
        pass
    return v

def human_bytes(v):
    try:
        if v is None or pd.isna(v): return None
        v = float(v)
    except Exception:
        return None
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while v >= 1024 and idx < len(units) - 1:
        v /= 1024
        idx += 1
    return f"{v:.2f} {units[idx]}"

def human_mhz(v):
    try:
        if v is None or pd.isna(v): return None
        v = float(v)
    except Exception:
        return None
    return f"{v / 1000:.2f} GHz" if v >= 1000 else f"{v:.2f} MHz"

def normalize_mac(v):
    try:
        if pd.isna(v): return None
    except Exception:
        pass
    return str(v).strip().lower() if v is not None else None

def make_dict(**kwargs):
    return kwargs

def parse_processes(raw):
    if raw is None: return []
    if isinstance(raw, list): return [p for p in raw if isinstance(p, dict)]
    try:
        if pd.isna(raw): return []
    except Exception:
        pass
    raw = str(raw).strip()
    if not raw or raw == "[]": return []
    try:
        value = ast.literal_eval(raw)
    except Exception:
        funcs = {
            "transformarParaDict": make_dict, "pmem": make_dict, "pfullmem": make_dict,
            "pcputimes": make_dict, "pthread": make_dict, "popenfile": make_dict,
            "pconn": make_dict, "sconn": make_dict, "addr": make_dict,
        }
        try:
            value = eval(raw, {"__builtins__": {}}, funcs)
        except Exception:
            return []
    return [p for p in value if isinstance(p, dict)] if isinstance(value, list) else []

def clean_cmdline(cmd):
    if cmd is None: return None
    try:
        if pd.isna(cmd): return None
    except Exception:
        pass
    if isinstance(cmd, list):
        out = []
        for x in cmd:
            if x is None: continue
            try:
                if pd.isna(x): continue
            except Exception:
                pass
            if isinstance(x, str) and not x.strip(): continue
            out.append(native(x))
        return out or None
    if isinstance(cmd, str):
        return cmd.strip() or None
    return native(cmd)

def proc_text(p):
    name = str(p.get("name") or "").lower()
    exe = str(p.get("exe") or "").lower()
    cmd = clean_cmdline(p.get("cmdline"))
    cmd = " ".join(map(str, cmd)).lower() if isinstance(cmd, list) else str(cmd or "").lower()
    return f"{name} {exe} {cmd}".strip()

def proc_high(p):
    text, name = proc_text(p), str(p.get("name") or "").lower()
    return any(name.startswith(x) or x in text for x in CFG["hi_prefix"])

def proc_vals(p):
    mem = p.get("memory_info") or {}
    rss = float(mem.get("rss") or 0)
    return {
        "cpu_percent": float(p.get("cpu_percent") or 0),
        "memory_percent": float(p.get("memory_percent") or 0),
        "num_threads": int(p.get("num_threads") or 0),
        "rss_bytes": rss,
        "rss_mb": rss / 1024 / 1024,
    }

def proc_id(p):
    name = str(p.get("name") or "").lower()
    pid, created = p.get("pid"), p.get("create_time")
    if pid is not None and created is not None:
        return f"pid:{pid}|created:{created}|name:{name}"
    return f"name:{name}|txt:{proc_text(p)[:180]}"

def proc_reasons(p, prev=None):
    vals, high, text = proc_vals(p), proc_high(p), proc_text(p)
    cpu_l = CFG["hi_cpu"] if high else CFG["proc_cpu"]
    mem_l = CFG["hi_mem"] if high else CFG["proc_mem"]
    rss_l = CFG["hi_rss"] if high else CFG["proc_rss"]
    reasons = []
    if high: reasons.append("processo_rbc_alta_prioridade")
    if vals["cpu_percent"] >= cpu_l: reasons.append(f"cpu_percent >= {cpu_l}")
    if vals["memory_percent"] >= mem_l: reasons.append(f"memory_percent >= {mem_l}")
    if vals["rss_mb"] >= rss_l: reasons.append(f"rss_mb >= {rss_l}")
    if vals["num_threads"] >= CFG["proc_threads"]: reasons.append(f"num_threads >= {CFG['proc_threads']}")
    if prev:
        mult = 0.5 if high else 1
        dcpu = vals["cpu_percent"] - float(prev.get("cpu_percent") or 0)
        dmem = vals["memory_percent"] - float(prev.get("memory_percent") or 0)
        drss = vals["rss_mb"] - float(prev.get("rss_mb") or 0)
        if dcpu >= CFG["cpu_spike"] * mult: reasons.append(f"anomalia_cpu_delta >= {CFG['cpu_spike'] * mult}")
        if dmem >= CFG["mem_spike"] * mult: reasons.append(f"anomalia_memory_percent_delta >= {CFG['mem_spike'] * mult}")
        if drss >= CFG["rss_growth"] * mult: reasons.append(f"anomalia_rss_growth_mb >= {CFG['rss_growth'] * mult}")
    if any(k in text for k in CFG["keywords"]):
        if vals["cpu_percent"] >= CFG["proc_cpu"] / 2 or vals["memory_percent"] >= CFG["proc_mem"] / 2 or vals["rss_mb"] >= CFG["proc_rss"] / 2:
            reasons.append("processo_importante_com_consumo_relevante")
    return [] if high and reasons == ["processo_rbc_alta_prioridade"] else reasons

def proc_alert(p, reasons, prev=None):
    vals = proc_vals(p)
    prev = prev or {}
    dcpu = vals["cpu_percent"] - float(prev.get("cpu_percent") or 0) if prev else None
    dmem = vals["memory_percent"] - float(prev.get("memory_percent") or 0) if prev else None
    drss = vals["rss_mb"] - float(prev.get("rss_mb") or 0) if prev else None
    score = vals["cpu_percent"]/max(CFG["proc_cpu"],1) + vals["memory_percent"]/max(CFG["proc_mem"],.1) + vals["rss_mb"]/max(CFG["proc_rss"],1)
    if dcpu is not None: score += max(dcpu / max(CFG["cpu_spike"],1), 0) * 2
    if dmem is not None: score += max(dmem / max(CFG["mem_spike"],.1), 0) * 2
    if drss is not None: score += max(drss / max(CFG["rss_growth"],1), 0) * 2
    if proc_high(p): score *= 2
    mem = p.get("memory_info") or {}
    alerta = {
        "pid": native(p.get("pid")),
        "name": native(p.get("name")),
        "alta_prioridade": proc_high(p),
        "cpu_percent": native(p.get("cpu_percent")),
        "memory_percent": native(p.get("memory_percent")),
        "rss_mb": round(vals["rss_mb"], 2),
        "rss_human": human_bytes(vals["rss_bytes"]),
        "vms_human": human_bytes(mem.get("vms")),
        "num_threads": native(p.get("num_threads")),
        "anomalias": {
            "cpu_delta_desde_leitura_anterior": round(dcpu, 4) if dcpu is not None else None,
            "memory_percent_delta_desde_leitura_anterior": round(dmem, 4) if dmem is not None else None,
            "rss_growth_mb_desde_leitura_anterior": round(drss, 2) if drss is not None else None,
            "score_anomalia_processo": round(score, 4),
        },
        "motivos_alerta": reasons,
    }
    if b("PROCESS_ALERT_VERBOSE", False):
        alerta["cmdline"] = clean_cmdline(p.get("cmdline"))
        alerta["exe"] = native(p.get("exe"))
    return alerta

def list_csv_keys(bucket, prefix):
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item["Key"]
            name = Path(key).name.lower()
            if name.endswith(".csv") and "/trusted/" not in f"/{key.lower()}" and not name.startswith("maquinas_enriquecido"):
                keys.append(key)
    return sorted(keys)

def read_s3_csvs(bucket, keys):
    frames = []
    for key in keys:
        local = Path("/tmp") / Path(key).name
        s3.download_file(bucket, key, str(local))
        frame = pd.read_csv(local, low_memory=False)
        frame["arquivo_origem_csv"] = key
        frames.append(frame)
    if not frames:
        raise ValueError("Nenhum CSV encontrado para processar")
    return pd.concat(frames, ignore_index=True)

def prepare(df):
    missing = [c for c in ["endereco_mac", "data_hora_iso"] if c not in df.columns]
    if missing:
        raise ValueError(f"Colunas obrigatórias ausentes: {', '.join(missing)}")
    df = df.copy()
    df["endereco_mac"] = df["endereco_mac"].map(normalize_mac)
    df["data_hora_iso"] = pd.to_datetime(df["data_hora_iso"], errors="coerce")
    nums = [
        "percentual_uso_cpu", "memoria_total_bytes", "memoria_disponivel_bytes",
        "percentual_uso_ram", "percentual_uso_swap", "disco_total_bytes", "disco_usado_bytes",
        "disco_livre_bytes", "percentual_uso_disco", "frequencia_cpu_atual_mhz",
        "frequencia_cpu_minima_mhz", "frequencia_cpu_maxima_mhz",
        "taxa_leitura_disco_bytes_por_segundo", "taxa_escrita_disco_bytes_por_segundo",
        "latencia_ping_ms", "taxa_download_rede_bytes_por_segundo", "taxa_upload_rede_bytes_por_segundo",
    ]
    for col in nums:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce", downcast="float")
    df["processos_parsed"] = [[] for _ in range(len(df))] if CFG["skip_proc"] or "processos" not in df.columns else [parse_processes(x) for x in df["processos"]]
    return df

def map_db(macs):
    if not macs:
        return pd.DataFrame(columns=["endereco_mac", "id_empresa", "nome_empresa", "id_linha", "nome_linha", "id_rbc", "nome_rbc"])
    conn = mysql.connector.connect(**db_cfg())
    try:
        cur = conn.cursor(dictionary=True)
        marks = ", ".join(["%s"] * len(macs))
        cur.execute(f"""
            SELECT LOWER(TRIM(r.macAdress)) AS endereco_mac,
                   e.idEmpresa AS id_empresa, e.razaoSocial AS nome_empresa,
                   l.idLinha AS id_linha, CONCAT('Linha ', l.idLinha) AS nome_linha,
                   r.idRbc AS id_rbc, r.nomeServidor AS nome_rbc
            FROM rbc r
            JOIN linha l ON r.fkLinha = l.idLinha
            JOIN empresa e ON e.idEmpresa = l.fkEmpresa
            WHERE LOWER(TRIM(r.macAdress)) IN ({marks})
        """, macs)
        rows = cur.fetchall()
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["endereco_mac", "id_empresa", "nome_empresa", "id_linha", "nome_linha", "id_rbc", "nome_rbc"])
    finally:
        conn.close()

def map_fallback(df):
    m = pd.DataFrame({"endereco_mac": sorted(df["endereco_mac"].dropna().unique())})
    m["id_empresa"] = None; m["nome_empresa"] = "SEM_EMPRESA"
    m["id_linha"] = None; m["nome_linha"] = "SEM_LINHA"
    m["id_rbc"] = m["endereco_mac"]; m["nome_rbc"] = m["endereco_mac"]
    return m

def health(score):
    try: score = float(score)
    except Exception: return None
    if score > 85: return "CRITICO"
    if score > 70: return "ALTO"
    if score > 50: return "MODERADO"
    return "BAIXO"

def enrich(df, mapping):
    df = df.merge(mapping, on="endereco_mac", how="left")
    df["nome_empresa"] = df["nome_empresa"].fillna("SEM_EMPRESA")
    df["nome_linha"] = df["nome_linha"].fillna("SEM_LINHA")
    df["id_rbc"] = df["id_rbc"].fillna(df["endereco_mac"])
    df["nome_rbc"] = df["nome_rbc"].fillna(df["endereco_mac"])
    if "uso_memoria" not in df.columns:
        df["uso_memoria"] = df["percentual_uso_ram"] if "percentual_uso_ram" in df.columns else np.nan
    for col in ["percentual_uso_cpu", "uso_memoria", "percentual_uso_disco", "percentual_uso_swap"]:
        if col not in df.columns: df[col] = np.nan
    df["score"] = df["percentual_uso_cpu"].fillna(0)*.3 + df["uso_memoria"].fillna(0)*.3 + df["percentual_uso_disco"].fillna(0)*.2 + df["percentual_uso_swap"].fillna(0)*.2
    df["criticidade"] = [health(x) for x in df["score"]]
    for col in ["memoria_total_bytes", "memoria_disponivel_bytes", "disco_livre_bytes", "disco_usado_bytes", "taxa_leitura_disco_bytes_por_segundo", "taxa_escrita_disco_bytes_por_segundo", "taxa_download_rede_bytes_por_segundo", "taxa_upload_rede_bytes_por_segundo"]:
        if col in df.columns: df[f"{col}_human"] = [human_bytes(x) for x in df[col]]
    for col in ["frequencia_cpu_atual_mhz", "frequencia_cpu_minima_mhz", "frequencia_cpu_maxima_mhz"]:
        if col in df.columns: df[f"{col}_human"] = [human_mhz(x) for x in df[col]]
    return df

def inactivity(df):
    df = df.copy()
    df["data_hora_iso"] = pd.to_datetime(df["data_hora_iso"], errors="coerce").dt.tz_localize(None)
    now = pd.Timestamp.utcnow().tz_localize(None)
    df["horario_atual_etl"] = now
    df["idade_ultima_leitura_minutos"] = (now - df["data_hora_iso"]).dt.total_seconds() / 60
    df["idade_ultima_leitura_segundos"] = df["idade_ultima_leitura_minutos"] * 60
    df["rbc_status"] = np.where(df["idade_ultima_leitura_minutos"].fillna(float("inf")) >= CFG["offline_min"], "OFFLINE", "ONLINE")
    df["rbc_status_motivo"] = np.where(df["rbc_status"].eq("OFFLINE"), f"RBC sem leitura recente há {CFG['offline_min']}+ minutos", None)
    df["gap_leitura_anterior_minutos"] = df["idade_ultima_leitura_minutos"]
    df["gap_leitura_anterior_segundos"] = df["idade_ultima_leitura_segundos"]
    df["leitura_anterior_data_hora"] = None
    return df

def add_proc_alerts(df):
    if CFG["skip_proc"]:
        df["processos_alerta_priorizados"] = [[] for _ in range(len(df))]
        return df
    prev, alerts = {}, {idx: [] for idx in df.index}
    group_col = "id_rbc" if "id_rbc" in df.columns else "endereco_mac"
    for idx, row in df.sort_values([group_col, "data_hora_iso"]).iterrows():
        row_alerts = []
        for p in row.get("processos_parsed", []) or []:
            if not isinstance(p, dict): continue
            key = (row.get(group_col), proc_id(p))
            old = prev.get(key)
            reasons = proc_reasons(p, old)
            if reasons:
                row_alerts.append(proc_alert(p, reasons, old))
            prev[key] = proc_vals(p)
        row_alerts.sort(key=lambda x: (bool(x.get("alta_prioridade")), float((x.get("anomalias") or {}).get("score_anomalia_processo") or 0), float(x.get("cpu_percent") or 0), float(x.get("rss_mb") or 0)), reverse=True)
        alerts[idx] = row_alerts[:CFG["max_proc"]]
    df = df.copy()
    df["processos_alerta_priorizados"] = [alerts.get(idx, []) for idx in df.index]
    return df

def reading_json(row):
    procs = row.get("processos_alerta_priorizados") if isinstance(row.get("processos_alerta_priorizados"), list) else []
    return {
        "data_hora": row["data_hora_iso"].isoformat() if pd.notna(row.get("data_hora_iso")) else None,
        "rbc_status": native(row.get("rbc_status")),
        "gap_leitura_anterior_minutos": native(row.get("gap_leitura_anterior_minutos")),
        "gap_leitura_anterior_segundos": native(row.get("gap_leitura_anterior_segundos")),
        "idade_ultima_leitura_minutos": native(row.get("idade_ultima_leitura_minutos")),
        "idade_ultima_leitura_segundos": native(row.get("idade_ultima_leitura_segundos")),
        "rbc_status_motivo": native(row.get("rbc_status_motivo")),
        "criticidade": native(row.get("criticidade")),
        "score": native(row.get("score")),
        "latencia_ping_ms": native(row.get("latencia_ping_ms")),
        "cpu": {"percentual_uso_cpu": native(row.get("percentual_uso_cpu")), "frequencia_atual": native(row.get("frequencia_cpu_atual_mhz_human"))},
        "memoria": {"percentual_uso_ram": native(row.get("percentual_uso_ram")), "total": native(row.get("memoria_total_bytes_human")), "disponivel": native(row.get("memoria_disponivel_bytes_human"))},
        "disco": {"percentual_uso_disco": native(row.get("percentual_uso_disco")), "livre": native(row.get("disco_livre_bytes_human")), "usado": native(row.get("disco_usado_bytes_human"))},
        "swap": {"percentual_uso_swap": native(row.get("percentual_uso_swap"))},
        "rede": {"download_por_segundo": native(row.get("taxa_download_rede_bytes_por_segundo_human")), "upload_por_segundo": native(row.get("taxa_upload_rede_bytes_por_segundo_human"))},
        "processos_alerta": procs,
        "total_processos_alerta": len(procs),
    }

def build_json(df):
    empresas = []
    for (id_emp, nome_emp), edf in df.groupby(["id_empresa", "nome_empresa"], dropna=False):
        linhas = []
        for (id_lin, nome_lin), ldf in edf.groupby(["id_linha", "nome_linha"], dropna=False):
            rbcs = []
            for id_rbc, rdf in ldf.groupby("id_rbc", dropna=False):
                last = rdf.sort_values("data_hora_iso").tail(CFG["last_n"])
                lr = last.iloc[-1]
                rbcs.append({"id_rbc": native(id_rbc), "nome_rbc": native(lr.get("nome_rbc")), "endereco_mac": native(lr.get("endereco_mac")), "status_atual": native(lr.get("rbc_status")), "ultimo_gap_leitura_anterior_minutos": native(lr.get("gap_leitura_anterior_minutos")), "ultimo_gap_leitura_anterior_segundos": native(lr.get("gap_leitura_anterior_segundos")), "ultimas_leituras": [reading_json(row) for _, row in last.iterrows()]})
            rbcs.sort(key=lambda x: str(x.get("id_rbc") or ""))
            linhas.append({"id_linha": native(id_lin), "nome_linha": native(nome_lin), "rbc": rbcs})
        linhas.sort(key=lambda x: str(x.get("id_linha") or x.get("nome_linha") or ""))
        empresas.append({"id_empresa": native(id_emp), "nome_empresa": native(nome_emp), "linhas": linhas})
    empresas.sort(key=lambda x: str(x.get("id_empresa") or x.get("nome_empresa") or ""))
    return {"empresas": empresas}

def run(event):
    in_bucket = event.get("input_bucket") or os.environ["INPUT_BUCKET"]
    out_bucket = event.get("output_bucket") or os.getenv("OUTPUT_BUCKET") or in_bucket
    out_key = event.get("output_key") or os.getenv("OUTPUT_KEY", "trusted/empresas_linhas_rbc.json")
    keys = event.get("input_keys") or ([event["input_key"]] if event.get("input_key") else list_csv_keys(in_bucket, event.get("input_prefix") or os.getenv("INPUT_PREFIX", "raw/")))
    raw = prepare(read_s3_csvs(in_bucket, keys))
    mapping = map_fallback(raw) if b("NO_DB", False) else map_db(sorted(raw["endereco_mac"].dropna().unique().tolist()))
    df = add_proc_alerts(inactivity(enrich(raw, mapping)))
    data = build_json(df)
    s3.put_object(Bucket=out_bucket, Key=out_key, Body=json.dumps(native(data), ensure_ascii=False, indent=CFG["indent"]).encode("utf-8"), ContentType="application/json; charset=utf-8")
    return {"ok": True, "input_bucket": in_bucket, "input_keys": keys, "output_bucket": out_bucket, "output_key": out_key, "total_empresas": len(data["empresas"]), "total_maquinas": sum(len(l["rbc"]) for e in data["empresas"] for l in e["linhas"]), "leituras_offline": int((df["rbc_status"] == "OFFLINE").sum()), "json": data if event.get("return_json", False) else None}

def lambda_handler(event, context):
    try:
        return {"statusCode": 200, "body": json.dumps(run(event or {}), ensure_ascii=False, default=str)}
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"ok": False, "erro": str(e)}, ensure_ascii=False)}
