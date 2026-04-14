import random
import subprocess
import time
from datetime import datetime

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


PROFILES = [
    "RBC_gerente_sessao_1","RBC_gerente_sessao_2",
    "RBC_calculo_rota_1","RBC_calculo_rota_2",
    "RBC_telemetria_1","RBC_telemetria_2",
    "RBC_monitor_saude_1","RBC_monitor_saude_2",
    "RBC_escritor_auditoria_1","RBC_escritor_auditoria_2",
    "RBC_trabalhador_link_1","RBC_trabalhador_link_2",
    "RBC_aquecedor_cache_1","RBC_aquecedor_cache_2",
    "RBC_sincronizacao_db_1","RBC_sincronizacao_db_2",
    "RBC_despacho_notificacao_1","RBC_despacho_notificacao_2",
    "RBC_inferencia_ml_1","RBC_inferencia_ml_2",
    "RBC_gerador_relatorio_1","RBC_gerador_relatorio_2",
    "RBC_escaner_fraude_1","RBC_escaner_fraude_2",
    "RBC_resumo_metricas_1","RBC_resumo_metricas_2"
]

children = []


BASE_MIN = 4
BASE_MAX = 20


def spawn(name, scale):
    cpu_loops = int(200_000 * (0.3 + scale))

    code = f"""
from setproctitle import setproctitle
import time, random

setproctitle("{name}")

data = bytearray(30 * 1024 * 1024)

while True:
    # CPU load (scaled)
    for _ in range({cpu_loops}):
        pass

    # memory touch
    for i in range(0, len(data), 4096):
        data[i] = (data[i] + 1) % 256

    time.sleep(random.uniform(0.05, 0.2))
"""

    return subprocess.Popen(
        ["python3", "-c", code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def adjust_population(scale):
    global children

    target = int(BASE_MIN + (BASE_MAX - BASE_MIN) * scale)


    while len(children) < target:
        name = random.choice(PROFILES)
        p = spawn(name, scale)
        children.append(p)

    while len(children) > target:
        p = children.pop(0)
        p.terminate()


def cleanup():
    global children
    children = [p for p in children if p.poll() is None]


def main():
    try:
        while True:
            ts = datetime.now()
            scale = get_scale_factor(ts)

            cleanup()
            adjust_population(scale)

            print("=" * 60)
            print(f"time: {ts}")
            print(f"scale factor: {scale}")
            print(f"target processes: {len(children)}")

            time.sleep(5)

    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()