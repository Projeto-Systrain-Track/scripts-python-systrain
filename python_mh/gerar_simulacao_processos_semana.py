import pandas as pd
import random
import math
import uuid
from datetime import datetime, timedelta

random.seed(42)

MB = 1024 * 1024


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
    {"name":"RBC_resumo_metricas_2","cpu":16, "mem_mb":96, "disk_kbps":300, "lat_min":25, "lat_max":110, "crash":0.001, "startup_fail":0.001, "hang":0.0012}
]


TOTAL_PROFILES = len(profiles)
CPU_COUNT = 16
MEM_TOTAL = 64 * 1024**3  
USER_NAME = "rbc_user"


def get_scale_factor(ts):
    day = ts.weekday()
    hour = ts.hour
    if day == 6:  

        return 0.15
    if day == 5:  

        return 0.50
    if (6 <= hour <= 9) or (16 <= hour <= 19):

        return 1.0
    if 9 <= hour <= 16:

        return 0.75
    return 0.30


active = []
next_pid = 12000
process_rr = 0
disk_used_percent = 61.0

start = datetime(2026, 4, 1, 0, 0, 0)
end = start + timedelta(days=14)
timestamps = []
ts = start
while ts < end:
    timestamps.append(ts)
    ts += timedelta(minutes=1)

rows = []

def spawn_process(profile, ts):
    global next_pid
    if random.random() < profile["startup_fail"]:
        return None
    proc = {
        "pid": next_pid,
        "name": profile["name"],
        "username": USER_NAME,
        "base_cpu": profile["cpu"],
        "mem_mb": max(8, int(random.gauss(profile["mem_mb"], max(4, profile["mem_mb"] * 0.08)))),
        "disk_kbps": max(1, int(random.gauss(profile["disk_kbps"], max(4, profile["disk_kbps"] * 0.10)))),
        "crash": profile["crash"],
        "hang": profile["hang"],
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
            else:
                continue

    elif len(active) > target:
        
        active = active[:target]

    
    process_infos = []
    total_cpu_from_procs = 0.0
    total_mem_rss = 0
    read_rate = 0
    write_rate = 0

    peak_boost = 1.15 if get_scale_factor(ts) >= 0.75 else 0.90
    for proc in active:
        if proc["stuck"]:
            proc_cpu = 0.0
        else:
            proc_cpu = max(0.1, min(100.0, random.gauss(proc["base_cpu"] * peak_boost, max(1.0, proc["base_cpu"] * 0.20))))
        proc["cpu_percent"] = round(proc_cpu, 2)

        rss = int(proc["mem_mb"] * MB * random.uniform(0.80, 1.20))
        vms = int(rss * random.uniform(1.2, 1.8))
        read_bps = int(proc["disk_kbps"] * 1024 * random.uniform(0.20, 0.70))
        write_bps = int(proc["disk_kbps"] * 1024 * random.uniform(0.40, 1.10))

        total_cpu_from_procs += proc_cpu
        total_mem_rss += rss
        read_rate += read_bps
        write_rate += write_bps

        process_infos.append({
            "pid": proc["pid"],
            "name": proc["name"],
            "username": proc["username"],
            "cpu_percent": round(proc_cpu, 2),
            "memory_info": {
                "rss": rss,
                "vms": vms
            }
        })


    host_cpu_noise = random.uniform(0.2, 9.0)
    cpu_percent_total = min(100.0, (total_cpu_from_procs / CPU_COUNT) + host_cpu_noise)
    freq_min = 1200
    freq_max = 4200
    freq_current = int(freq_min + (freq_max - freq_min) * min(1.0, cpu_percent_total / 100.0) * random.uniform(0.85, 1.0))
    disk_used_percent = min(88.0, max(45.0, disk_used_percent + (write_rate / (200 * 1024**2)) + random.uniform(0.125, 0.5)))
    baseline_mem = int(12 * 1024**3)
    mem_used = min(MEM_TOTAL - int(2 * 1024**3), baseline_mem + total_mem_rss + random.randint(0, 512 * MB))
    mem_available = MEM_TOTAL - mem_used
    memoria_percentual = (mem_available / MEM_TOTAL) * 100.0

    mac_num = uuid.getnode()
    mac_address = ':'.join(['{:02x}'.format((mac_num >> i) & 0xff) for i in range(0, 48, 8)][::-1])

    rows.append({
        "macAdress": mac_address,
        "usuario": USER_NAME,
        "porcentagem_uso_da_cpu": round(cpu_percent_total, 2),
        "frequencia_atual": int(freq_current),
        "frequencia_min": int(freq_min),
        "frequencia_max": int(freq_max),
        "porcentagem_uso_do_disco": round(disk_used_percent, 2),
        "read_rate_Bps": int(read_rate),
        "write_rate_Bps": int(write_rate),
        "memoria_percentual": int(memoria_percentual),
        "memoria_total": int(MEM_TOTAL),
        "memoria_livre": int(mem_available),
        "processos": str(process_infos),
        "data": ts.isoformat()
    })

df = pd.DataFrame(rows, columns=[
    "macAdress",
    "usuario",
    "porcentagem_uso_da_cpu",
    "frequencia_atual",
    "frequencia_min",
    "frequencia_max",
    "porcentagem_uso_do_disco",
    "read_rate_Bps",
    "write_rate_Bps",
    "memoria_percentual",
    "memoria_total",
    "memoria_livre",
    "processos",
    "data"
])

# $$$$$$$\  $$$$$$$\   $$$$$$\   $$$$$$\  $$\   $$\ $$$$$$$\  $$$$$$$$\       $$\      $$\  $$$$$$\  $$$$$$$\   $$$$$$\  $$$$$$\ 
# $$  __$$\ $$  __$$\ $$  __$$\ $$  __$$\ $$ |  $$ |$$  __$$\ $$  _____|      $$$\    $$$ |$$  __$$\ $$  __$$\ $$  __$$\ \_$$  _|
# $$ |  $$ |$$ |  $$ |$$ /  $$ |$$ /  \__|$$ |  $$ |$$ |  $$ |$$ |            $$$$\  $$$$ |$$ /  $$ |$$ |  $$ |$$ /  \__|  $$ |  
# $$$$$$$  |$$$$$$$  |$$ |  $$ |$$ |      $$ |  $$ |$$$$$$$  |$$$$$\          $$\$$\$$ $$ |$$$$$$$$ |$$$$$$$  |$$ |        $$ |  
# $$  ____/ $$  __$$< $$ |  $$ |$$ |      $$ |  $$ |$$  __$$< $$  __|         $$ \$$$  $$ |$$  __$$ |$$  __$$< $$ |        $$ |  
# $$ |      $$ |  $$ |$$ |  $$ |$$ |  $$\ $$ |  $$ |$$ |  $$ |$$ |            $$ |\$  /$$ |$$ |  $$ |$$ |  $$ |$$ |  $$\   $$ |  
# $$ |      $$ |  $$ | $$$$$$  |\$$$$$$  |\$$$$$$  |$$ |  $$ |$$$$$$$$\       $$ | \_/ $$ |$$ |  $$ |$$ |  $$ |\$$$$$$  |$$$$$$\ 
# \__|      \__|  \__| \______/  \______/  \______/ \__|  \__|\________|      \__|     \__|\__|  \__|\__|  \__| \______/ \______|
                                                                                                                               
                                                                                                                               
                                                                                                                               
# $$$$$$$\   $$$$$$\  $$$$$$$\   $$$$$$\        $$$$$$$\  $$\   $$\ $$\    $$\ $$$$$$\ $$$$$$$\   $$$$$$\   
# $$  __$$\ $$  __$$\ $$  __$$\ $$  __$$\       $$  __$$\ $$ |  $$ |$$ |   $$ |\_$$  _|$$  __$$\ $$  __$$\ 
# $$ |  $$ |$$ /  $$ |$$ |  $$ |$$ /  $$ |      $$ |  $$ |$$ |  $$ |$$ |   $$ |  $$ |  $$ |  $$ |$$ /  $$ |
# $$$$$$$  |$$$$$$$$ |$$$$$$$  |$$$$$$$$ |      $$ |  $$ |$$ |  $$ |\$$\  $$  |  $$ |  $$ |  $$ |$$$$$$$$ |
# $$  ____/ $$  __$$ |$$  __$$< $$  __$$ |      $$ |  $$ |$$ |  $$ | \$$\$$  /   $$ |  $$ |  $$ |$$  __$$ |
# $$ |      $$ |  $$ |$$ |  $$ |$$ |  $$ |      $$ |  $$ |$$ |  $$ |  \$$$  /    $$ |  $$ |  $$ |$$ |  $$ |
# $$ |      $$ |  $$ |$$ |  $$ |$$ |  $$ |      $$$$$$$  |\$$$$$$  |   \$  /   $$$$$$\ $$$$$$$  |$$ |  $$ |
# \__|      \__|  \__|\__|  \__|\__|  \__|      \_______/  \______/     \_/    \______|\_______/ \__|  \__|
                                                                                                                               
                                                                                                                               
                                                                                                                               
csv_path = "df.csv"
df.to_csv(csv_path, index=False, encoding="utf-8")
