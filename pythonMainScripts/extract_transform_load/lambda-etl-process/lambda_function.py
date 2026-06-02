from __future__ import annotations

import ast
import base64
import json
import os
import re
from datetime import datetime, time
from io import BytesIO, StringIO
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote_plus

import boto3
import numpy as np
import pandas as pd


s3 = boto3.client("s3")


def env_bool(nome: str, padrao: bool = False) -> bool:
    valor = os.getenv(nome)
    if valor is None:
        return padrao
    return valor.strip().lower() in {"1", "true", "yes", "sim", "on", "s"}


def env_int(nome: str, padrao: int) -> int:
    try:
        return int(os.getenv(nome, str(padrao)))
    except Exception:
        return padrao


def env_float(nome: str, padrao: float) -> float:
    try:
        return float(os.getenv(nome, str(padrao)))
    except Exception:
        return padrao


CONFIG = {
    "input_bucket": os.getenv("INPUT_BUCKET") or os.getenv("S3_BUCKET_NAME"),
    "input_prefix": os.getenv("INPUT_PREFIX", "raw/"),
    "output_bucket": os.getenv("OUTPUT_BUCKET"),
    "output_key": os.getenv("OUTPUT_KEY", "trusted/empresas_linhas_rbc.json"),

    "last_n": env_int("LAST_N", 10),
    "json_indent": env_int("JSON_INDENT", 2),
    "no_db": env_bool("NO_DB", False),
    "db_required": env_bool("DB_REQUIRED", False),

    "rbc_offline_gap_minutes": env_float("RBC_OFFLINE_GAP_MINUTES", 5),
    "skip_process_alerts": env_bool("SKIP_PROCESS_ALERTS", False),
    "max_processes_per_reading": env_int("MAX_PROCESSES_PER_READING", 10),

    # Protege a Lambda contra tentar carregar todo o histórico do bucket.
    # Com o coletor novo, cada arquivo costuma ter 1 minuto de dados.
    # 180 por MAC dá uma janela boa para dashboard e anomalias curtas.
    # Passe latest_files_per_mac=0 no payload para processar tudo do prefixo.
    "latest_files_per_mac": env_int("LATEST_FILES_PER_MAC", 180),
    "max_csvs_per_run": env_int("MAX_CSVS_PER_RUN", 5000),

    "process_cpu_alert": env_float("PROCESS_CPU_ALERT", 15),
    "process_memory_percent_alert": env_float("PROCESS_MEMORY_PERCENT_ALERT", 10),
    "process_rss_mb_alert": env_float("PROCESS_RSS_MB_ALERT", 200),
    "process_threads_alert": env_int("PROCESS_THREADS_ALERT", 75),

    "high_priority_prefixes": tuple(
        item.strip().lower()
        for item in os.getenv("HIGH_PRIORITY_PROCESS_PREFIXES", "RBC_").split(",")
        if item.strip()
    ),
    "high_priority_process_cpu_alert": env_float("HIGH_PRIORITY_PROCESS_CPU_ALERT", 2),
    "high_priority_process_memory_percent_alert": env_float("HIGH_PRIORITY_PROCESS_MEMORY_PERCENT_ALERT", 5),
    "high_priority_process_rss_mb_alert": env_float("HIGH_PRIORITY_PROCESS_RSS_MB_ALERT", 20),

    "process_cpu_spike_alert": env_float("PROCESS_CPU_SPIKE_ALERT", 15),
    "process_memory_spike_alert": env_float("PROCESS_MEMORY_SPIKE_ALERT", 1),
    "process_rss_growth_mb_alert": env_float("PROCESS_RSS_GROWTH_MB_ALERT", 10),

    "important_process_keywords": tuple(
        item.strip().lower()
        for item in os.getenv(
            "IMPORTANT_PROCESS_KEYWORDS",
            "java,node,python,postgres,mysql,sqlserver,mongodb,redis,nginx,apache,httpd,docker,containerd,chrome,firefox,edge,chromium",
        ).split(",")
        if item.strip()
    ),
}


COLUNAS_MAPEAMENTO = ["endereco_mac", "id_empresa", "nome_empresa", "id_linha", "nome_linha", "id_rbc", "nome_rbc"]

COLUNAS_NUMERICAS = [
    "percentual_uso_cpu",
    "memoria_total_bytes",
    "memoria_disponivel_bytes",
    "percentual_uso_ram",
    "uso_memoria",
    "swap_total_bytes",
    "swap_usado_bytes",
    "swap_livre_bytes",
    "swap_entrada_bytes",
    "swap_saida_bytes",
    "percentual_uso_swap",
    "disco_total_bytes",
    "disco_usado_bytes",
    "disco_livre_bytes",
    "percentual_uso_disco",
    "frequencia_cpu_atual_mhz",
    "frequencia_cpu_minima_mhz",
    "frequencia_cpu_maxima_mhz",
    "taxa_leitura_disco_bytes_por_segundo",
    "taxa_escrita_disco_bytes_por_segundo",
    "latencia_ping_ms",
    "taxa_download_rede_bytes_por_segundo",
    "taxa_upload_rede_bytes_por_segundo",
]

ALIASES_COLUNAS = {
    "mac": "endereco_mac",
    "mac_address": "endereco_mac",
    "macadress": "endereco_mac",
    "mac_address_rbc": "endereco_mac",
    "timestamp": "data_hora_iso",
    "data_hora": "data_hora_iso",
    "datetime": "data_hora_iso",
    "created_at": "data_hora_iso",
    "cpu_percent": "percentual_uso_cpu",
    "percentual_cpu": "percentual_uso_cpu",
    "ram_percent": "percentual_uso_ram",
    "memory_percent": "percentual_uso_ram",
    "percentual_memoria": "percentual_uso_ram",
    "disk_percent": "percentual_uso_disco",
    "disco_percent": "percentual_uso_disco",
    "ping_ms": "latencia_ping_ms",
    "latencia_ms": "latencia_ping_ms",
}


def resposta(status_code: int, corpo: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "OPTIONS,POST,GET",
        },
        "body": json.dumps(corpo, ensure_ascii=False, default=str),
    }


def normalizar_json(valor: Any) -> Any:
    if valor is None:
        return None
    if isinstance(valor, dict):
        return {str(chave): normalizar_json(valor_interno) for chave, valor_interno in valor.items()}
    if isinstance(valor, list):
        return [normalizar_json(valor_interno) for valor_interno in valor]
    if isinstance(valor, tuple):
        return [normalizar_json(valor_interno) for valor_interno in valor]
    if isinstance(valor, np.integer):
        return int(valor)
    if isinstance(valor, np.floating):
        if np.isnan(valor):
            return None
        return float(valor)
    if isinstance(valor, np.bool_):
        return bool(valor)
    if isinstance(valor, pd.Timestamp):
        if pd.isna(valor):
            return None
        return valor.isoformat()
    try:
        if pd.isna(valor):
            return None
    except Exception:
        pass
    return valor


def converter_bytes(valor: Any) -> Optional[str]:
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
        valor = float(valor)
    except Exception:
        return None

    unidades = ["B", "KB", "MB", "GB", "TB", "PB"]
    indice = 0
    while abs(valor) >= 1024 and indice < len(unidades) - 1:
        valor /= 1024
        indice += 1
    return f"{valor:.2f} {unidades[indice]}"


def converter_mhz(valor: Any) -> Optional[str]:
    try:
        if valor is None or pd.isna(valor):
            return None
        valor = float(valor)
    except Exception:
        return None
    if valor >= 1000:
        return f"{valor / 1000:.2f} GHz"
    return f"{valor:.2f} MHz"


def limpar_mac(valor: Any) -> Optional[str]:
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except Exception:
        pass

    texto = str(valor).strip().lower()
    if not texto:
        return None

    texto = texto.replace(":", "-")
    texto = re.sub(r"[^0-9a-f-]", "", texto)

    if len(texto) == 12 and "-" not in texto:
        texto = "-".join(texto[i:i + 2] for i in range(0, 12, 2))

    return texto or None


def transformar_para_dict(**argumentos_nomeados):
    return argumentos_nomeados


def separar_processos(texto_bruto: Any) -> List[dict]:
    if texto_bruto is None:
        return []
    if isinstance(texto_bruto, list):
        return [item for item in texto_bruto if isinstance(item, dict)]

    try:
        if pd.isna(texto_bruto):
            return []
    except Exception:
        pass

    texto_bruto = str(texto_bruto).strip()
    if not texto_bruto or texto_bruto == "[]":
        return []

    try:
        processos = ast.literal_eval(texto_bruto)
    except Exception:
        funcoes_permitidas = {
            "transformarParaDict": transformar_para_dict,
            "pmem": transformar_para_dict,
            "pfullmem": transformar_para_dict,
            "pcputimes": transformar_para_dict,
            "pthread": transformar_para_dict,
            "popenfile": transformar_para_dict,
            "pconn": transformar_para_dict,
            "sconn": transformar_para_dict,
            "addr": transformar_para_dict,
        }
        try:
            processos = eval(texto_bruto, {"__builtins__": {}}, funcoes_permitidas)
        except Exception:
            return []

    if isinstance(processos, list):
        return [item for item in processos if isinstance(item, dict)]
    return []


def limpar_cmdline(cmdline: Any) -> Optional[List[Any] | str]:
    if cmdline is None:
        return None
    try:
        if pd.isna(cmdline):
            return None
    except Exception:
        pass

    if isinstance(cmdline, list):
        valores = []
        for item in cmdline:
            if item is None:
                continue
            try:
                if pd.isna(item):
                    continue
            except Exception:
                pass
            if isinstance(item, str) and item.strip() == "":
                continue
            valores.append(normalizar_json(item))
        return valores or None

    if isinstance(cmdline, str):
        cmdline = cmdline.strip()
        return cmdline or None

    return normalizar_json(cmdline)


def texto_pesquisavel_processo(processo: dict) -> str:
    nome = str(processo.get("name") or "").lower()
    exe = str(processo.get("exe") or "").lower()
    cmdline = limpar_cmdline(processo.get("cmdline"))

    if isinstance(cmdline, list):
        texto_cmdline = " ".join(str(item) for item in cmdline if item).lower()
    else:
        texto_cmdline = str(cmdline or "").lower()

    return f"{nome} {exe} {texto_cmdline}".strip()


def processo_alta_prioridade(processo: dict) -> bool:
    nome = str(processo.get("name") or "").lower()
    texto = texto_pesquisavel_processo(processo)
    return any(nome.startswith(prefixo) or prefixo in texto for prefixo in CONFIG["high_priority_prefixes"])


def valores_processo(processo: dict) -> dict:
    memoria = processo.get("memory_info") or {}
    if not isinstance(memoria, dict):
        memoria = {}
    rss_bytes = float(memoria.get("rss") or 0)
    return {
        "cpu_percent": float(processo.get("cpu_percent") or 0),
        "memory_percent": float(processo.get("memory_percent") or 0),
        "num_threads": int(processo.get("num_threads") or 0),
        "rss_bytes": rss_bytes,
        "rss_mb": rss_bytes / 1024 / 1024,
    }


def identificar_processo(processo: dict) -> str:
    nome = str(processo.get("name") or "").lower()
    pid = processo.get("pid")
    create_time = processo.get("create_time")

    if pid is not None and create_time is not None:
        return f"pid:{pid}|created:{create_time}|name:{nome}"

    return f"name:{nome}|texto:{texto_pesquisavel_processo(processo)[:180]}"


def motivos_alerta_processo(processo: dict, valores_anteriores: Optional[dict] = None) -> List[str]:
    valores = valores_processo(processo)
    alta = processo_alta_prioridade(processo)
    texto = texto_pesquisavel_processo(processo)

    limite_cpu = CONFIG["high_priority_process_cpu_alert"] if alta else CONFIG["process_cpu_alert"]
    limite_memoria = CONFIG["high_priority_process_memory_percent_alert"] if alta else CONFIG["process_memory_percent_alert"]
    limite_rss = CONFIG["high_priority_process_rss_mb_alert"] if alta else CONFIG["process_rss_mb_alert"]

    motivos = []

    if alta:
        motivos.append("processo_rbc_alta_prioridade")

    if valores["cpu_percent"] >= limite_cpu:
        motivos.append(f"cpu_percent >= {limite_cpu:g}")

    if valores["memory_percent"] >= limite_memoria:
        motivos.append(f"memory_percent >= {limite_memoria:g}")

    if valores["rss_mb"] >= limite_rss:
        motivos.append(f"rss_mb >= {limite_rss:g}")

    if valores["num_threads"] >= CONFIG["process_threads_alert"]:
        motivos.append(f"num_threads >= {CONFIG['process_threads_alert']:g}")

    if valores_anteriores:
        delta_cpu = valores["cpu_percent"] - float(valores_anteriores.get("cpu_percent") or 0)
        delta_memoria = valores["memory_percent"] - float(valores_anteriores.get("memory_percent") or 0)
        delta_rss = valores["rss_mb"] - float(valores_anteriores.get("rss_mb") or 0)
        multiplicador = 0.5 if alta else 1.0

        if delta_cpu >= CONFIG["process_cpu_spike_alert"] * multiplicador:
            motivos.append(f"anomalia_cpu_delta >= {CONFIG['process_cpu_spike_alert'] * multiplicador:g}")

        if delta_memoria >= CONFIG["process_memory_spike_alert"] * multiplicador:
            motivos.append(f"anomalia_memory_percent_delta >= {CONFIG['process_memory_spike_alert'] * multiplicador:g}")

        if delta_rss >= CONFIG["process_rss_growth_mb_alert"] * multiplicador:
            motivos.append(f"anomalia_rss_growth_mb >= {CONFIG['process_rss_growth_mb_alert'] * multiplicador:g}")

    if any(palavra in texto for palavra in CONFIG["important_process_keywords"]):
        if (
            valores["cpu_percent"] >= CONFIG["process_cpu_alert"] / 2
            or valores["memory_percent"] >= CONFIG["process_memory_percent_alert"] / 2
            or valores["rss_mb"] >= CONFIG["process_rss_mb_alert"] / 2
        ):
            motivos.append("processo_importante_com_consumo_relevante")

    if alta and motivos == ["processo_rbc_alta_prioridade"]:
        return []

    return motivos


def classificar_causas_processo(alerta: dict) -> List[dict]:
    causas = []
    anomalias = alerta.get("anomalias") or {}
    motivos = alerta.get("motivos_alerta") or []

    score = float(anomalias.get("score_anomalia_processo") or 0)
    delta_cpu = float(anomalias.get("cpu_delta_desde_leitura_anterior") or 0)
    delta_memoria = float(anomalias.get("memory_percent_delta_desde_leitura_anterior") or 0)
    delta_rss = float(anomalias.get("rss_growth_mb_desde_leitura_anterior") or 0)

    if alerta.get("alta_prioridade"):
        causas.append({
            "tipo": "PROCESSO_RBC_PRIORITARIO",
            "nivel": "ALTO",
            "mensagem": "Processo RBC prioritário apresentou consumo ou anomalia relevante.",
        })

    if delta_rss >= CONFIG["process_rss_growth_mb_alert"] or any("anomalia_rss_growth_mb" in motivo for motivo in motivos):
        causas.append({
            "tipo": "MEMORY_LEAK",
            "nivel": "CRITICO" if score >= 5 else "ALTO",
            "mensagem": "RSS cresceu rapidamente; possível vazamento de memória.",
        })

    if delta_cpu >= CONFIG["process_cpu_spike_alert"] or any("anomalia_cpu_delta" in motivo for motivo in motivos):
        causas.append({
            "tipo": "CPU_SPIKE",
            "nivel": "ALTO",
            "mensagem": "CPU teve aumento brusco; possível loop, tarefa pesada ou processo preso.",
        })

    if delta_memoria >= CONFIG["process_memory_spike_alert"] or any("anomalia_memory_percent_delta" in motivo for motivo in motivos):
        causas.append({
            "tipo": "RAM_SPIKE",
            "nivel": "ALTO",
            "mensagem": "Uso percentual de memória subiu de forma anormal.",
        })

    if any("num_threads" in motivo for motivo in motivos):
        causas.append({
            "tipo": "THREAD_EXCESS",
            "nivel": "ALTO",
            "mensagem": "Quantidade de threads acima do limite; possível excesso de concorrência ou deadlock parcial.",
        })

    if any("processo_importante_com_consumo_relevante" in motivo for motivo in motivos):
        causas.append({
            "tipo": "PROCESSO_IMPORTANTE_COM_CONSUMO",
            "nivel": "MEDIO",
            "mensagem": "Processo importante de infraestrutura com consumo relevante.",
        })

    if not causas:
        causas.append({
            "tipo": "PROCESSO_SUSPEITO",
            "nivel": "MEDIO",
            "mensagem": "Processo foi sinalizado pela ETL, mas sem causa específica forte.",
        })

    return causas


def resumir_problema_processo(alerta: dict) -> str:
    motivos = " | ".join(alerta.get("motivos_alerta") or [])

    if "anomalia_rss_growth_mb" in motivos:
        return "Vazamento de memória com risco de travamento"

    if "anomalia_cpu_delta" in motivos:
        return "Pico de CPU com risco de lentidão ou processo preso"

    if "num_threads" in motivos:
        return "Excesso de threads com risco de travamento parcial"

    if alerta.get("alta_prioridade") and "rss_mb" in motivos:
        return "Processo RBC prioritário usando memória acima do limite"

    if alerta.get("alta_prioridade") and "cpu_percent" in motivos:
        return "Processo RBC prioritário usando CPU acima do limite"

    if "processo_importante_com_consumo_relevante" in motivos:
        return "Processo importante com consumo relevante"

    return "Processo suspeito com consumo fora do esperado"


def acoes_sugeridas_processo(alerta: dict) -> List[str]:
    nome = alerta.get("name") or "processo"
    causas = {causa.get("tipo") for causa in alerta.get("causas_possiveis") or []}

    acoes = [f"Verificar logs do processo {nome}"]

    if "MEMORY_LEAK" in causas:
        acoes.append("Comparar RSS das leituras anteriores para confirmar crescimento contínuo.")
        acoes.append("Reiniciar o serviço se o consumo continuar subindo ou se a máquina estiver inativa.")

    if "CPU_SPIKE" in causas:
        acoes.append("Verificar loop, tarefa pesada ou operação bloqueante no processo.")

    if "THREAD_EXCESS" in causas:
        acoes.append("Checar quantidade de threads, deadlocks e pool de workers.")

    if alerta.get("alta_prioridade"):
        acoes.append("Priorizar análise por ser processo RBC.")

    acoes.append("Conferir se o processo morreu, reiniciou ou ficou travado após a última leitura.")
    return acoes


def montar_alerta_processo(processo: dict, motivos: List[str], valores_anteriores: Optional[dict] = None) -> dict:
    valores = valores_processo(processo)
    valores_anteriores = valores_anteriores or {}

    delta_cpu = valores["cpu_percent"] - float(valores_anteriores.get("cpu_percent") or 0) if valores_anteriores else None
    delta_memoria = valores["memory_percent"] - float(valores_anteriores.get("memory_percent") or 0) if valores_anteriores else None
    delta_rss = valores["rss_mb"] - float(valores_anteriores.get("rss_mb") or 0) if valores_anteriores else None

    score = 0.0
    score += valores["cpu_percent"] / max(CONFIG["process_cpu_alert"], 1)
    score += valores["memory_percent"] / max(CONFIG["process_memory_percent_alert"], 0.1)
    score += valores["rss_mb"] / max(CONFIG["process_rss_mb_alert"], 1)
    score += valores["num_threads"] / max(CONFIG["process_threads_alert"], 1)

    if delta_cpu is not None:
        score += max(delta_cpu / max(CONFIG["process_cpu_spike_alert"], 1), 0) * 2
    if delta_memoria is not None:
        score += max(delta_memoria / max(CONFIG["process_memory_spike_alert"], 0.1), 0) * 2
    if delta_rss is not None:
        score += max(delta_rss / max(CONFIG["process_rss_growth_mb_alert"], 1), 0) * 2

    if processo_alta_prioridade(processo):
        score *= 2

    memoria = processo.get("memory_info") or {}
    if not isinstance(memoria, dict):
        memoria = {}
    cpu_times = processo.get("cpu_times") or {}
    if not isinstance(cpu_times, dict):
        cpu_times = {}

    alerta = {
        "pid": normalizar_json(processo.get("pid")),
        "name": normalizar_json(processo.get("name")),
        "alta_prioridade": processo_alta_prioridade(processo),
        "nivel": "CRITICO" if score >= 5 or processo_alta_prioridade(processo) else "ALTO",
        "username": normalizar_json(processo.get("username")),
        "status": normalizar_json(processo.get("status")),
        "cpu_percent": normalizar_json(processo.get("cpu_percent")),
        "memory_percent": normalizar_json(processo.get("memory_percent")),
        "rss_mb": round(valores["rss_mb"], 2),
        "rss_human": converter_bytes(valores["rss_bytes"]),
        "vms_human": converter_bytes(memoria.get("vms")),
        "num_threads": normalizar_json(processo.get("num_threads")),
        "cmdline": limpar_cmdline(processo.get("cmdline")),
        "exe": normalizar_json(processo.get("exe")),
        "cpu_times": {
            "user": normalizar_json(cpu_times.get("user")),
            "system": normalizar_json(cpu_times.get("system")),
        },
        "anomalias": {
            "cpu_delta_desde_leitura_anterior": round(delta_cpu, 4) if delta_cpu is not None else None,
            "memory_percent_delta_desde_leitura_anterior": round(delta_memoria, 4) if delta_memoria is not None else None,
            "rss_growth_mb_desde_leitura_anterior": round(delta_rss, 2) if delta_rss is not None else None,
            "score_anomalia_processo": round(score, 4),
        },
        "motivos_alerta": motivos,
    }

    alerta["causas_possiveis"] = classificar_causas_processo(alerta)
    alerta["possivel_problema"] = resumir_problema_processo(alerta)
    alerta["possivel_impacto"] = "Pode ter causado lentidão, travamento, parada do processo ou atraso/perda de leitura da máquina."
    alerta["acoes_sugeridas"] = acoes_sugeridas_processo(alerta)

    return alerta


def chave_ordenacao_alerta_processo(alerta: dict) -> tuple:
    return (
        bool(alerta.get("alta_prioridade")),
        float((alerta.get("anomalias") or {}).get("score_anomalia_processo") or 0),
        float(alerta.get("cpu_percent") or 0),
        float(alerta.get("memory_percent") or 0),
        float(alerta.get("rss_mb") or 0),
        float(alerta.get("num_threads") or 0),
    )


def parsear_data_evento(valor: Any, fim: bool = False) -> Optional[datetime]:
    if valor is None or valor == "":
        return None

    texto = str(valor).strip()
    somente_data = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto))

    ts = pd.to_datetime(texto, errors="coerce", utc=False)
    if pd.isna(ts):
        return None

    if isinstance(ts, pd.Timestamp):
        dt = ts.to_pydatetime()
    else:
        dt = ts

    if getattr(dt, "tzinfo", None) is not None:
        dt = pd.Timestamp(dt).tz_convert("UTC").tz_localize(None).to_pydatetime()

    if somente_data and fim:
        return datetime.combine(dt.date(), time(23, 59, 59, 999999))
    if somente_data and not fim:
        return datetime.combine(dt.date(), time(0, 0, 0, 0))

    return dt.replace(tzinfo=None)


def parsear_chave_raw(chave: str) -> dict:
    partes = chave.strip("/").split("/")
    meta = {
        "mac": None,
        "data_hora": None,
        "ano": None,
        "mes": None,
        "dia": None,
    }

    if len(partes) < 5:
        return meta

    nome = partes[-1]
    match_nome = re.fullmatch(r"(?P<hora>\d{2})h(?P<minuto>\d{2})\.csv", nome, flags=re.IGNORECASE)
    if not match_nome:
        return meta

    ano, mes, dia = partes[-4], partes[-3], partes[-2]
    mac = limpar_mac(partes[-5])

    if not re.fullmatch(r"\d{4}", ano or ""):
        return meta
    if not re.fullmatch(r"\d{2}", mes or ""):
        return meta
    if not re.fullmatch(r"\d{2}", dia or ""):
        return meta

    try:
        dt = datetime(
            int(ano),
            int(mes),
            int(dia),
            int(match_nome.group("hora")),
            int(match_nome.group("minuto")),
        )
    except Exception:
        dt = None

    meta.update({
        "mac": mac,
        "data_hora": dt,
        "ano": int(ano),
        "mes": int(mes),
        "dia": int(dia),
    })
    return meta


def extrair_macs_evento(event: dict) -> Optional[set[str]]:
    candidatos = []

    for chave in ("mac", "input_mac", "endereco_mac", "mac_address"):
        if event.get(chave):
            candidatos.append(event.get(chave))

    for chave in ("macs", "input_macs", "enderecos_mac"):
        valor = event.get(chave)
        if valor:
            if isinstance(valor, str):
                candidatos.extend([item.strip() for item in valor.split(",") if item.strip()])
            elif isinstance(valor, Iterable):
                candidatos.extend(list(valor))

    macs = {limpar_mac(item) for item in candidatos}
    macs = {item for item in macs if item}
    return macs or None


def normalizar_lista_chaves(valor: Any) -> List[str]:
    if valor is None:
        return []
    if isinstance(valor, str):
        texto = valor.strip()
        if not texto:
            return []
        if texto.startswith("["):
            try:
                dados = json.loads(texto)
                if isinstance(dados, list):
                    return [str(item) for item in dados if str(item).strip()]
            except Exception:
                pass
        return [item.strip() for item in texto.split(",") if item.strip()]
    if isinstance(valor, Iterable):
        return [str(item) for item in valor if str(item).strip()]
    return []


def listar_csvs_s3(
    bucket: str,
    prefix: str,
    macs: Optional[set[str]] = None,
    data_inicio: Optional[datetime] = None,
    data_fim: Optional[datetime] = None,
    latest_files_per_mac: Optional[int] = None,
    max_csvs: Optional[int] = None,
) -> List[str]:
    prefix = (prefix or "").lstrip("/")
    paginator = s3.get_paginator("list_objects_v2")
    itens: List[dict] = []

    for pagina in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in pagina.get("Contents", []):
            chave = item["Key"]
            chave_lower = chave.lower()
            nome_lower = chave.rsplit("/", 1)[-1].lower()

            if not nome_lower.endswith(".csv"):
                continue
            if "/trusted/" in f"/{chave_lower}":
                continue
            if nome_lower.startswith("maquinas_enriquecido") or nome_lower.startswith("empresas_linhas_rbc"):
                continue

            meta = parsear_chave_raw(chave)
            mac_chave = meta.get("mac")
            data_chave = meta.get("data_hora")

            if macs and mac_chave and mac_chave not in macs:
                continue
            if data_inicio and data_chave and data_chave < data_inicio:
                continue
            if data_fim and data_chave and data_chave > data_fim:
                continue

            itens.append({
                "key": chave,
                "mac": mac_chave or "__sem_mac__",
                "data_hora": data_chave,
                "last_modified": item.get("LastModified"),
            })

    if not itens:
        return []

    def ordem(item: dict) -> tuple:
        data_hora = item.get("data_hora")
        last_modified = item.get("last_modified")
        return (
            data_hora or datetime.min,
            last_modified.replace(tzinfo=None) if getattr(last_modified, "tzinfo", None) else (last_modified or datetime.min),
            item.get("key") or "",
        )

    latest_files_per_mac = CONFIG["latest_files_per_mac"] if latest_files_per_mac is None else int(latest_files_per_mac)
    max_csvs = CONFIG["max_csvs_per_run"] if max_csvs is None else int(max_csvs)

    if latest_files_per_mac > 0:
        por_mac: Dict[str, List[dict]] = {}
        for item in itens:
            por_mac.setdefault(str(item["mac"]), []).append(item)

        filtrados = []
        for _, grupo in por_mac.items():
            grupo.sort(key=ordem, reverse=True)
            filtrados.extend(grupo[:latest_files_per_mac])
        itens = filtrados

    itens.sort(key=ordem, reverse=True)

    if max_csvs > 0:
        itens = itens[:max_csvs]

    itens.sort(key=ordem)
    return [item["key"] for item in itens]


def ler_csv_s3(bucket: str, chave: str) -> pd.DataFrame:
    objeto = s3.get_object(Bucket=bucket, Key=chave)
    corpo = objeto["Body"].read()

    try:
        tabela = pd.read_csv(BytesIO(corpo), low_memory=False)
    except UnicodeDecodeError:
        texto = corpo.decode("utf-8", errors="replace")
        tabela = pd.read_csv(StringIO(texto), low_memory=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()

    tabela.columns = [str(coluna).strip().replace("\ufeff", "") for coluna in tabela.columns]
    tabela["arquivo_origem_csv"] = chave

    meta = parsear_chave_raw(chave)
    tabela["mac_origem_s3"] = meta.get("mac")
    tabela["data_hora_arquivo_iso"] = meta.get("data_hora").isoformat() if meta.get("data_hora") else None

    return tabela


def carregar_csvs_s3(bucket: str, chaves: List[str]) -> Tuple[pd.DataFrame, List[str]]:
    tabelas = []
    avisos = []

    for chave in chaves:
        try:
            tabela = ler_csv_s3(bucket, chave)
            if tabela.empty:
                avisos.append(f"CSV vazio ignorado: {chave}")
                continue
            tabelas.append(tabela)
        except Exception as erro:
            avisos.append(f"CSV ignorado por erro de leitura: {chave} | {type(erro).__name__}: {erro}")

    if not tabelas:
        detalhe = "; ".join(avisos[-5:]) if avisos else "Nenhum CSV encontrado para processar."
        raise ValueError(f"Nenhum CSV válido encontrado para processar. {detalhe}")

    return pd.concat(tabelas, ignore_index=True), avisos


def aplicar_alias_colunas(tabela: pd.DataFrame) -> pd.DataFrame:
    renomear = {}

    for coluna in tabela.columns:
        normal = str(coluna).strip().lower().replace(" ", "_").replace("-", "_")
        destino = ALIASES_COLUNAS.get(normal)
        if destino and destino not in tabela.columns:
            renomear[coluna] = destino

    if renomear:
        tabela = tabela.rename(columns=renomear)

    return tabela


def converter_datahora_serie(serie: pd.Series) -> pd.Series:
    convertido = pd.to_datetime(serie, errors="coerce", utc=True)
    return convertido.dt.tz_localize(None)


def preparar_dataframe(tabela: pd.DataFrame) -> pd.DataFrame:
    tabela = tabela.copy()
    tabela.columns = [str(coluna).strip().replace("\ufeff", "") for coluna in tabela.columns]
    tabela = aplicar_alias_colunas(tabela)

    if "endereco_mac" not in tabela.columns and "mac_origem_s3" in tabela.columns:
        tabela["endereco_mac"] = tabela["mac_origem_s3"]

    if "data_hora_iso" not in tabela.columns:
        if "data_hora_envio" in tabela.columns:
            tabela["data_hora_iso"] = tabela["data_hora_envio"]
        elif "data_hora_arquivo_iso" in tabela.columns:
            tabela["data_hora_iso"] = tabela["data_hora_arquivo_iso"]

    colunas_obrigatorias = ["endereco_mac", "data_hora_iso"]
    ausentes = [coluna for coluna in colunas_obrigatorias if coluna not in tabela.columns]
    if ausentes:
        raise ValueError(f"Colunas obrigatórias ausentes: {', '.join(ausentes)}")

    tabela["endereco_mac"] = tabela["endereco_mac"].where(tabela["endereco_mac"].notna(), tabela.get("mac_origem_s3"))
    tabela["endereco_mac"] = tabela["endereco_mac"].map(limpar_mac)

    tabela["data_hora_iso"] = tabela["data_hora_iso"].where(tabela["data_hora_iso"].notna(), tabela.get("data_hora_arquivo_iso"))
    tabela["data_hora_iso"] = converter_datahora_serie(tabela["data_hora_iso"])

    for coluna in COLUNAS_NUMERICAS:
        if coluna in tabela.columns:
            tabela[coluna] = pd.to_numeric(tabela[coluna], errors="coerce", downcast="float")

    # O coletor novo usa percentual_uso_ram, mas o score antigo espera uso_memoria.
    if "uso_memoria" not in tabela.columns:
        tabela["uso_memoria"] = tabela["percentual_uso_ram"] if "percentual_uso_ram" in tabela.columns else np.nan

    # O coletor novo não captura swap; mantém 0 para o score não punir dado ausente.
    if "percentual_uso_swap" not in tabela.columns:
        tabela["percentual_uso_swap"] = 0.0

    for coluna in ["percentual_uso_cpu", "percentual_uso_ram", "percentual_uso_disco", "latencia_ping_ms"]:
        if coluna not in tabela.columns:
            tabela[coluna] = np.nan

    if CONFIG["skip_process_alerts"] or "processos" not in tabela.columns:
        tabela["processos_parsed"] = [[] for _ in range(len(tabela))]
    else:
        tabela["processos_parsed"] = [separar_processos(valor) for valor in tabela["processos"]]

    tabela = tabela.dropna(subset=["endereco_mac", "data_hora_iso"])
    tabela = tabela.drop_duplicates(subset=["endereco_mac", "data_hora_iso", "arquivo_origem_csv"], keep="last")
    tabela = tabela.sort_values(["endereco_mac", "data_hora_iso"]).reset_index(drop=True)

    if tabela.empty:
        raise ValueError("Após limpar MAC/data, nenhum registro válido sobrou.")

    return tabela


def mysql_config() -> dict:
    obrigatorias = ["DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"]
    ausentes = [chave for chave in obrigatorias if not os.getenv(chave)]
    if ausentes:
        raise ValueError(f"Variáveis MySQL ausentes: {', '.join(ausentes)}")

    return {
        "host": os.environ["DB_HOST"],
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
        "database": os.environ["DB_NAME"],
        "connection_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "5")),
    }


def buscar_mapeamento_mysql(macs: List[str]) -> pd.DataFrame:
    if not macs:
        return pd.DataFrame(columns=COLUNAS_MAPEAMENTO)

    import mysql.connector

    conexao = mysql.connector.connect(**mysql_config())

    try:
        cursor = conexao.cursor(dictionary=True)
        marcadores = ", ".join(["%s"] * len(macs))

        consulta = f"""
            SELECT
                LOWER(REPLACE(TRIM(r.macAdress), ':', '-')) AS endereco_mac,
                e.idEmpresa AS id_empresa,
                e.razaoSocial AS nome_empresa,
                l.idLinha AS id_linha,
                CONCAT('Linha ', l.idLinha) AS nome_linha,
                r.idRbc AS id_rbc,
                r.nomeServidor AS nome_rbc
            FROM rbc r
            JOIN linha l ON r.fkLinha = l.idLinha
            JOIN empresa e ON e.idEmpresa = l.fkEmpresa
            WHERE LOWER(REPLACE(TRIM(r.macAdress), ':', '-')) IN ({marcadores})
        """

        cursor.execute(consulta, macs)
        linhas = cursor.fetchall()

        if not linhas:
            return pd.DataFrame(columns=COLUNAS_MAPEAMENTO)

        mapeamento = pd.DataFrame(linhas)
        mapeamento["endereco_mac"] = mapeamento["endereco_mac"].map(limpar_mac)
        return mapeamento

    finally:
        conexao.close()


def mapeamento_sem_banco(tabela: pd.DataFrame) -> pd.DataFrame:
    mapeamento = pd.DataFrame({"endereco_mac": sorted(tabela["endereco_mac"].dropna().unique())})
    mapeamento["id_empresa"] = None
    mapeamento["nome_empresa"] = "SEM_EMPRESA"
    mapeamento["id_linha"] = None
    mapeamento["nome_linha"] = "SEM_LINHA"
    mapeamento["id_rbc"] = mapeamento["endereco_mac"]
    mapeamento["nome_rbc"] = mapeamento["endereco_mac"]
    return mapeamento


def obter_mapeamento(tabela: pd.DataFrame, avisos: List[str]) -> pd.DataFrame:
    macs = sorted(tabela["endereco_mac"].dropna().unique().tolist())

    if CONFIG["no_db"]:
        return mapeamento_sem_banco(tabela)

    try:
        mapeamento = buscar_mapeamento_mysql(macs)
        if mapeamento.empty:
            avisos.append("MySQL não retornou mapeamento para os MACs processados; usando fallback SEM_EMPRESA.")
            return mapeamento_sem_banco(tabela)
        return mapeamento
    except Exception as erro:
        mensagem = f"Falha ao buscar mapeamento MySQL: {type(erro).__name__}: {erro}"
        if CONFIG["db_required"]:
            raise RuntimeError(mensagem) from erro
        avisos.append(mensagem + " | usando fallback SEM_EMPRESA.")
        return mapeamento_sem_banco(tabela)


def classificar_saude(score: Any) -> Optional[str]:
    try:
        if score is None or pd.isna(score):
            return None
        score = float(score)
    except Exception:
        return None

    if score > 85:
        return "CRITICO"
    if score > 70:
        return "ALTO"
    if score > 50:
        return "MODERADO"
    return "BAIXO"


def enriquecer_maquinas(tabela: pd.DataFrame, mapeamento: pd.DataFrame) -> pd.DataFrame:
    tabela = tabela.merge(mapeamento, on="endereco_mac", how="left")

    tabela["nome_empresa"] = tabela.get("nome_empresa", pd.Series(index=tabela.index)).fillna("SEM_EMPRESA")
    tabela["nome_linha"] = tabela.get("nome_linha", pd.Series(index=tabela.index)).fillna("SEM_LINHA")
    tabela["id_rbc"] = tabela.get("id_rbc", pd.Series(index=tabela.index)).fillna(tabela["endereco_mac"])
    tabela["nome_rbc"] = tabela.get("nome_rbc", pd.Series(index=tabela.index)).fillna(tabela["endereco_mac"])

    for coluna in ["percentual_uso_cpu", "uso_memoria", "percentual_uso_disco", "percentual_uso_swap"]:
        if coluna not in tabela.columns:
            tabela[coluna] = 0.0

    tabela["score"] = (
        tabela["percentual_uso_cpu"].fillna(0) * 0.3
        + tabela["uso_memoria"].fillna(0) * 0.3
        + tabela["percentual_uso_disco"].fillna(0) * 0.2
        + tabela["percentual_uso_swap"].fillna(0) * 0.2
    )
    tabela["criticidade"] = [classificar_saude(valor) for valor in tabela["score"]]

    colunas_bytes = [
        "memoria_total_bytes",
        "memoria_disponivel_bytes",
        "disco_livre_bytes",
        "disco_usado_bytes",
        "taxa_leitura_disco_bytes_por_segundo",
        "taxa_escrita_disco_bytes_por_segundo",
        "taxa_download_rede_bytes_por_segundo",
        "taxa_upload_rede_bytes_por_segundo",
    ]

    for coluna in colunas_bytes:
        if coluna in tabela.columns:
            tabela[f"{coluna}_human"] = [converter_bytes(valor) for valor in tabela[coluna]]
        else:
            tabela[f"{coluna}_human"] = None

    for coluna in ["frequencia_cpu_atual_mhz", "frequencia_cpu_minima_mhz", "frequencia_cpu_maxima_mhz"]:
        if coluna in tabela.columns:
            tabela[f"{coluna}_human"] = [converter_mhz(valor) for valor in tabela[coluna]]
        else:
            tabela[f"{coluna}_human"] = None

    return tabela


def adicionar_status_inatividade(tabela: pd.DataFrame) -> pd.DataFrame:
    tabela = tabela.copy()
    tabela["data_hora_iso"] = converter_datahora_serie(tabela["data_hora_iso"])

    agora = pd.Timestamp.utcnow().tz_localize(None)
    tabela["horario_atual_etl"] = agora
    tabela["idade_ultima_leitura_minutos"] = (agora - tabela["data_hora_iso"]).dt.total_seconds() / 60
    tabela["idade_ultima_leitura_segundos"] = tabela["idade_ultima_leitura_minutos"] * 60

    coluna_grupo = "id_rbc" if "id_rbc" in tabela.columns else "endereco_mac"
    tabela = tabela.sort_values([coluna_grupo, "data_hora_iso"]).copy()
    tabela["leitura_anterior_data_hora"] = tabela.groupby(coluna_grupo)["data_hora_iso"].shift(1)
    tabela["intervalo_desde_leitura_anterior_minutos"] = (
        tabela["data_hora_iso"] - tabela["leitura_anterior_data_hora"]
    ).dt.total_seconds() / 60
    tabela["intervalo_desde_leitura_anterior_segundos"] = tabela["intervalo_desde_leitura_anterior_minutos"] * 60

    # Mantém nomes antigos para o frontend: aqui "gap" significa tempo desde a última leitura até a execução da ETL.
    tabela["gap_leitura_anterior_minutos"] = tabela["idade_ultima_leitura_minutos"]
    tabela["gap_leitura_anterior_segundos"] = tabela["idade_ultima_leitura_segundos"]

    tabela["rbc_status"] = np.where(
        tabela["idade_ultima_leitura_minutos"].fillna(float("inf")) >= CONFIG["rbc_offline_gap_minutes"],
        "OFFLINE",
        "ONLINE",
    )

    tabela["rbc_status_motivo"] = np.where(
        tabela["rbc_status"].eq("OFFLINE"),
        f"RBC sem leitura recente há {CONFIG['rbc_offline_gap_minutes']:g}+ minutos",
        None,
    )

    return tabela


def adicionar_alertas_processos(tabela: pd.DataFrame) -> pd.DataFrame:
    tabela = tabela.copy()

    if CONFIG["skip_process_alerts"]:
        tabela["processos_alerta_priorizados"] = [[] for _ in range(len(tabela))]
        return tabela

    coluna_grupo = "id_rbc" if "id_rbc" in tabela.columns else "endereco_mac"
    valores_anteriores_por_chave: Dict[tuple, dict] = {}
    alertas_por_indice: Dict[Any, List[dict]] = {indice: [] for indice in tabela.index}

    for indice, linha in tabela.sort_values([coluna_grupo, "data_hora_iso"]).iterrows():
        chave_maquina = linha.get(coluna_grupo)
        alertas_linha = []

        for processo in linha.get("processos_parsed", []) or []:
            if not isinstance(processo, dict):
                continue

            chave_processo = (chave_maquina, identificar_processo(processo))
            valores_anteriores = valores_anteriores_por_chave.get(chave_processo)

            motivos = motivos_alerta_processo(processo, valores_anteriores=valores_anteriores)
            if motivos:
                alertas_linha.append(montar_alerta_processo(processo, motivos, valores_anteriores))

            valores_anteriores_por_chave[chave_processo] = valores_processo(processo)

        alertas_linha.sort(key=chave_ordenacao_alerta_processo, reverse=True)
        alertas_por_indice[indice] = alertas_linha[: CONFIG["max_processes_per_reading"]]

    tabela["processos_alerta_priorizados"] = [alertas_por_indice.get(indice, []) for indice in tabela.index]
    return tabela


def definir_causa_principal_maquina(status: str, inatividade_minutos: float, processos_alerta: List[dict]) -> dict:
    if status != "ONLINE" and processos_alerta:
        evidencias = [
            f"Máquina sem leitura por {inatividade_minutos:.1f} minutos",
            f"{len(processos_alerta)} processo(s) em alerta na última leitura",
        ]

        top = processos_alerta[0]
        causas_top = [causa.get("tipo") for causa in top.get("causas_possiveis") or []]
        if causas_top:
            evidencias.append(f"Principal processo suspeito: {top.get('name')} ({', '.join(causas_top)})")

        return {
            "tipo": "POSSIVEL_CRASH_OU_TRAVAMENTO",
            "nivel": "CRITICO",
            "mensagem": "Máquina ficou inativa e havia processos em alerta na última leitura.",
            "confianca": "MEDIA",
            "evidencias": evidencias,
        }

    if status != "ONLINE":
        return {
            "tipo": "MAQUINA_INATIVA",
            "nivel": "CRITICO",
            "mensagem": "Máquina ficou inativa, mas não há processo em alerta suficiente para apontar causa.",
            "confianca": "BAIXA",
            "evidencias": [
                f"Máquina sem leitura por {inatividade_minutos:.1f} minutos",
                "Sem processos priorizados na última leitura",
            ],
        }

    if processos_alerta:
        return {
            "tipo": "PROCESSOS_SUSPEITOS",
            "nivel": "ALTO",
            "mensagem": "Máquina ainda está online, mas há processos que podem causar futura instabilidade.",
            "confianca": "MEDIA",
            "evidencias": [f"{len(processos_alerta)} processo(s) em alerta"],
        }

    return {
        "tipo": "SEM_SINAL_DE_CRASH",
        "nivel": "BAIXO",
        "mensagem": "Sem sinais fortes de crash ou travamento.",
        "confianca": "MEDIA",
        "evidencias": [],
    }


def montar_leitura_json(linha: pd.Series) -> dict:
    processos_alerta = linha.get("processos_alerta_priorizados")
    if not isinstance(processos_alerta, list):
        processos_alerta = []

    return {
        "data_hora": linha["data_hora_iso"].isoformat() if pd.notna(linha.get("data_hora_iso")) else None,
        "arquivo_origem_csv": normalizar_json(linha.get("arquivo_origem_csv")),
        "rbc_status": normalizar_json(linha.get("rbc_status")),
        "gap_leitura_anterior_minutos": normalizar_json(linha.get("gap_leitura_anterior_minutos")),
        "gap_leitura_anterior_segundos": normalizar_json(linha.get("gap_leitura_anterior_segundos")),
        "idade_ultima_leitura_minutos": normalizar_json(linha.get("idade_ultima_leitura_minutos")),
        "idade_ultima_leitura_segundos": normalizar_json(linha.get("idade_ultima_leitura_segundos")),
        "intervalo_desde_leitura_anterior_minutos": normalizar_json(linha.get("intervalo_desde_leitura_anterior_minutos")),
        "intervalo_desde_leitura_anterior_segundos": normalizar_json(linha.get("intervalo_desde_leitura_anterior_segundos")),
        "leitura_anterior_data_hora": (
            linha["leitura_anterior_data_hora"].isoformat()
            if pd.notna(linha.get("leitura_anterior_data_hora"))
            else None
        ),
        "rbc_status_motivo": normalizar_json(linha.get("rbc_status_motivo")),
        "criticidade": normalizar_json(linha.get("criticidade")),
        "score": normalizar_json(linha.get("score")),
        "latencia_ping_ms": normalizar_json(linha.get("latencia_ping_ms")),
        "cpu": {
            "percentual_uso_cpu": normalizar_json(linha.get("percentual_uso_cpu")),
            "frequencia_atual": normalizar_json(linha.get("frequencia_cpu_atual_mhz_human")),
            "frequencia_minima": normalizar_json(linha.get("frequencia_cpu_minima_mhz_human")),
            "frequencia_maxima": normalizar_json(linha.get("frequencia_cpu_maxima_mhz_human")),
        },
        "memoria": {
            "percentual_uso_ram": normalizar_json(linha.get("percentual_uso_ram")),
            "total": normalizar_json(linha.get("memoria_total_bytes_human")),
            "disponivel": normalizar_json(linha.get("memoria_disponivel_bytes_human")),
        },
        "disco": {
            "percentual_uso_disco": normalizar_json(linha.get("percentual_uso_disco")),
            "livre": normalizar_json(linha.get("disco_livre_bytes_human")),
            "usado": normalizar_json(linha.get("disco_usado_bytes_human")),
            "leitura_por_segundo": normalizar_json(linha.get("taxa_leitura_disco_bytes_por_segundo_human")),
            "escrita_por_segundo": normalizar_json(linha.get("taxa_escrita_disco_bytes_por_segundo_human")),
        },
        "swap": {
            "percentual_uso_swap": normalizar_json(linha.get("percentual_uso_swap")),
        },
        "rede": {
            "download_por_segundo": normalizar_json(linha.get("taxa_download_rede_bytes_por_segundo_human")),
            "upload_por_segundo": normalizar_json(linha.get("taxa_upload_rede_bytes_por_segundo_human")),
        },
        "processos_alerta": processos_alerta,
        "total_processos_alerta": len(processos_alerta),
    }


def montar_json_hierarquico(tabela: pd.DataFrame) -> dict:
    empresas = []

    for (id_empresa, nome_empresa), tabela_empresa in tabela.groupby(["id_empresa", "nome_empresa"], dropna=False):
        linhas = []

        for (id_linha, nome_linha), tabela_linha in tabela_empresa.groupby(["id_linha", "nome_linha"], dropna=False):
            rbcs = []

            for id_rbc, tabela_rbc in tabela_linha.groupby("id_rbc", dropna=False):
                ultimas = tabela_rbc.sort_values("data_hora_iso").tail(CONFIG["last_n"])
                ultima = ultimas.iloc[-1]
                processos_alerta = ultima.get("processos_alerta_priorizados")
                if not isinstance(processos_alerta, list):
                    processos_alerta = []

                rbcs.append({
                    "id_rbc": normalizar_json(id_rbc),
                    "nome_rbc": normalizar_json(ultima.get("nome_rbc")),
                    "endereco_mac": normalizar_json(ultima.get("endereco_mac")),
                    "status_atual": normalizar_json(ultima.get("rbc_status")),
                    "ultimo_gap_leitura_anterior_minutos": normalizar_json(ultima.get("gap_leitura_anterior_minutos")),
                    "ultimo_gap_leitura_anterior_segundos": normalizar_json(ultima.get("gap_leitura_anterior_segundos")),
                    "ultimo_intervalo_desde_leitura_anterior_minutos": normalizar_json(
                        ultima.get("intervalo_desde_leitura_anterior_minutos")
                    ),
                    "possivel_causa_principal": definir_causa_principal_maquina(
                        str(ultima.get("rbc_status") or ""),
                        float(ultima.get("gap_leitura_anterior_minutos") or 0),
                        processos_alerta,
                    ),
                    "ultimas_leituras": [montar_leitura_json(linha) for _, linha in ultimas.iterrows()],
                })

            rbcs.sort(key=lambda item: str(item.get("id_rbc") or ""))
            linhas.append({
                "id_linha": normalizar_json(id_linha),
                "nome_linha": normalizar_json(nome_linha),
                "rbc": rbcs,
            })

        linhas.sort(key=lambda item: str(item.get("id_linha") or item.get("nome_linha") or ""))
        empresas.append({
            "id_empresa": normalizar_json(id_empresa),
            "nome_empresa": normalizar_json(nome_empresa),
            "linhas": linhas,
        })

    empresas.sort(key=lambda item: str(item.get("id_empresa") or item.get("nome_empresa") or ""))
    return {"empresas": empresas}


def montar_retorno_focado_processos(tabela: pd.DataFrame, json_hierarquico: dict, incluir_json_completo: bool) -> dict:
    maquinas = []

    for (id_rbc, nome_rbc, mac), grupo in tabela.groupby(["id_rbc", "nome_rbc", "endereco_mac"], dropna=False):
        ultimas = grupo.sort_values("data_hora_iso").tail(CONFIG["last_n"])
        ultima = ultimas.iloc[-1]
        processos_alerta = ultima.get("processos_alerta_priorizados")
        if not isinstance(processos_alerta, list):
            processos_alerta = []

        inatividade = float(ultima.get("gap_leitura_anterior_minutos") or 0)
        status = str(ultima.get("rbc_status") or "DESCONHECIDO")

        maquinas.append({
            "id_rbc": normalizar_json(id_rbc),
            "nome_rbc": normalizar_json(nome_rbc),
            "endereco_mac": normalizar_json(mac),
            "empresa": normalizar_json(ultima.get("nome_empresa")),
            "linha": normalizar_json(ultima.get("nome_linha")),
            "status": status,
            "inatividade_minutos": normalizar_json(inatividade),
            "ultima_leitura": ultima["data_hora_iso"].isoformat() if pd.notna(ultima.get("data_hora_iso")) else None,
            "arquivo_origem_ultima_leitura": normalizar_json(ultima.get("arquivo_origem_csv")),
            "criticidade": normalizar_json(ultima.get("criticidade")),
            "score": normalizar_json(ultima.get("score")),
            "cpu_percent": normalizar_json(ultima.get("percentual_uso_cpu")),
            "ram_percent": normalizar_json(ultima.get("percentual_uso_ram")),
            "disco_percent": normalizar_json(ultima.get("percentual_uso_disco")),
            "latencia_ping_ms": normalizar_json(ultima.get("latencia_ping_ms")),
            "possivel_causa_principal": definir_causa_principal_maquina(status, inatividade, processos_alerta),
            "alertas_processos": processos_alerta,
            "total_processos_alerta": len(processos_alerta),
        })

    maquinas.sort(
        key=lambda item: (
            item["status"] != "ONLINE",
            item["total_processos_alerta"],
            float(item["inatividade_minutos"] or 0),
            float(item["score"] or 0),
        ),
        reverse=True,
    )

    total_maquinas = len(maquinas)
    maquinas_offline = sum(1 for item in maquinas if item["status"] != "ONLINE")
    maquinas_com_processos_alerta = sum(1 for item in maquinas if item["total_processos_alerta"] > 0)
    total_processos_alerta = sum(item["total_processos_alerta"] for item in maquinas)
    possiveis_crashes = sum(
        1
        for item in maquinas
        if (item["possivel_causa_principal"] or {}).get("tipo") == "POSSIVEL_CRASH_OU_TRAVAMENTO"
    )

    retorno = {
        "ok": True,
        "resumo": {
            "total_maquinas": total_maquinas,
            "maquinas_offline": maquinas_offline,
            "maquinas_com_processos_alerta": maquinas_com_processos_alerta,
            "total_processos_alerta": total_processos_alerta,
            "possiveis_crashes": possiveis_crashes,
            "maior_risco": maquinas[0]["nome_rbc"] if maquinas else None,
        },
        "maquinas": maquinas,
    }

    if incluir_json_completo:
        retorno["json_completo"] = json_hierarquico

    return retorno


def extrair_s3_trigger(event: dict) -> Optional[dict]:
    records = event.get("Records")
    if not isinstance(records, list) or not records:
        return None

    primeiro = records[0]
    if not isinstance(primeiro, dict) or "s3" not in primeiro:
        return None

    try:
        bucket = primeiro["s3"]["bucket"]["name"]
        keys = [unquote_plus(record["s3"]["object"]["key"]) for record in records if "s3" in record]
        return {"input_bucket": bucket, "input_keys": keys}
    except Exception:
        return None


def resolver_payload(event: Any) -> dict:
    if not isinstance(event, dict):
        return {}

    s3_event = extrair_s3_trigger(event)
    if s3_event:
        return s3_event

    if event.get("httpMethod") == "OPTIONS" or event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return {"__options": True}

    if "body" not in event:
        return event or {}

    body = event.get("body")
    if body is None:
        return {}

    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8", errors="replace")

    if isinstance(body, str):
        body = body.strip()
        if not body:
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"raw_body": body}

    if isinstance(body, dict):
        return body

    return {}


def executar_etl(event: dict) -> dict:
    avisos: List[str] = []

    input_bucket = event.get("input_bucket") or event.get("bucket") or CONFIG["input_bucket"]
    if not input_bucket:
        raise ValueError("INPUT_BUCKET não configurado. Envie input_bucket no payload ou configure INPUT_BUCKET/S3_BUCKET_NAME.")

    output_bucket = event.get("output_bucket") or CONFIG["output_bucket"] or input_bucket
    output_key = event.get("output_key") or CONFIG["output_key"]

    input_keys = normalizar_lista_chaves(event.get("input_keys"))
    if not input_keys:
        input_keys = normalizar_lista_chaves(event.get("input_key") or event.get("key"))

    input_prefix = event.get("input_prefix") or event.get("prefix") or CONFIG["input_prefix"]

    if not input_keys:
        data_inicio = parsear_data_evento(
            event.get("data_inicio") or event.get("start_date") or event.get("date_from"),
            fim=False,
        )
        data_fim = parsear_data_evento(
            event.get("data_fim") or event.get("end_date") or event.get("date_to"),
            fim=True,
        )
        macs = extrair_macs_evento(event)

        latest_files_per_mac = int(event.get("latest_files_per_mac", CONFIG["latest_files_per_mac"]))
        max_csvs = int(event.get("max_csvs", CONFIG["max_csvs_per_run"]))

        input_keys = listar_csvs_s3(
            bucket=input_bucket,
            prefix=input_prefix,
            macs=macs,
            data_inicio=data_inicio,
            data_fim=data_fim,
            latest_files_per_mac=latest_files_per_mac,
            max_csvs=max_csvs,
        )

    if not input_keys:
        raise ValueError(f"Nenhum CSV encontrado em s3://{input_bucket}/{input_prefix}")

    tabela, avisos_leitura = carregar_csvs_s3(input_bucket, input_keys)
    avisos.extend(avisos_leitura)

    tabela = preparar_dataframe(tabela)
    mapeamento = obter_mapeamento(tabela, avisos)

    tabela = enriquecer_maquinas(tabela, mapeamento)
    tabela = adicionar_status_inatividade(tabela)
    tabela = adicionar_alertas_processos(tabela)

    json_hierarquico = montar_json_hierarquico(tabela)
    corpo_json = json.dumps(
        normalizar_json(json_hierarquico),
        ensure_ascii=False,
        indent=CONFIG["json_indent"],
    ).encode("utf-8")

    s3.put_object(
        Bucket=output_bucket,
        Key=output_key,
        Body=corpo_json,
        ContentType="application/json; charset=utf-8",
    )

    retorno = montar_retorno_focado_processos(
        tabela,
        json_hierarquico=json_hierarquico,
        incluir_json_completo=bool(event.get("return_json", False)),
    )

    retorno["arquivos"] = {
        "input_bucket": input_bucket,
        "input_prefix": input_prefix,
        "input_keys": input_keys,
        "input_keys_total": len(input_keys),
        "output_bucket": output_bucket,
        "output_key": output_key,
        "s3_uri": f"s3://{output_bucket}/{output_key}",
    }

    retorno["config_execucao"] = {
        "last_n": CONFIG["last_n"],
        "latest_files_per_mac": event.get("latest_files_per_mac", CONFIG["latest_files_per_mac"]),
        "max_csvs": event.get("max_csvs", CONFIG["max_csvs_per_run"]),
        "rbc_offline_gap_minutes": CONFIG["rbc_offline_gap_minutes"],
        "skip_process_alerts": CONFIG["skip_process_alerts"],
        "no_db": CONFIG["no_db"],
        "db_required": CONFIG["db_required"],
    }

    if avisos:
        retorno["avisos"] = avisos[:50]

    return retorno


def lambda_handler(event, context):
    try:
        body = resolver_payload(event)

        if body.get("__options"):
            return resposta(200, {"ok": True})

        resultado = executar_etl(body)
        return resposta(200, resultado)

    except Exception as erro:
        return resposta(500, {
            "ok": False,
            "erro": str(erro),
            "tipo": type(erro).__name__,
        })
