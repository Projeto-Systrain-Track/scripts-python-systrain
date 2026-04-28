import random
import subprocess
import time
from datetime import datetime
import numpy as np

PERFIS = [
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
    "RBC_resumo_metricas_1","RBC_resumo_metricas_2",
    "RBC_cache_distribuido_1","RBC_cache_distribuido_2",
    "RBC_agregador_logs_1","RBC_agregador_logs_2",
    "RBC_indexador_busca_1","RBC_indexador_busca_2",
    "RBC_api_gateway_1","RBC_api_gateway_2",
    "RBC_balanceador_carga_1","RBC_balanceador_carga_2",
    "RBC_processador_eventos_1","RBC_processador_eventos_2",
    "RBC_fila_mensagens_1","RBC_fila_mensagens_2",
    "RBC_normalizador_dados_1","RBC_normalizador_dados_2",
    "RBC_validador_transacao_1","RBC_validador_transacao_2",
    "RBC_executor_regras_1","RBC_executor_regras_2",
    "RBC_coletor_metricas_1","RBC_coletor_metricas_2",
    "RBC_exportador_dados_1","RBC_exportador_dados_2",
    "RBC_backup_incremental_1","RBC_backup_incremental_2",
    "RBC_reconciliador_1","RBC_reconciliador_2",
    "RBC_scheduler_jobs_1","RBC_scheduler_jobs_2",
    "RBC_limpeza_dados_1","RBC_limpeza_dados_2",
    "RBC_preprocessador_ml_1","RBC_preprocessador_ml_2"
]

processosFilhos = []

TOTAL_PERFIS = len(PERFIS)

nivelRuido = 0.4321

MIN_PROCESSOS = 1
MAX_PROCESSOS = TOTAL_PERFIS


def obterFatorEscala(ts: datetime) -> float:
    dia = ts.weekday()
    hora = ts.hour

    if dia == 6:
        base = 0.15
    elif dia == 5:
        base = 0.50
    elif (6 <= hora <= 9) or (16 <= hora <= 19):
        base = 1.0
    elif 9 <= hora < 16:
        base = 0.75
    else:
        base = 0.30

    ruido = np.random.uniform(-nivelRuido, nivelRuido)
    resultado = base + (base * ruido)
    return max(0.01, resultado)


def obterQuantidadeAlvoProcessos(ts: datetime) -> tuple[int, float]:
    escala = obterFatorEscala(ts)

    alvoBase = TOTAL_PERFIS * escala

    desvio = max(1.0, alvoBase * 0.08)
    alvo = int(round(np.random.normal(alvoBase, desvio)))

    alvo = max(MIN_PROCESSOS, min(MAX_PROCESSOS, alvo))
    return alvo, escala


def criarProcesso(nome: str, escala: float):
    cpuLoops = int(200_000 * (0.3 + escala))

    codigo = f'''
from setproctitle import setproctitle
import time, random

setproctitle("{nome}")

dados = bytearray(30 * 1024 * 1024)

while True:
    for _ in range({cpuLoops}):
        pass

    for i in range(0, len(dados), 4096):
        dados[i] = (dados[i] + 1) % 256

    time.sleep(random.uniform(0.05, 0.2))
'''

    return subprocess.Popen(
        ["python3", "-c", codigo],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def ajustarPopulacao(alvo: int, escala: float):
    global processosFilhos

    while len(processosFilhos) < alvo:
        nome = random.choice(PERFIS)
        p = criarProcesso(nome, escala)
        processosFilhos.append(p)

    while len(processosFilhos) > alvo:
        p = processosFilhos.pop(0)
        p.terminate()


def limparProcessos():
    global processosFilhos
    processosFilhos = [p for p in processosFilhos if p.poll() is None]


def encerrarTudo():
    global processosFilhos
    for p in processosFilhos:
        if p.poll() is None:
            p.terminate()

    time.sleep(1)

    for p in processosFilhos:
        if p.poll() is None:
            p.kill()

    processosFilhos = []


def main():
    try:
        while True:
            ts = datetime.now()
            alvo, escala = obterQuantidadeAlvoProcessos(ts)

            limparProcessos()
            ajustarPopulacao(alvo, escala)

            print("=" * 60)
            print(f"tempo: {ts}")
            print(f"fator escala: {escala:.4f}")
            print(f"processos alvo: {alvo}")
            print(f"processos ativos: {len(processosFilhos)}")

            time.sleep(25)

    except KeyboardInterrupt:
        pass
    finally:
        encerrarTudo()


if __name__ == "__main__":
    main()