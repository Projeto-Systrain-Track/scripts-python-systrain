import pandas as pd
import numpy as np
import random
import uuid
from datetime import datetime, timedelta

random.seed(2094)

MB = 1024 * 1024
GB = 1024 * 1024 * 1024

profiles = [
    {"name":"RBC_gerente_sessao_1", "cpu":10, "mem_mb":64, "disk_kbps":64, "lat_min":30, "lat_max":120, "crash":0.002, "startup_fail":0.02, "hang":0.001},
    {"name":"RBC_gerente_sessao_2", "cpu":15, "mem_mb":96, "disk_kbps":128, "lat_min":20, "lat_max":100, "crash":0.001, "startup_fail":0.01, "hang":0.001},
    {"name":"RBC_calculo_rota_1", "cpu":45, "mem_mb":128, "disk_kbps":32, "lat_min":10, "lat_max":40, "crash":0.004, "startup_fail":0.012, "hang":0.001},
    {"name":"RBC_calculo_rota_2", "cpu":55, "mem_mb":192, "disk_kbps":16, "lat_min":5, "lat_max":25, "crash":0.005, "startup_fail":0.012, "hang":0.001},
    {"name":"RBC_telemetria_1", "cpu":10, "mem_mb":48, "disk_kbps":256, "lat_min":50, "lat_max":200, "crash":0.001, "startup_fail":0.012, "hang":0.001},
    {"name":"RBC_telemetria_2", "cpu":10, "mem_mb":48, "disk_kbps":256, "lat_min":50, "lat_max":200, "crash":0.001, "startup_fail":0.001, "hang":0.001},
    {"name":"RBC_monitor_saude_1", "cpu":8, "mem_mb":24, "disk_kbps":8, "lat_min":100,"lat_max":300, "crash":0.001, "startup_fail":0.002, "hang":0.001},
    {"name":"RBC_monitor_saude_2", "cpu":8, "mem_mb":24, "disk_kbps":8, "lat_min":100,"lat_max":300, "crash":0.003, "startup_fail":0.002, "hang":0.001},
    {"name":"RBC_escritor_auditoria_1", "cpu":12, "mem_mb":80, "disk_kbps":512, "lat_min":30, "lat_max":120, "crash":0.001, "startup_fail":0.01, "hang":0.001},
    {"name":"RBC_escritor_auditoria_2", "cpu":12, "mem_mb":80, "disk_kbps":512, "lat_min":30, "lat_max":120, "crash":0.002, "startup_fail":0.01, "hang":0.001},
    {"name":"RBC_trabalhador_link_1", "cpu":35, "mem_mb":128, "disk_kbps":64, "lat_min":15, "lat_max":60, "crash":0.001, "startup_fail":0.05, "hang":0.02},
    {"name":"RBC_trabalhador_link_2", "cpu":35, "mem_mb":128, "disk_kbps":64, "lat_min":15, "lat_max":60, "crash":0.001, "startup_fail":0.01, "hang":0.005},
    {"name":"RBC_aquecedor_cache_1", "cpu":30, "mem_mb":160, "disk_kbps":8, "lat_min":10, "lat_max":35, "crash":0.001, "startup_fail":0.0012, "hang":0.01},
    {"name":"RBC_aquecedor_cache_2", "cpu":28, "mem_mb":160, "disk_kbps":8, "lat_min":10, "lat_max":35, "crash":0.003, "startup_fail":0.001, "hang":0.02},
    {"name":"RBC_sincronizacao_db_1", "cpu":18, "mem_mb":220, "disk_kbps":384, "lat_min":30, "lat_max":100, "crash":0.001, "startup_fail":0.00015,"hang":0.01},
    {"name":"RBC_sincronizacao_db_2", "cpu":18, "mem_mb":220, "disk_kbps":384, "lat_min":30, "lat_max":100, "crash":0.001, "startup_fail":0.001, "hang":0.01},
    {"name":"RBC_despacho_notificacao_1","cpu":22, "mem_mb":72, "disk_kbps":48, "lat_min":8, "lat_max":25, "crash":0.006, "startup_fail":0.01, "hang":0.002},
    {"name":"RBC_despacho_notificacao_2","cpu":22, "mem_mb":72, "disk_kbps":48, "lat_min":8, "lat_max":25, "crash":0.002, "startup_fail":0.001, "hang":0.01},
    {"name":"RBC_inferencia_ml_1", "cpu":65, "mem_mb":256, "disk_kbps":24, "lat_min":5, "lat_max":20, "crash":0.004, "startup_fail":0.01, "hang":0.03},
    {"name":"RBC_inferencia_ml_2", "cpu":62, "mem_mb":256, "disk_kbps":24, "lat_min":5, "lat_max":20, "crash":0.002, "startup_fail":0.01, "hang":0.002},
    {"name":"RBC_gerador_relatorio_1", "cpu":14, "mem_mb":144, "disk_kbps":640, "lat_min":40, "lat_max":160, "crash":0.001, "startup_fail":0.001, "hang":0.01},
    {"name":"RBC_gerador_relatorio_2", "cpu":14, "mem_mb":144, "disk_kbps":640, "lat_min":40, "lat_max":160, "crash":0.002, "startup_fail":0.001, "hang":0.02},
    {"name":"RBC_escaner_fraude_1", "cpu":55, "mem_mb":200, "disk_kbps":96, "lat_min":12, "lat_max":45, "crash":0.001, "startup_fail":0.001, "hang":0.08},
    {"name":"RBC_escaner_fraude_2", "cpu":55, "mem_mb":200, "disk_kbps":96, "lat_min":12, "lat_max":45, "crash":0.001, "startup_fail":0.001, "hang":0.01},
    {"name":"RBC_resumo_metricas_1","cpu":16, "mem_mb":96, "disk_kbps":300, "lat_min":25, "lat_max":110, "crash":0.001, "startup_fail":0.01, "hang":0.002},
    {"name":"RBC_resumo_metricas_2","cpu":16, "mem_mb":96, "disk_kbps":300, "lat_min":25, "lat_max":110, "crash":0.001, "startup_fail":0.001, "hang":0.0012},
    {"name":"RBC_cache_distribuido_1","cpu":40,"mem_mb":512,"disk_kbps":32,"lat_min":5,"lat_max":20,"crash":0.002,"startup_fail":0.002,"hang":0.01},
    {"name":"RBC_cache_distribuido_2","cpu":42,"mem_mb":512,"disk_kbps":32,"lat_min":5,"lat_max":20,"crash":0.002,"startup_fail":0.001,"hang":0.015},
    {"name":"RBC_agregador_logs_1","cpu":20,"mem_mb":128,"disk_kbps":1024,"lat_min":40,"lat_max":180,"crash":0.001,"startup_fail":0.003,"hang":0.002},
    {"name":"RBC_agregador_logs_2","cpu":22,"mem_mb":128,"disk_kbps":1024,"lat_min":40,"lat_max":180,"crash":0.002,"startup_fail":0.003,"hang":0.003},
    {"name":"RBC_indexador_busca_1","cpu":50,"mem_mb":256,"disk_kbps":512,"lat_min":20,"lat_max":80,"crash":0.003,"startup_fail":0.005,"hang":0.01},
    {"name":"RBC_indexador_busca_2","cpu":48,"mem_mb":256,"disk_kbps":512,"lat_min":20,"lat_max":80,"crash":0.002,"startup_fail":0.004,"hang":0.008},
    {"name":"RBC_api_gateway_1","cpu":35,"mem_mb":128,"disk_kbps":64,"lat_min":5,"lat_max":30,"crash":0.002,"startup_fail":0.02,"hang":0.005},
    {"name":"RBC_api_gateway_2","cpu":38,"mem_mb":128,"disk_kbps":64,"lat_min":5,"lat_max":30,"crash":0.002,"startup_fail":0.015,"hang":0.006},
    {"name":"RBC_balanceador_carga_1","cpu":25,"mem_mb":96,"disk_kbps":32,"lat_min":3,"lat_max":15,"crash":0.001,"startup_fail":0.01,"hang":0.002},
    {"name":"RBC_balanceador_carga_2","cpu":27,"mem_mb":96,"disk_kbps":32,"lat_min":3,"lat_max":15,"crash":0.001,"startup_fail":0.008,"hang":0.002},
    {"name":"RBC_processador_eventos_1","cpu":60,"mem_mb":192,"disk_kbps":128,"lat_min":10,"lat_max":50,"crash":0.004,"startup_fail":0.01,"hang":0.02},
    {"name":"RBC_processador_eventos_2","cpu":58,"mem_mb":192,"disk_kbps":128,"lat_min":10,"lat_max":50,"crash":0.003,"startup_fail":0.009,"hang":0.015},
    {"name":"RBC_fila_mensagens_1","cpu":30,"mem_mb":160,"disk_kbps":256,"lat_min":8,"lat_max":40,"crash":0.002,"startup_fail":0.003,"hang":0.01},
    {"name":"RBC_fila_mensagens_2","cpu":32,"mem_mb":160,"disk_kbps":256,"lat_min":8,"lat_max":40,"crash":0.002,"startup_fail":0.002,"hang":0.012},
    {"name":"RBC_normalizador_dados_1","cpu":28,"mem_mb":140,"disk_kbps":64,"lat_min":12,"lat_max":60,"crash":0.002,"startup_fail":0.004,"hang":0.006},
    {"name":"RBC_normalizador_dados_2","cpu":26,"mem_mb":140,"disk_kbps":64,"lat_min":12,"lat_max":60,"crash":0.002,"startup_fail":0.003,"hang":0.005},
    {"name":"RBC_validador_transacao_1","cpu":45,"mem_mb":180,"disk_kbps":48,"lat_min":6,"lat_max":25,"crash":0.003,"startup_fail":0.01,"hang":0.008},
    {"name":"RBC_validador_transacao_2","cpu":47,"mem_mb":180,"disk_kbps":48,"lat_min":6,"lat_max":25,"crash":0.002,"startup_fail":0.008,"hang":0.007},
    {"name":"RBC_executor_regras_1","cpu":52,"mem_mb":200,"disk_kbps":32,"lat_min":7,"lat_max":30,"crash":0.004,"startup_fail":0.01,"hang":0.02},
    {"name":"RBC_executor_regras_2","cpu":50,"mem_mb":200,"disk_kbps":32,"lat_min":7,"lat_max":30,"crash":0.003,"startup_fail":0.009,"hang":0.018},
    {"name":"RBC_coletor_metricas_1","cpu":15,"mem_mb":80,"disk_kbps":200,"lat_min":20,"lat_max":90,"crash":0.001,"startup_fail":0.002,"hang":0.002},
    {"name":"RBC_coletor_metricas_2","cpu":15,"mem_mb":80,"disk_kbps":200,"lat_min":20,"lat_max":90,"crash":0.001,"startup_fail":0.002,"hang":0.002},
    {"name":"RBC_exportador_dados_1","cpu":22,"mem_mb":160,"disk_kbps":700,"lat_min":50,"lat_max":200,"crash":0.002,"startup_fail":0.003,"hang":0.01},
    {"name":"RBC_exportador_dados_2","cpu":22,"mem_mb":160,"disk_kbps":700,"lat_min":50,"lat_max":200,"crash":0.002,"startup_fail":0.002,"hang":0.01},
    {"name":"RBC_backup_incremental_1","cpu":18,"mem_mb":256,"disk_kbps":900,"lat_min":100,"lat_max":400,"crash":0.001,"startup_fail":0.001,"hang":0.005},
    {"name":"RBC_backup_incremental_2","cpu":18,"mem_mb":256,"disk_kbps":900,"lat_min":100,"lat_max":400,"crash":0.001,"startup_fail":0.001,"hang":0.005},
    {"name":"RBC_reconciliador_1","cpu":34,"mem_mb":220,"disk_kbps":120,"lat_min":20,"lat_max":70,"crash":0.003,"startup_fail":0.006,"hang":0.01},
    {"name":"RBC_reconciliador_2","cpu":34,"mem_mb":220,"disk_kbps":120,"lat_min":20,"lat_max":70,"crash":0.002,"startup_fail":0.005,"hang":0.01},
    {"name":"RBC_scheduler_jobs_1","cpu":12,"mem_mb":96,"disk_kbps":32,"lat_min":30,"lat_max":120,"crash":0.001,"startup_fail":0.003,"hang":0.002},
    {"name":"RBC_scheduler_jobs_2","cpu":12,"mem_mb":96,"disk_kbps":32,"lat_min":30,"lat_max":120,"crash":0.001,"startup_fail":0.003,"hang":0.002},
    {"name":"RBC_limpeza_dados_1","cpu":20,"mem_mb":180,"disk_kbps":400,"lat_min":60,"lat_max":250,"crash":0.002,"startup_fail":0.002,"hang":0.008},
    {"name":"RBC_limpeza_dados_2","cpu":20,"mem_mb":180,"disk_kbps":400,"lat_min":60,"lat_max":250,"crash":0.002,"startup_fail":0.002,"hang":0.008},
    {"name":"RBC_preprocessador_ml_1","cpu":55,"mem_mb":300,"disk_kbps":80,"lat_min":10,"lat_max":40,"crash":0.004,"startup_fail":0.01,"hang":0.02},
    {"name":"RBC_preprocessador_ml_2","cpu":52,"mem_mb":300,"disk_kbps":80,"lat_min":10,"lat_max":40,"crash":0.003,"startup_fail":0.009,"hang":0.018}
]

TOTAL_PROFILES = len(profiles)
CPU_COUNT = 8
MEM_TOTAL = 16 * 1024**3
SWAP_TOTAL = 8 * 1024**3
DISK_TOTAL = 256 * 1024**3
# USER_NAME = "rbc_user"
# USER_NAME = "rbc_analista"
USER_NAME = "rbc_gerencia"
noise_level = 0.321

def get_scale_factor(ts):
    day = ts.weekday()
    hour = ts.hour

    if day == 6:
        base = 0.15
    elif day == 5:
        base = 0.50
    elif (6 <= hour <= 9) or (16 <= hour <= 19):
        base = 1.0
    elif 9 <= hour < 16:
        base = 0.75
    else:
        base = 0.30

    noise = np.random.uniform(-noise_level, noise_level)
    return max(0.01, base + (base * noise))

active = []
next_pid = 12000
process_rr = 0
disk_used_percent = 11.0

start = datetime(2026, 4, 1, 0, 0, 0)
end = start + timedelta(days=7)

timestamps = []
ts = start
while ts < end:
    timestamps.append(ts)
    ts += timedelta(minutes=10)

rows = []

maquina = 0

def get_mac_address():
    # return "60:c7:27:3e:4f:56"
    # return "06:71:a3:c2:10:07"
    # return "13:47:52:e1:8a:7f"
    # return "ae:b1:7d:b6:3a:19"
    return "ec:3f:b6:b9:ae:2f"

def spawn_process(profile, ts):
    global next_pid
    if random.random() < profile["startup_fail"]:
        return None

    proc = {
        "pid": next_pid,
        "name": profile["name"],
        "username": USER_NAME,
        "status": "running",
        "create_time": ts.timestamp(),
        "base_cpu": profile["cpu"],
        "mem_mb": max(8, int(random.gauss(profile["mem_mb"], max(4, profile["mem_mb"] * 0.08)))),
        "disk_kbps": max(1, int(random.gauss(profile["disk_kbps"], max(4, profile["disk_kbps"] * 0.10)))),
        "crash": profile["crash"],
        "hang": profile["hang"],
        "lat_min": profile["lat_min"],
        "lat_max": profile["lat_max"],
        "stuck": False,
        "started_at": ts,
        "cpu_percent": 0.0,
    }
    next_pid += 1
    return proc

for ts in timestamps:
    survivors = []
    for proc in active:
        if proc["stuck"]:
            if random.random() < 0.10:
                continue
            survivors.append(proc)
            continue

        if random.random() < proc["hang"]:
            proc["stuck"] = True
            proc["cpu_percent"] = 0.0
            proc["status"] = "stopped"
            survivors.append(proc)
            continue

        if random.random() < proc["crash"]:
            continue

        survivors.append(proc)

    active = survivors
    target = max(1, int(TOTAL_PROFILES * get_scale_factor(ts)))

    missing = target - len(active)
    if missing > 0:
        active_names = {p["name"] for p in active}
        for prof in profiles:
            if missing <= 0:
                break
            if prof["name"] not in active_names:
                proc = spawn_process(prof, ts)
                if proc:
                    active.append(proc)
                    active_names.add(prof["name"])
                    missing -= 1

        while missing > 0:
            prof = profiles[process_rr % len(profiles)]
            process_rr += 1
            proc = spawn_process(prof, ts)
            if proc:
                active.append(proc)
                missing -= 1

    elif len(active) > target:
        active = active[:target]

    lista_processos = []
    total_cpu_from_procs = 0.0
    total_mem_rss = 0
    taxa_leitura_disco_bytes_por_segundo = 0
    taxa_escrita_disco_bytes_por_segundo = 0
    latencias = []

    peak_boost = 1.15 if get_scale_factor(ts) >= 0.75 else 0.90

    for proc in active:
        if proc["stuck"]:
            proc_cpu = 0.0
            status = "stopped"
        else:
            proc_cpu = max(
                0.1,
                min(100.0, random.gauss(proc["base_cpu"] * peak_boost, max(1.0, proc["base_cpu"] * 0.20)))
            )
            status = "running"

        proc["cpu_percent"] = round(proc_cpu, 2)
        proc["status"] = status

        rss = int(proc["mem_mb"] * MB * random.uniform(0.80, 1.20))
        vms = int(rss * random.uniform(1.2, 1.8))
        read_bps = int(proc["disk_kbps"] * 1024 * random.uniform(0.20, 0.70))
        write_bps = int(proc["disk_kbps"] * 1024 * random.uniform(0.40, 1.10))
        memory_percent = (rss / MEM_TOTAL) * 100

        total_cpu_from_procs += proc_cpu
        total_mem_rss += rss
        taxa_leitura_disco_bytes_por_segundo += read_bps
        taxa_escrita_disco_bytes_por_segundo += write_bps
        latencias.append(random.randint(proc["lat_min"], proc["lat_max"]))

        lista_processos.append({
            "pid": proc["pid"],
            "name": proc["name"],
            "username": proc["username"],
            "status": proc["status"],
            "create_time": proc["create_time"],
            "cpu_percent": round(proc_cpu, 2),
            "memory_info": {
                "rss": rss,
                "vms": vms
            },
            "num_threads": random.randint(1, 24),
            "cmdline": [proc["name"], "--mode=simulado"],
            "exe": f"/opt/{proc['name']}",
            "cpu_times": {
                "user": round(random.uniform(1, 500), 2),
                "system": round(random.uniform(1, 120), 2)
            },
            "memory_percent": round(memory_percent, 2)
        })

    percentual_uso_cpu = min(100.0, (total_cpu_from_procs / CPU_COUNT) + random.uniform(0.2, 9.0))

    frequencia_cpu_minima_mhz = 1200
    frequencia_cpu_maxima_mhz = 4200
    frequencia_cpu_atual_mhz = int(
        frequencia_cpu_minima_mhz +
        (frequencia_cpu_maxima_mhz - frequencia_cpu_minima_mhz) *
        min(1.0, percentual_uso_cpu / 100.0) *
        random.uniform(0.85, 1.0)
    )

    disk_used_percent = min(
        88.0,
        max(45.0, disk_used_percent + (taxa_escrita_disco_bytes_por_segundo / (200 * 1024**2)) + random.uniform(0.125, 0.5))
    )

    disco_usado_bytes = int(DISK_TOTAL * (disk_used_percent / 100.0))
    disco_livre_bytes = DISK_TOTAL - disco_usado_bytes

    baseline_mem = int(12 * 1024**3)
    memoria_usada = min(MEM_TOTAL - int(2 * 1024**3), baseline_mem + total_mem_rss + random.randint(0, 512 * MB))
    memoria_disponivel_bytes = MEM_TOTAL - memoria_usada
    percentual_uso_ram = round((memoria_usada / MEM_TOTAL) * 100.0, 2)

    swap_usado_bytes = int(min(SWAP_TOTAL * 0.85, max(0, (memoria_usada - int(MEM_TOTAL * 0.75)) * 0.35 + random.randint(0, 256 * MB))))
    swap_livre_bytes = SWAP_TOTAL - swap_usado_bytes
    swap_entrada_bytes = int(random.uniform(0, 2 * MB))
    swap_saida_bytes = int(random.uniform(0, 2 * MB))
    percentual_uso_swap = round((swap_usado_bytes / SWAP_TOTAL) * 100.0, 2)

    latencia_ping_ms = int(np.mean(latencias)) if latencias else 0
    taxa_download_rede_bytes_por_segundo = int(random.uniform(2 * MB, 40 * MB))
    taxa_upload_rede_bytes_por_segundo = int(random.uniform(512 * 1024, 10 * MB))

    rows.append({
        "endereco_mac": get_mac_address(),
        "nome_usuario": USER_NAME,
        "percentual_uso_cpu": round(percentual_uso_cpu, 2),
        "frequencia_cpu_atual_mhz": frequencia_cpu_atual_mhz,
        "frequencia_cpu_minima_mhz": frequencia_cpu_minima_mhz,
        "frequencia_cpu_maxima_mhz": frequencia_cpu_maxima_mhz,
        "memoria_total_bytes": int(MEM_TOTAL),
        "memoria_disponivel_bytes": int(memoria_disponivel_bytes),
        "percentual_uso_ram": percentual_uso_ram,
        "swap_total_bytes": int(SWAP_TOTAL),
        "swap_usado_bytes": int(swap_usado_bytes),
        "swap_livre_bytes": int(swap_livre_bytes),
        "swap_entrada_bytes": int(swap_entrada_bytes),
        "swap_saida_bytes": int(swap_saida_bytes),
        "percentual_uso_swap": percentual_uso_swap,
        "disco_total_bytes": int(DISK_TOTAL),
        "disco_usado_bytes": int(disco_usado_bytes),
        "disco_livre_bytes": int(disco_livre_bytes),
        "percentual_uso_disco": round(disk_used_percent, 2),
        "taxa_leitura_disco_bytes_por_segundo": int(taxa_leitura_disco_bytes_por_segundo),
        "taxa_escrita_disco_bytes_por_segundo": int(taxa_escrita_disco_bytes_por_segundo),
        "latencia_ping_ms": latencia_ping_ms,
        "taxa_download_rede_bytes_por_segundo": int(taxa_download_rede_bytes_por_segundo),
        "taxa_upload_rede_bytes_por_segundo": int(taxa_upload_rede_bytes_por_segundo),
        "processos": str(lista_processos),
        "data_hora_iso": ts.isoformat()
    })

df = pd.DataFrame(rows, columns=[
    "endereco_mac",
    "nome_usuario",
    "percentual_uso_cpu",
    "frequencia_cpu_atual_mhz",
    "frequencia_cpu_minima_mhz",
    "frequencia_cpu_maxima_mhz",
    "memoria_total_bytes",
    "memoria_disponivel_bytes",
    "percentual_uso_ram",
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
    "taxa_leitura_disco_bytes_por_segundo",
    "taxa_escrita_disco_bytes_por_segundo",
    "latencia_ping_ms",
    "taxa_download_rede_bytes_por_segundo",
    "taxa_upload_rede_bytes_por_segundo",
    "processos",
    "data_hora_iso"
])













# df.to_csv("df.csv", index=False, encoding="utf-8")
# df.to_csv("df_1.csv", index=False, encoding="utf-8")
# df.to_csv("df_2.csv", index=False, encoding="utf-8")
# df.to_csv("df_3.csv", index=False, encoding="utf-8")
df.to_csv("df_4.csv", index=False, encoding="utf-8")
print("CSV gerado com sucesso: df.csv")