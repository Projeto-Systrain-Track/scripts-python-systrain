from __future__ import annotations
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from pathlib import Path
import mysql.connector
from glob import glob
import pandas as pd
import numpy as np
import json
import ast
import os
load_dotenv()
try:
    columns = os.get_terminal_size().columns
except OSError:
    columns = 80
def lerVariavelAmbienteBooleana(nomeVariavel: str) -> bool:
    """
    Lê uma variável do .env
    serei honesta, essa parte pode ser removida, mas não confio,
    logo, adicionei erros de digitação para que de certo mesmo assim...
    """

    valorBruto = os.getenv(nomeVariavel)
    valorNormalizado = valorBruto.strip().lower()
    if valorNormalizado in {"1", "true", "yes", "sim", "on","sin", "sum", "om", "treu", "tru", "TRUE", "True", "FUNCIONA", "s"}:
        return True
    if valorNormalizado in {"0", "false", "no", "nao", "não", "off", "noa", "n", "não funciona", "NÃO FUNCIONA", "flase", "fales"}:
        return False
    
def lerVariavelAmbienteInteira(nomeVariavel: str) -> int:
    """
    Lê número inteiro do .env e evita que a ETL quebre
    """
    return int(os.getenv(nomeVariavel))


def lerVariavelAmbienteDecimal(nomeVariavel: str) -> float:
    """
    Lê número decimal do .env e usa o padrão quando não conseguir 
    """
    return float(os.getenv(nomeVariavel))

configuracaoMysql = {
    "host": os.getenv("MYSQL_HOST"),
    "port": int(os.getenv("MYSQL_PORT")),
    "user": os.getenv("MYSQL_USER"),
    "password": os.getenv("MYSQL_PASSWORD"),
    "database": os.getenv("MYSQL_DATABASE"),
}
limiteAlertaCpuProcesso = float(os.getenv("PROCESS_CPU_ALERT"))
limiteAlertaPercentualMemoriaProcesso = float(os.getenv("PROCESS_MEMORY_PERCENT_ALERT"))
limiteAlertaMemoriaResidenteMbProcesso = float(os.getenv("PROCESS_RSS_MB_ALERT"))
limiteAlertaThreadsProcesso = int(os.getenv("PROCESS_THREADS_ALERT"))
limiteMaximoProcessosPorLeitura = int(os.getenv("PROCESS_MAX_PER_READING", os.getenv("MAX_PROCESSES_PER_READING")))
limiteMinutosRbcOffline = float(os.getenv("RBC_OFFLINE_GAP_MINUTES"))
csvCompactoPadrao = os.getenv("COMPACT_CSV_DEFAULT").strip().lower()
indentacaoJsonPadrao = os.getenv("JSON_INDENT").strip()
linhas = int(os.getenv("LAST_N"))
prefixosProcessosAltaPrioridade = tuple(elemento.strip().lower() for elemento in os.getenv("HIGH_PRIORITY_PROCESS_PREFIXES").split(",")if elemento.strip())
limiteAlertaCpuProcessoAltaPrioridade = float(os.getenv("HIGH_PRIORITY_PROCESS_CPU_ALERT"))
limiteAlertaPercentualMemoriaProcessoAltaPrioridade = float(os.getenv("HIGH_PRIORITY_PROCESS_MEMORY_PERCENT_ALERT"))
limiteAlertaMemoriaResidenteMbProcessoAltaPrioridade = float(os.getenv("HIGH_PRIORITY_PROCESS_RSS_MB_ALERT"))
limitePicoCpuProcesso = float(os.getenv("PROCESS_CPU_SPIKE_ALERT"))
limitePicoMemoriaProcesso = float(os.getenv("PROCESS_MEMORY_SPIKE_ALERT"))
limiteCrescimentoMemoriaResidenteMbProcesso = float(os.getenv("PROCESS_RSS_GROWTH_MB_ALERT"))
palavrasChaveProcessosImportantes = tuple(elemento.strip().lower()for elemento in os.getenv("IMPORTANT_PROCESS_KEYWORDS").split(","))


def transformarParaDict(**argumentosNomeados):
    """
    Junta os argumentos nomeados em um dicionário.
    É basicamente um empacotador para quando a coluna de processos vem com cara de chamada Python, tipo transformarParaDict(chave=valor). A função só pega isso e devolve um dicionário normal.
    """
    return argumentosNomeados
def limparEnderecoMac(enderecoMac: Any) -> Any:
    """
    Dá uma arrumada no endereço MAC.
    Se vazio, deixa. Se preenchido, tira espaço e coloca tudo para minúsculo, para minha facilidade...
    """
    if pd.isna(enderecoMac):
        return enderecoMac
    return str(enderecoMac).strip().lower()
def converterBytesParaEquivalenteHumano(valor: Any) -> Optional[str]:
    """
    Transforma bytes em algo que uma pessoa consiga entende
    """
    if valor is None or pd.isna(valor):
        return None
    valor = float(valor)
    unidades = ["B", "KB", "MB", "GB", "TB", "PB"]
    indice = 0
    while valor >= 1024 and indice < len(unidades) - 1:
        valor /= 1024.0
        indice += 1
    return f"{valor:.2f} {unidades[indice]}"
def converterMegaHertzParaEquivalenteHumano(valor: Any) -> Optional[str]:
    """
    Transforma megahertz em megahertz(duh) ou gigahertz.
    """
    if valor is None or pd.isna(valor):
        return None
    valor = float(valor)
    if valor >= 1000:
        return f"{valor / 1000:.2f} GHz"
    return f"{valor:.2f} MHz"
def consertadorDeValoresBizarrosDoNumpy(valor: Any) -> Any:
    """
    Arruma aqueles tipos do numpy e do pandas antes de mandar para o JSON.
    O JSON não entende essas merda, então aqui troca por tipos comuns
    """
    if valor is None:
        return None
    if isinstance(valor, dict):
        return {chave: consertadorDeValoresBizarrosDoNumpy(valorInterno) for chave, valorInterno in valor.items()}
    if isinstance(valor, list):
        return [consertadorDeValoresBizarrosDoNumpy(valorInterno) for valorInterno in valor]
    if isinstance(valor, tuple):
        return [consertadorDeValoresBizarrosDoNumpy(valorInterno) for valorInterno in valor]
    if isinstance(valor, np.integer):
        return int(valor)
    if isinstance(valor, np.floating):
        if np.isnan(valor):
            return None
        return float(valor)
    if isinstance(valor, np.bool_):
        return bool(valor)
    if isinstance(valor, np.ndarray):
        return valor.tolist()
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
def separarProcessos(textoBrutoProcessos: Any) -> List[dict]:
    """
    Pega a coluna de processos e tenta transformar em uma lista de dicionários.
    Também aceita nomes comuns do psutil, tipo pmem(...) e pcputimes(...), porque alguns CSVs vêm desse jeito.
    """
    if textoBrutoProcessos is None:
        return []
    if isinstance(textoBrutoProcessos, list):
        return [processoItem for processoItem in textoBrutoProcessos if isinstance(processoItem, dict)]
    try:
        if pd.isna(textoBrutoProcessos):
            return []
    except Exception:
        pass
    textoBrutoProcessos = str(textoBrutoProcessos).strip()
    if not textoBrutoProcessos:
        return []
    #tudo acima é "vazio = retorna, vazio = retorna"
    #com alguns dos csvs
    #sim, apenas alguns, essa merda não lia se não tivesse essa segurança
    #mas ainda formatava igual com o ast.literal 
    #AAAAA
    try:
        processosSeparados = ast.literal_eval(textoBrutoProcessos)
    except Exception:
        funcoesPermitidas = {
            "transformarParaDict": transformarParaDict,
            "transformarParaDict": transformarParaDict,
            "pmem": transformarParaDict,
            "pfullmem": transformarParaDict,
            "pcputimes": transformarParaDict,
            "pthread": transformarParaDict,
            "popenfile": transformarParaDict,
            "pconn": transformarParaDict,
            "sconn": transformarParaDict,
            "addr": transformarParaDict,
        }
        try:
            processosSeparados = eval(
                textoBrutoProcessos,
                {"__builtins__": {}},
                funcoesPermitidas,
            )
        except Exception:
            return []
    if isinstance(processosSeparados, list):
        return [processoItem for processoItem in processosSeparados if isinstance(processoItem, dict)]
    return []
def classificarSaudeMaquina(pontuacao: Any) -> Optional[str]:
    """
    Traduz o score da máquina para uma criticidade mais fácil de ler.
    Quanto maior o score, pior a situação. Simples assim.
    """
    if pontuacao is None or pd.isna(pontuacao):
        return None
    pontuacao = float(pontuacao)
    if pontuacao > 85:
        return "CRITICO"
    if pontuacao > 70:
        return "ALTO"
    if pontuacao > 50:
        return "MODERADO"
    return "BAIXO"
def limparLinhaComandoProcessos(linhaComando: Any) -> Optional[List[Any] | str]:
    """
    Limpa a linha de comando do processo.
    A ideia é tirar lixo tipo nulo, NaN, texto vazio e afins, porque ninguém merece
    """
    if linhaComando is None:
        return None
    try:
        if pd.isna(linhaComando):
            return None
    except Exception:
        pass
    if isinstance(linhaComando, list):
        processoLimpo = []
        for elemento in linhaComando:
            if elemento is None:
                continue
            try:
                if pd.isna(elemento):
                    continue
            except Exception:
                pass
            if isinstance(elemento, str) and elemento.strip() == "":
                continue
            processoLimpo.append(consertadorDeValoresBizarrosDoNumpy(elemento))
        return processoLimpo or None
    if isinstance(linhaComando, str):
        linhaComando = linhaComando.strip()
        return linhaComando or None
    return consertadorDeValoresBizarrosDoNumpy(linhaComando)
def limparProcessos(processo: dict) -> dict:
    """
    Deixa um processo mais apresentável para exportar.
    Mantém o que importa e remove a linha de comando quando, depois da limpeza, ela não tem mais nada útil.
    """
    processoLimpo = consertadorDeValoresBizarrosDoNumpy(processo.copy())
    linhaComandoLimpa = limparLinhaComandoProcessos(processoLimpo.get("cmdline"))
    if linhaComandoLimpa is None:
        processoLimpo.pop("cmdline", None)
    else:
        processoLimpo["cmdline"] = linhaComandoLimpa
    return processoLimpo
def limparProcessosParaSaida(processos: Any) -> List[dict]:
    """
    Pega a coluna de processos e devolve tudo já limpinho para sair no arquivo final.
    """
    return [limparProcessos(processo) for processo in separarProcessos(processos) if isinstance(processo, dict)]
def buscarProcessoPorTexto(processo: dict) -> str:
    """
    Monta um textão pesquisável do processo.
    Serve como rede de segurança quando não dá para confiar só no identificador do processo. Aí usamos nome, executável e linha de comando para tentar reconhecer o bendito.
    """
    nomeProcesso = str(processo.get("name") or "").lower()
    executavelProcesso = str(processo.get("exe") or "").lower()
    linhaComando = limparLinhaComandoProcessos(processo.get("cmdline"))
    if isinstance(linhaComando, list):
        textoLinhaComando = " ".join(str(argumentoLinhaComando) for argumentoLinhaComando in linhaComando if argumentoLinhaComando).lower()
    else:
        textoLinhaComando = str(linhaComando or "").lower()
    return f"{nomeProcesso} {executavelProcesso} {textoLinhaComando}".strip()
def processoPossuiPrioridade(processo: dict, limitesComponentes: Optional[dict] = None) -> bool:
    """
    Confere se o processo merece atenção especial.
    Primeiro usa o PRS_STX do banco. Se não tiver, usa HIGH_PRIORITY_PROCESS_PREFIXES do .env.
    """
    textoProcesso = buscarProcessoPorTexto(processo)
    nomeProcesso = str(processo.get("name") or "").lower()
    prefixoBanco = pegarValorComponenteTexto(limitesComponentes, "PRS_STX")
    if prefixoBanco:
        prefixos = tuple(elemento.strip().lower() for elemento in str(prefixoBanco).split(",") if elemento.strip())
    else:
        prefixos = prefixosProcessosAltaPrioridade
    return any(nomeProcesso.startswith(prefixo) or prefixo in textoProcesso for prefixo in prefixos)
def valoresNumericosDosProcessos(processo: dict) -> dict:
    """
    Puxa os números que realmente importam para avaliar o processo.
    Aqui ficam processador, memória, quantidade de threads e memória residente em bytes e megabytes.
    """
    informacoesMemoria = processo.get("memory_info") or {}
    memoriaResidenteBytes = informacoesMemoria.get("rss") or 0
    return {
        "cpu_percent": float(processo.get("cpu_percent") or 0),
        "memory_percent": float(processo.get("memory_percent") or 0),
        "num_threads": int(processo.get("num_threads") or 0),
        "rss_bytes": float(memoriaResidenteBytes or 0),
        "rss_mb": float(memoriaResidenteBytes or 0) / 1024 / 1024,
    }
def identificarProcesso(processo: dict) -> str:
    """
    Cria uma identificação mais firme para comparar o processo entre leituras.
    Quando tem identificador e horário de criação, usa isso. Quando não tem, usa nome, executável e linha de comando resumida.
    """
    nomeProcesso = str(processo.get("name") or "").lower()
    identificadorProcesso = processo.get("pid")
    horarioCriacaoProcesso = processo.get("create_time")
    executavelProcesso = str(processo.get("exe") or "").lower()
    linhaComando = limparLinhaComandoProcessos(processo.get("cmdline"))
    if isinstance(linhaComando, list):
        textoLinhaComando = " ".join(str(argumentoLinhaComando) for argumentoLinhaComando in linhaComando if argumentoLinhaComando).lower()
    else:
        textoLinhaComando = str(linhaComando or "").lower()
    if identificadorProcesso is not None and horarioCriacaoProcesso is not None:
        return f"pid:{identificadorProcesso}|created:{horarioCriacaoProcesso}|name:{nomeProcesso}"
    return f"name:{nomeProcesso}|exe:{executavelProcesso}|cmd:{textoLinhaComando[:180]}"
def motivosAlertasDosProcessos(processo: dict, valoresAnteriores: Optional[dict] = None, limitesComponentes: Optional[dict] = None) -> List[str]:
    """
    Monta a lista de motivos pelos quais um processo virou alerta.
    Usa limites do banco para PRS_CPU_PER, PRS_RAM_PER, PRS_RAM_USE, PRS_CPU_THR e PRS_STX.
    Se o banco não tiver o limite, usa o .env como fallback.
    """
    valoresProcesso = valoresNumericosDosProcessos(processo)
    textoPesquisavelProcesso = buscarProcessoPorTexto(processo)
    processoAltaPrioridade = processoPossuiPrioridade(processo, limitesComponentes=limitesComponentes)
    limiteCpuAtual = pegarLimiteComponente(
        limitesComponentes,
        "PRS_CPU_PER",
        "limite_alerta",
        limiteAlertaCpuProcessoAltaPrioridade if processoAltaPrioridade else limiteAlertaCpuProcesso,
    )
    limiteMemoriaAtual = pegarLimiteComponente(
        limitesComponentes,
        "PRS_RAM_PER",
        "limite_alerta",
        limiteAlertaPercentualMemoriaProcessoAltaPrioridade if processoAltaPrioridade else limiteAlertaPercentualMemoriaProcesso,
    )
    limiteMemoriaResidenteAtual = pegarLimiteComponente(
        limitesComponentes,
        "PRS_RAM_USE",
        "limite_alerta",
        limiteAlertaMemoriaResidenteMbProcessoAltaPrioridade if processoAltaPrioridade else limiteAlertaMemoriaResidenteMbProcesso,
    )
    limiteThreadsAtual = pegarLimiteComponente(
        limitesComponentes,
        "PRS_CPU_THR",
        "limite_alerta",
        limiteAlertaThreadsProcesso,
    )
    limiteCpuAtual = float(limiteCpuAtual)
    limiteMemoriaAtual = float(limiteMemoriaAtual)
    limiteMemoriaResidenteAtual = float(limiteMemoriaResidenteAtual)
    limiteThreadsAtual = float(limiteThreadsAtual)
    motivosAlerta = []
    if processoAltaPrioridade:
        motivosAlerta.append("processo_rbc_alta_prioridade")
    if valoresProcesso["cpu_percent"] >= limiteCpuAtual:
        motivosAlerta.append(f"cpu_percent >= {limiteCpuAtual:g}")
    if valoresProcesso["memory_percent"] >= limiteMemoriaAtual:
        motivosAlerta.append(f"memory_percent >= {limiteMemoriaAtual:g}")
    if valoresProcesso["rss_mb"] >= limiteMemoriaResidenteAtual:
        motivosAlerta.append(f"rss_mb >= {limiteMemoriaResidenteAtual:g}")
    if valoresProcesso["num_threads"] >= limiteThreadsAtual:
        motivosAlerta.append(f"num_threads >= {limiteThreadsAtual:g}")
    if valoresAnteriores:
        variacaoCpu = valoresProcesso["cpu_percent"] - float(valoresAnteriores.get("cpu_percent") or 0)
        variacaoMemoria = valoresProcesso["memory_percent"] - float(valoresAnteriores.get("memory_percent") or 0)
        variacaoMemoriaResidente = valoresProcesso["rss_mb"] - float(valoresAnteriores.get("rss_mb") or 0)
        multiplicadorPico = 0.5 if processoAltaPrioridade else 1.0
        if variacaoCpu >= limitePicoCpuProcesso * multiplicadorPico:
            motivosAlerta.append(f"anomalia_cpu_delta >= {limitePicoCpuProcesso * multiplicadorPico:g}")
        if variacaoMemoria >= limitePicoMemoriaProcesso * multiplicadorPico:
            motivosAlerta.append(f"anomalia_memory_percent_delta >= {limitePicoMemoriaProcesso * multiplicadorPico:g}")
        if variacaoMemoriaResidente >= limiteCrescimentoMemoriaResidenteMbProcesso * multiplicadorPico:
            motivosAlerta.append(f"anomalia_rss_growth_mb >= {limiteCrescimentoMemoriaResidenteMbProcesso * multiplicadorPico:g}")
    if any(palavraChave in textoPesquisavelProcesso for palavraChave in palavrasChaveProcessosImportantes):
        if (
            valoresProcesso["cpu_percent"] >= limiteCpuAtual / 2
            or valoresProcesso["memory_percent"] >= limiteMemoriaAtual / 2
            or valoresProcesso["rss_mb"] >= limiteMemoriaResidenteAtual / 2
        ):
            motivosAlerta.append("processo_importante_com_consumo_relevante")
    if processoAltaPrioridade and motivosAlerta == ["processo_rbc_alta_prioridade"]:
        return []
    return motivosAlerta
def alertaProcessosCarga(processo: dict, motivosAlerta: List[str], valoresAnteriores: Optional[dict] = None, limitesComponentes: Optional[dict] = None) -> dict:
    """
    Monta o alerta do processo usando limites do banco quando disponíveis.
    """
    informacoesMemoria = processo.get("memory_info") or {}
    temposCpu = processo.get("cpu_times") or {}
    valoresProcesso = valoresNumericosDosProcessos(processo)
    memoriaVirtualBytes = informacoesMemoria.get("vms")
    valoresAnteriores = valoresAnteriores or {}
    variacaoCpu = valoresProcesso["cpu_percent"] - float(valoresAnteriores.get("cpu_percent") or 0) if valoresAnteriores else None
    variacaoMemoria = valoresProcesso["memory_percent"] - float(valoresAnteriores.get("memory_percent") or 0) if valoresAnteriores else None
    variacaoMemoriaResidente = valoresProcesso["rss_mb"] - float(valoresAnteriores.get("rss_mb") or 0) if valoresAnteriores else None
    processoAltaPrioridade = processoPossuiPrioridade(processo, limitesComponentes=limitesComponentes)
    limiteCpuAtual = float(pegarLimiteComponente(limitesComponentes, "PRS_CPU_PER", "limite_alerta", limiteAlertaCpuProcessoAltaPrioridade if processoAltaPrioridade else limiteAlertaCpuProcesso))
    limiteMemoriaAtual = float(pegarLimiteComponente(limitesComponentes, "PRS_RAM_PER", "limite_alerta", limiteAlertaPercentualMemoriaProcessoAltaPrioridade if processoAltaPrioridade else limiteAlertaPercentualMemoriaProcesso))
    limiteMemoriaResidenteAtual = float(pegarLimiteComponente(limitesComponentes, "PRS_RAM_USE", "limite_alerta", limiteAlertaMemoriaResidenteMbProcessoAltaPrioridade if processoAltaPrioridade else limiteAlertaMemoriaResidenteMbProcesso))
    limiteThreadsAtual = float(pegarLimiteComponente(limitesComponentes, "PRS_CPU_THR", "limite_alerta", limiteAlertaThreadsProcesso))
    pontuacaoAnomalia = 0.0
    pontuacaoAnomalia += max(valoresProcesso["cpu_percent"] / max(limiteCpuAtual, 1), 0)
    pontuacaoAnomalia += max(valoresProcesso["memory_percent"] / max(limiteMemoriaAtual, 0.1), 0)
    pontuacaoAnomalia += max(valoresProcesso["rss_mb"] / max(limiteMemoriaResidenteAtual, 1), 0)
    pontuacaoAnomalia += max(valoresProcesso["num_threads"] / max(limiteThreadsAtual, 1), 0)
    if variacaoCpu is not None:
        pontuacaoAnomalia += max(variacaoCpu / max(limitePicoCpuProcesso, 1), 0) * 2
    if variacaoMemoria is not None:
        pontuacaoAnomalia += max(variacaoMemoria / max(limitePicoMemoriaProcesso, 0.1), 0) * 2
    if variacaoMemoriaResidente is not None:
        pontuacaoAnomalia += max(variacaoMemoriaResidente / max(limiteCrescimentoMemoriaResidenteMbProcesso, 1), 0) * 2
    if processoAltaPrioridade:
        pontuacaoAnomalia *= 2
    return {
        "pid": consertadorDeValoresBizarrosDoNumpy(processo.get("pid")),
        "name": consertadorDeValoresBizarrosDoNumpy(processo.get("name")),
        "alta_prioridade": processoAltaPrioridade,
        "username": consertadorDeValoresBizarrosDoNumpy(processo.get("username")),
        "status": consertadorDeValoresBizarrosDoNumpy(processo.get("status")),
        "cpu_percent": consertadorDeValoresBizarrosDoNumpy(processo.get("cpu_percent")),
        "memory_percent": consertadorDeValoresBizarrosDoNumpy(processo.get("memory_percent")),
        "rss_mb": round(valoresProcesso["rss_mb"], 2),
        "rss_human": converterBytesParaEquivalenteHumano(valoresProcesso["rss_bytes"]),
        "vms_human": converterBytesParaEquivalenteHumano(memoriaVirtualBytes),
        "num_threads": consertadorDeValoresBizarrosDoNumpy(processo.get("num_threads")),
        "cmdline": limparLinhaComandoProcessos(processo.get("cmdline")),
        "exe": consertadorDeValoresBizarrosDoNumpy(processo.get("exe")),
        "create_time": (
            pd.to_datetime(processo.get("create_time"), unit="s", errors="coerce").isoformat()
            if processo.get("create_time") else None
        ),
        "cpu_times": {
            "user": consertadorDeValoresBizarrosDoNumpy(temposCpu.get("user")),
            "system": consertadorDeValoresBizarrosDoNumpy(temposCpu.get("system")),
        },
        "limites_usados": {
            "PRS_CPU_PER": limiteCpuAtual,
            "PRS_RAM_PER": limiteMemoriaAtual,
            "PRS_RAM_USE": limiteMemoriaResidenteAtual,
            "PRS_CPU_THR": limiteThreadsAtual,
            "PRS_STX": pegarValorComponenteTexto(limitesComponentes, "PRS_STX", prefixosProcessosAltaPrioridade),
        },
        "anomalias": {
            "cpu_delta_desde_leitura_anterior": round(variacaoCpu, 4) if variacaoCpu is not None else None,
            "memory_percent_delta_desde_leitura_anterior": round(variacaoMemoria, 4) if variacaoMemoria is not None else None,
            "rss_growth_mb_desde_leitura_anterior": round(variacaoMemoriaResidente, 2) if variacaoMemoriaResidente is not None else None,
            "score_anomalia_processo": round(pontuacaoAnomalia, 4),
        },
        "motivos_alerta": motivosAlerta,
    }
def chaveOrdenacaoProcessoAlerta(processoItem: dict) -> tuple:
    """
    Monta a chave usada para ordenar processos em alerta.
    Fica separado em uma função normal para não precisar usar lambda no sort.
    """
    return (
        bool(processoItem.get("alta_prioridade")),
        float((processoItem.get("anomalias") or {}).get("score_anomalia_processo") or 0),
        float(processoItem.get("cpu_percent") or 0),
        float(processoItem.get("memory_percent") or 0),
        float(processoItem.get("rss_mb") or 0),
    )
def chaveOrdenacaoRbcJson(elemento: dict) -> str:
    """Ordena RBC pelo id sem precisar usar lambda."""
    return str(elemento.get("id_rbc") or "")
def chaveOrdenacaoLinhaJson(elemento: dict) -> str:
    """Ordena linha pelo id ou pelo nome sem precisar usar lambda."""
    return str(elemento.get("id_linha") or elemento.get("nome_linha") or "")
def chaveOrdenacaoEmpresaJson(elemento: dict) -> str:
    """Ordena empresa pelo id ou pelo nome sem precisar usar lambda."""
    return str(elemento.get("id_empresa") or elemento.get("nome_empresa") or "")
def processosUteis(processos: List[dict], limitesComponentes: Optional[dict] = None) -> List[dict]:
    """
    Escolhe processos interessantes quando não tem histórico para comparar.
    Também usa limites de processo do banco quando eles estiverem disponíveis.
    """
    processosSelecionados = []
    for processo in processos:
        if not isinstance(processo, dict):
            continue
        motivosAlerta = motivosAlertasDosProcessos(processo, limitesComponentes=limitesComponentes)
        if motivosAlerta:
            processosSelecionados.append(alertaProcessosCarga(processo, motivosAlerta, limitesComponentes=limitesComponentes))
    processosSelecionados.sort(
        key=chaveOrdenacaoProcessoAlerta,
        reverse=True,
    )
    return processosSelecionados[:limiteMaximoProcessosPorLeitura]
def criarColunaAlertaProcessos(tabelaDados: pd.DataFrame) -> pd.DataFrame:
    """
    Cria a coluna com os processos em alerta para cada leitura.
    Usa limites vindos do banco por RBC e faz fallback para o .env.
    """
    if tabelaDados.empty:
        resultado = tabelaDados.copy()
        resultado["processos_alerta_priorizados"] = [[] for _ in range(len(resultado))]
        return resultado
    resultado = tabelaDados.copy()
    resultado["data_hora_iso"] = pd.to_datetime(resultado["data_hora_iso"], errors="coerce")
    if "limites_componentes" not in resultado.columns:
        resultado["limites_componentes"] = [{} for _ in range(len(resultado))]
    colunaAgrupamento = "id_rbc" if "id_rbc" in resultado.columns else "endereco_mac"
    alertasPorIndice: Dict[Any, List[dict]] = {indice: [] for indice in resultado.index}
    valoresAnterioresPorChave: Dict[tuple, dict] = {}
    for indice, linhaDados in resultado.sort_values([colunaAgrupamento, "data_hora_iso"]).iterrows():
        chaveRbc = linhaDados.get(colunaAgrupamento)
        limitesComponentes = linhaDados.get("limites_componentes") or {}
        alertasDaLinha = []
        for processo in linhaDados.get("processos_parsed", []) or []:
            if not isinstance(processo, dict):
                continue
            identidadeProcesso = identificarProcesso(processo)
            chaveEstadoProcesso = (chaveRbc, identidadeProcesso)
            valoresAnteriores = valoresAnterioresPorChave.get(chaveEstadoProcesso)
            motivosAlerta = motivosAlertasDosProcessos(
                processo,
                valoresAnteriores=valoresAnteriores,
                limitesComponentes=limitesComponentes,
            )
            if motivosAlerta:
                alertasDaLinha.append(
                    alertaProcessosCarga(
                        processo,
                        motivosAlerta,
                        valoresAnteriores=valoresAnteriores,
                        limitesComponentes=limitesComponentes,
                    )
                )
            valoresAnterioresPorChave[chaveEstadoProcesso] = valoresNumericosDosProcessos(processo)
        alertasDaLinha.sort(
            key=chaveOrdenacaoProcessoAlerta,
            reverse=True,
        )
        alertasPorIndice[indice] = alertasDaLinha[:limiteMaximoProcessosPorLeitura]
    processosAlertaPriorizados = []
    for indice in resultado.index:
        processosAlertaPriorizados.append(alertasPorIndice.get(indice, []))
    resultado["processos_alerta_priorizados"] = processosAlertaPriorizados
    return resultado
def carregarCsvLocal(caminhoCsv: str, separarColunaProcessos: bool = True, colunasParaUsar: Optional[List[str]] = None) -> pd.DataFrame:
    """
    Carrega o CSV local e já dá aquela primeira organizada.
    Também pode separar a coluna de processos. Se quiser rodar mais rápido e não ligar para alerta de processo, dá para pular essa parte.
    """
    parametrosLeitura = {"low_memory": False}
    # print(linhas)
    num_lines = sum(1 for line in open(caminhoCsv))
    tabelaDados = pd.read_csv(caminhoCsv, skiprows=range(1, num_lines - linhas), **parametrosLeitura)
    if colunasParaUsar:
        colunasExistentesParaUsar = []
        for coluna in colunasParaUsar:
            if coluna in tabelaDados.columns:
                colunasExistentesParaUsar.append(coluna)
        tabelaDados = tabelaDados[colunasExistentesParaUsar]
    colunasObrigatorias = ["endereco_mac", "data_hora_iso"]
    colunasAusentes = [coluna for coluna in colunasObrigatorias if coluna not in tabelaDados.columns]
    if colunasAusentes:
        raise ValueError(f"Colunas obrigatórias ausentes no CSV: {', '.join(colunasAusentes)}")
    enderecosMacLimpos = []
    for enderecoMac in tabelaDados["endereco_mac"]:
        enderecosMacLimpos.append(limparEnderecoMac(enderecoMac))
    tabelaDados["endereco_mac"] = enderecosMacLimpos
    tabelaDados["data_hora_iso"] = pd.to_datetime(tabelaDados["data_hora_iso"], errors="coerce")
    colunasNumericas = [
        "percentual_uso_cpu", "memoria_total_bytes", "memoria_disponivel_bytes",
        "percentual_uso_ram", "swap_total_bytes", "swap_usado_bytes", "swap_livre_bytes",
        "swap_entrada_bytes", "swap_saida_bytes", "percentual_uso_swap",
        "disco_total_bytes", "disco_usado_bytes", "disco_livre_bytes", "percentual_uso_disco",
        "frequencia_cpu_atual_mhz", "frequencia_cpu_minima_mhz", "frequencia_cpu_maxima_mhz",
        "taxa_leitura_disco_bytes_por_segundo", "taxa_escrita_disco_bytes_por_segundo",
        "latencia_ping_ms", "taxa_download_rede_bytes_por_segundo",
        "taxa_upload_rede_bytes_por_segundo",
    ]
    for coluna in colunasNumericas:
        if coluna in tabelaDados.columns:
            tabelaDados[coluna] = pd.to_numeric(tabelaDados[coluna], errors="coerce", downcast="float")
    if separarColunaProcessos and "processos" in tabelaDados.columns:
        processosSeparadosPorLinha = []
        for textoProcessos in tabelaDados["processos"]:
            processosSeparadosPorLinha.append(separarProcessos(textoProcessos))
        tabelaDados["processos_parsed"] = processosSeparadosPorLinha
    else:
        processosVaziosPorLinha = []
        for _ in range(len(tabelaDados)):
            processosVaziosPorLinha.append([])
        tabelaDados["processos_parsed"] = processosVaziosPorLinha
    return tabelaDados
def obterConexaoMysql():
    """
    Abre a conexão com o MySQL usando o que estiver configurado no ambiente.
    """
    if mysql is None:
        raise RuntimeError("mysql-connector-python não está instalado")
    return mysql.connector.connect(**configuracaoMysql)


def separarDefinicaoComponente(definicao: Any) -> dict:
    if definicao is None:
        return {}
    definicao = str(definicao).strip()
    if not definicao:
        return {}
    if "=" not in definicao:
        return {"valor": definicao}
    resultado = {}
    for pedaco in definicao.split(";"):
        pedaco = pedaco.strip()
        if not pedaco or "=" not in pedaco:
            continue
        chave, valor = pedaco.split("=", 1)
        chave = chave.strip()
        valor = valor.strip()
        try:
            resultado[chave] = float(valor)
        except Exception:
            resultado[chave] = valor
    return resultado


def buscarLimitesComponentesRbc(idsRbc: List[Any]) -> pd.DataFrame:
    idsLimpos = []
    for idRbc in idsRbc:
        if idRbc is None:
            continue
        try:
            if pd.isna(idRbc):
                continue
        except Exception:
            pass
        try:
            idsLimpos.append(int(idRbc))
        except Exception:
            pass
    idsLimpos = sorted(set(idsLimpos))
    if not idsLimpos:
        return pd.DataFrame(columns=["id_rbc", "limites_componentes"])
    conexao = obterConexaoMysql()
    try:
        cursor = conexao.cursor(dictionary=True)
        marcadoresParametros = ", ".join(["%s"] * len(idsLimpos))
        consultaSql = f"""
            SELECT
                rc.fkRbc AS id_rbc,
                c.idComponente AS id_componente,
                c.nome AS codigo_componente,
                c.tipo AS tipo_componente,
                c.parametros AS parametros,
                c.unidade AS unidade,
                rc.definicao AS definicao
            FROM rbcComponente rc
            JOIN componente c ON c.idComponente = rc.fkComponente
            WHERE rc.fkRbc IN ({marcadoresParametros})
        """
        cursor.execute(consultaSql, idsLimpos)
        linhasConsulta = cursor.fetchall()
        limitesPorRbc = {}
        for linha in linhasConsulta:
            idRbc = linha.get("id_rbc")
            codigoComponente = str(linha.get("codigo_componente") or "").strip()
            if not codigoComponente:
                continue
            if idRbc not in limitesPorRbc:
                limitesPorRbc[idRbc] = {}
            definicaoSeparada = separarDefinicaoComponente(linha.get("definicao"))
            limitesPorRbc[idRbc][codigoComponente] = {
                "id_componente": linha.get("id_componente"),
                "tipo_componente": linha.get("tipo_componente"),
                "parametros": linha.get("parametros"),
                "unidade": linha.get("unidade"),
                "definicao": linha.get("definicao"),
                "limite_alerta": definicaoSeparada.get("limite_alerta"),
                "limite_critico": definicaoSeparada.get("limite_critico"),
                "valor": definicaoSeparada.get("valor"),
            }
        linhasLimites = []
        for idRbc, limites in limitesPorRbc.items():
            linhasLimites.append({"id_rbc": idRbc, "limites_componentes": limites})
        return pd.DataFrame(linhasLimites)
    finally:
        conexao.close()


def pegarLimiteComponente(limitesComponentes: Any, codigoComponente: str, nomeLimite: str, valorPadrao: Any = None) -> Any:
    if not isinstance(limitesComponentes, dict):
        return valorPadrao
    componente = limitesComponentes.get(codigoComponente)
    if not isinstance(componente, dict):
        return valorPadrao
    valor = componente.get(nomeLimite)
    if valor is None:
        return valorPadrao
    return valor


def pegarValorComponenteTexto(limitesComponentes: Any, codigoComponente: str, valorPadrao: Any = None) -> Any:
    if not isinstance(limitesComponentes, dict):
        return valorPadrao
    componente = limitesComponentes.get(codigoComponente)
    if not isinstance(componente, dict):
        return valorPadrao
    valor = componente.get("valor")
    if valor is None:
        return valorPadrao
    return valor


def classificarValorPorLimite(valor: Any, limiteAlerta: Any, limiteCritico: Any) -> Optional[str]:
    if valor is None or limiteAlerta is None or limiteCritico is None:
        return None
    try:
        valor = float(valor)
        limiteAlerta = float(limiteAlerta)
        limiteCritico = float(limiteCritico)
    except Exception:
        return None
    limiteInvertido = limiteCritico < limiteAlerta
    if limiteInvertido:
        if valor <= limiteCritico:
            return "CRITICO"
        if valor <= limiteAlerta:
            return "ALERTA"
        return "NORMAL"
    if valor >= limiteCritico:
        return "CRITICO"
    if valor >= limiteAlerta:
        return "ALERTA"
    return "NORMAL"


def pegarValorMetricaLinha(linhaDados: pd.Series, coluna: str, converterParaMb: bool = False, valorAlternativo: Any = None) -> Any:
    valor = linhaDados.get(coluna)
    if valor is None:
        valor = valorAlternativo
    try:
        if pd.isna(valor):
            valor = valorAlternativo
    except Exception:
        pass
    if valor is None:
        return None
    try:
        valor = float(valor)
    except Exception:
        return None
    if converterParaMb:
        return valor / 1024 / 1024
    return valor


def montarMetricaParaLimite(linhaDados: pd.Series, codigo: str, nome: str, valor: Any, unidade: Optional[str]) -> dict:
    limitesComponentes = linhaDados.get("limites_componentes") or {}
    limiteAlerta = pegarLimiteComponente(limitesComponentes, codigo, "limite_alerta")
    limiteCritico = pegarLimiteComponente(limitesComponentes, codigo, "limite_critico")
    statusMetrica = classificarValorPorLimite(valor, limiteAlerta, limiteCritico)
    return {
        "codigo_componente": codigo,
        "metrica": nome,
        "valor": consertadorDeValoresBizarrosDoNumpy(valor),
        "unidade": unidade,
        "limite_alerta": consertadorDeValoresBizarrosDoNumpy(limiteAlerta),
        "limite_critico": consertadorDeValoresBizarrosDoNumpy(limiteCritico),
        "status": statusMetrica,
    }


def aplicarLimitesDoBanco(tabelaDados: pd.DataFrame, tabelaLimites: pd.DataFrame) -> pd.DataFrame:
    resultado = tabelaDados.copy()
    if tabelaLimites.empty:
        resultado["limites_componentes"] = [{} for _ in range(len(resultado))]
        resultado["alertas_metricas"] = [[] for _ in range(len(resultado))]
        resultado["total_alertas_metricas"] = 0
        return resultado
    resultado["id_rbc"] = pd.to_numeric(resultado["id_rbc"])
    tabelaLimites = tabelaLimites.copy()
    tabelaLimites["id_rbc"] = pd.to_numeric(tabelaLimites["id_rbc"])
    resultado = resultado.merge(tabelaLimites, on="id_rbc", how="left")
    resultado["limites_componentes"] = [limites if isinstance(limites, dict) else {} for limites in resultado["limites_componentes"]]
    alertasPorLinha = []
    criticidadesPorLinha = []
    for _, linhaDados in resultado.iterrows():
        memoriaUsadaMb = None
        memoriaTotal = linhaDados.get("memoria_total_bytes")
        memoriaDisponivel = linhaDados.get("memoria_disponivel_bytes")
        try:
            if pd.notna(memoriaTotal) and pd.notna(memoriaDisponivel):
                memoriaUsadaMb = (float(memoriaTotal) - float(memoriaDisponivel)) / 1024 / 1024
        except Exception:
            memoriaUsadaMb = None
        quantidadeProcessos = 0
        processos = linhaDados.get("processos_parsed")
        if isinstance(processos, list):
            quantidadeProcessos = len(processos)
        metricas = [
            montarMetricaParaLimite(linhaDados, "CPU_PER", "percentual_uso_cpu", pegarValorMetricaLinha(linhaDados, "percentual_uso_cpu"), "%"),
            montarMetricaParaLimite(linhaDados, "CPU_MAX", "frequencia_cpu_maxima_mhz", pegarValorMetricaLinha(linhaDados, "frequencia_cpu_maxima_mhz"), "MHz"),
            montarMetricaParaLimite(linhaDados, "CPU_MIN", "frequencia_cpu_minima_mhz", pegarValorMetricaLinha(linhaDados, "frequencia_cpu_minima_mhz"), "MHz"),
            montarMetricaParaLimite(linhaDados, "CPUUSE", "frequencia_cpu_atual_mhz", pegarValorMetricaLinha(linhaDados, "frequencia_cpu_atual_mhz"), "MHz"),
            montarMetricaParaLimite(linhaDados, "RAM_PER", "percentual_uso_ram", pegarValorMetricaLinha(linhaDados, "percentual_uso_ram"), "%"),
            montarMetricaParaLimite(linhaDados, "RAM_MAX", "memoria_total_mb", pegarValorMetricaLinha(linhaDados, "memoria_total_bytes", converterParaMb=True), "MB"),
            montarMetricaParaLimite(linhaDados, "RAM_USE", "memoria_usada_mb", memoriaUsadaMb, "MB"),
            montarMetricaParaLimite(linhaDados, "VOL_PER", "percentual_uso_disco", pegarValorMetricaLinha(linhaDados, "percentual_uso_disco"), "%"),
            montarMetricaParaLimite(linhaDados, "VOL_MAX", "disco_total_mb", pegarValorMetricaLinha(linhaDados, "disco_total_bytes", converterParaMb=True), "MB"),
            montarMetricaParaLimite(linhaDados, "VOL_USE", "disco_usado_mb", pegarValorMetricaLinha(linhaDados, "disco_usado_bytes", converterParaMb=True), "MB"),
            montarMetricaParaLimite(linhaDados, "VOL_OUT", "taxa_escrita_disco_mb_por_segundo", pegarValorMetricaLinha(linhaDados, "taxa_escrita_disco_bytes_por_segundo", converterParaMb=True), "MB/s"),
            montarMetricaParaLimite(linhaDados, "VOL_INP", "taxa_leitura_disco_mb_por_segundo", pegarValorMetricaLinha(linhaDados, "taxa_leitura_disco_bytes_por_segundo", converterParaMb=True), "MB/s"),
            montarMetricaParaLimite(linhaDados, "WEB_NUM", "latencia_ping_ms", pegarValorMetricaLinha(linhaDados, "latencia_ping_ms"), "ms"),
            montarMetricaParaLimite(linhaDados, "WEB_INP", "taxa_download_rede_mb_por_segundo", pegarValorMetricaLinha(linhaDados, "taxa_download_rede_bytes_por_segundo", converterParaMb=True), "MB/s"),
            montarMetricaParaLimite(linhaDados, "WEB_OUT", "taxa_upload_rede_mb_por_segundo", pegarValorMetricaLinha(linhaDados, "taxa_upload_rede_bytes_por_segundo", converterParaMb=True), "MB/s"),
            montarMetricaParaLimite(linhaDados, "PRS_NUM", "quantidade_processos", quantidadeProcessos, None),
            montarMetricaParaLimite(linhaDados, "SWP_PER", "percentual_uso_swap", pegarValorMetricaLinha(linhaDados, "percentual_uso_swap"), "%"),
            montarMetricaParaLimite(linhaDados, "SWP_MAX", "swap_total_mb", pegarValorMetricaLinha(linhaDados, "swap_total_bytes", converterParaMb=True), "MB"),
            montarMetricaParaLimite(linhaDados, "SWP_USE", "swap_usado_mb", pegarValorMetricaLinha(linhaDados, "swap_usado_bytes", converterParaMb=True), "MB"),
            montarMetricaParaLimite(linhaDados, "SWP_FRE", "swap_livre_mb", pegarValorMetricaLinha(linhaDados, "swap_livre_bytes", converterParaMb=True), "MB"),
            montarMetricaParaLimite(linhaDados, "SWP_INP", "swap_entrada_mb_por_segundo", pegarValorMetricaLinha(linhaDados, "swap_entrada_bytes", converterParaMb=True), "MB/s"),
            montarMetricaParaLimite(linhaDados, "SWP_OUT", "swap_saida_mb_por_segundo", pegarValorMetricaLinha(linhaDados, "swap_saida_bytes", converterParaMb=True), "MB/s"),
        ]
        alertasLinha = [metrica for metrica in metricas if metrica.get("status") in {"ALERTA", "CRITICO"}]
        if any(metrica.get("status") == "CRITICO" for metrica in alertasLinha):
            criticidade = "CRITICO"
        elif any(metrica.get("status") == "ALERTA" for metrica in alertasLinha):
            criticidade = "ALTO"
        else:
            criticidade = linhaDados.get("criticidade") or "BAIXO"
        alertasPorLinha.append(alertasLinha)
        criticidadesPorLinha.append(criticidade)
    resultado["alertas_metricas"] = alertasPorLinha
    resultado["total_alertas_metricas"] = [len(alertas) for alertas in alertasPorLinha]
    resultado["criticidade"] = criticidadesPorLinha
    return resultado
def mapearRbcLinhaEmpresa(enderecosMacUnicos: List[str]) -> pd.DataFrame:
    """
    Busca no banco qual RBC pertence a qual linha e empresa.
    Esse mapeamento é o que deixa o CSV cru com cara de dado útil, juntando MAC, RBC, linha e empresa.
    """
    if not enderecosMacUnicos:
        return pd.DataFrame(columns=[
            "endereco_mac", "id_empresa", "nome_empresa", "id_linha", "nome_linha", "id_rbc", "nome_rbc"
        ])
    conexao = obterConexaoMysql()
    try:
        cursor = conexao.cursor(dictionary=True)
        marcadoresParametros = ", ".join(["%s"] * len(enderecosMacUnicos))
        consultaSql = f"""
            SELECT
                LOWER(TRIM(r.macAdress)) AS endereco_mac,
                e.idEmpresa AS id_empresa,
                e.razaoSocial AS nome_empresa,
                l.idLinha AS id_linha,
                CONCAT('Linha ', l.idLinha) AS nome_linha,
                r.idRbc AS id_rbc,
                r.nomeServidor AS nome_rbc
            FROM rbc r
            JOIN linha l ON r.fkLinha = l.idLinha
            JOIN empresa e ON e.idEmpresa = l.fkEmpresa
            WHERE LOWER(TRIM(r.macAdress)) IN ({marcadoresParametros})
        """
        cursor.execute(consultaSql, enderecosMacUnicos)
        linhasConsulta = cursor.fetchall()
        tabelaMapeamento = pd.DataFrame(linhasConsulta)
        if tabelaMapeamento.empty:
            tabelaMapeamento = pd.DataFrame(columns=[
                "endereco_mac", "id_empresa", "nome_empresa", "id_linha", "nome_linha", "id_rbc", "nome_rbc"
            ])
        return tabelaMapeamento
    finally:
        conexao.close()
def csvSemMapear(tabelaDados: pd.DataFrame) -> pd.DataFrame:
    """
    Cria um mapeamento só com o que já veio no CSV.
    É o modo sem banco: usa o que tiver disponível e completa o resto com valores padrão para o fluxo não quebrar.
    """
    mapeamento = pd.DataFrame({"endereco_mac": sorted(tabelaDados["endereco_mac"].dropna().unique())})
    for coluna, valorPadrao in {
        "id_empresa": None,
        "nome_empresa": "SEM_EMPRESA",
        "id_linha": None,
        "nome_linha": "SEM_LINHA",
        "id_rbc": None,
        "nome_rbc": None,
    }.items():
        if coluna in tabelaDados.columns:
            tabelaTemporaria = tabelaDados[["endereco_mac", coluna]].dropna().drop_duplicates("endereco_mac", keep="last")
            mapeamento = mapeamento.merge(tabelaTemporaria, on="endereco_mac", how="left")
        else:
            mapeamento[coluna] = valorPadrao
    if "id_rbc" not in mapeamento.columns or mapeamento["id_rbc"].isna().all():
        if "id_maquina" in tabelaDados.columns:
            tabelaTemporaria = tabelaDados[["endereco_mac", "id_maquina"]].dropna().drop_duplicates("endereco_mac", keep="last")
            mapeamento = mapeamento.drop(columns=["id_rbc"], errors="ignore").merge(tabelaTemporaria, on="endereco_mac", how="left")
            mapeamento = mapeamento.rename(columns={"id_maquina": "id_rbc"})
        else:
            mapeamento["id_rbc"] = mapeamento["endereco_mac"]
    return mapeamento
def enriquecerDataframeMaquinas(tabelaDados: pd.DataFrame, tabelaMapeamento: pd.DataFrame) -> pd.DataFrame:
    """
    Junta as leituras com as informações de empresa, linha e RBC.
    Também calcula score, criticidade e versões mais legíveis de bytes e frequência. É aqui que o CSV começa a ficar mais útil de verdade.
    """
    tabelaMesclada = tabelaDados.merge(tabelaMapeamento, on="endereco_mac", how="left")
    tabelaMesclada["nome_empresa"] = tabelaMesclada.get("nome_empresa", pd.Series(index=tabelaMesclada.index)).fillna("SEM_EMPRESA")
    tabelaMesclada["nome_linha"] = tabelaMesclada.get("nome_linha", pd.Series(index=tabelaMesclada.index)).fillna("SEM_LINHA")
    tabelaMesclada["id_rbc"] = tabelaMesclada.get("id_rbc", pd.Series(index=tabelaMesclada.index)).fillna(tabelaMesclada["endereco_mac"])
    tabelaMesclada["nome_rbc"] = tabelaMesclada.get("nome_rbc", pd.Series(index=tabelaMesclada.index)).fillna(tabelaMesclada["endereco_mac"])
    if "uso_memoria" not in tabelaMesclada.columns:
        tabelaMesclada["uso_memoria"] = tabelaMesclada["percentual_uso_ram"] if "percentual_uso_ram" in tabelaMesclada.columns else np.nan
    for coluna in ["percentual_uso_cpu", "uso_memoria", "percentual_uso_disco", "percentual_uso_swap"]:
        if coluna not in tabelaMesclada.columns:
            tabelaMesclada[coluna] = np.nan
    tabelaMesclada["score"] = (
        tabelaMesclada["percentual_uso_cpu"].fillna(0) * 0.3
        + tabelaMesclada["uso_memoria"].fillna(0) * 0.3
        + tabelaMesclada["percentual_uso_disco"].fillna(0) * 0.2
        + tabelaMesclada["percentual_uso_swap"].fillna(0) * 0.2
    )
    criticidadesCalculadas = []
    for pontuacao in tabelaMesclada["score"]:
        criticidadesCalculadas.append(classificarSaudeMaquina(pontuacao))
    tabelaMesclada["criticidade"] = criticidadesCalculadas
    colunasDeBytes = [
        "memoria_total_bytes", "memoria_disponivel_bytes", "swap_total_bytes", "swap_usado_bytes",
        "swap_livre_bytes", "swap_entrada_bytes", "swap_saida_bytes", "disco_total_bytes",
        "disco_usado_bytes", "disco_livre_bytes", "taxa_leitura_disco_bytes_por_segundo",
        "taxa_escrita_disco_bytes_por_segundo", "taxa_download_rede_bytes_por_segundo",
        "taxa_upload_rede_bytes_por_segundo",
    ]
    for coluna in colunasDeBytes:
        if coluna in tabelaMesclada.columns:
            valoresHumanos = []
            for valorBytes in tabelaMesclada[coluna]:
                valoresHumanos.append(converterBytesParaEquivalenteHumano(valorBytes))
            tabelaMesclada[f"{coluna}_human"] = valoresHumanos
    for coluna in ["frequencia_cpu_atual_mhz", "frequencia_cpu_minima_mhz", "frequencia_cpu_maxima_mhz"]:
        if coluna in tabelaMesclada.columns:
            frequenciasHumanas = []
            for valorMegaHertz in tabelaMesclada[coluna]:
                frequenciasHumanas.append(converterMegaHertzParaEquivalenteHumano(valorMegaHertz))
            tabelaMesclada[f"{coluna}_human"] = frequenciasHumanas
    return tabelaMesclada
def adicionarColunasStatusRbc(tabelaDados: pd.DataFrame,limiteMinutosSemLeitura: float = limiteMinutosRbcOffline) -> pd.DataFrame:
    if tabelaDados.empty:
        return tabelaDados.copy()
    resultado = tabelaDados.copy()
    resultado["data_hora_iso"] = pd.to_datetime(resultado["data_hora_iso"], errors="coerce")
    horarioAtualEtl = pd.Timestamp.now()
    if resultado["data_hora_iso"].dt.tz is not None:
        horarioAtualEtl = pd.Timestamp.now(tz=resultado["data_hora_iso"].dt.tz)
    resultado["horario_atual_etl"] = horarioAtualEtl
    resultado["idade_ultima_leitura_minutos"] = (
        horarioAtualEtl - resultado["data_hora_iso"]
    ).dt.total_seconds() / 60.0
    resultado["idade_ultima_leitura_segundos"] = (
        resultado["idade_ultima_leitura_minutos"] * 60.0
    )
    resultado["rbc_status"] = np.where(
        resultado["idade_ultima_leitura_minutos"].fillna(float("inf")) >= limiteMinutosSemLeitura,
        "OFFLINE",
        "ONLINE",
    )
    resultado["rbc_status_motivo"] = np.where(
        resultado["rbc_status"].eq("OFFLINE"),
        f"RBC sem leitura recente há {limiteMinutosSemLeitura:g}+ minutos",
        None,
    )
    resultado["rbc_gap_limite_minutos"] = limiteMinutosSemLeitura
    resultado["leitura_anterior_data_hora"] = None
    resultado["gap_leitura_anterior_minutos"] = resultado["idade_ultima_leitura_minutos"]
    resultado["gap_leitura_anterior_segundos"] = resultado["idade_ultima_leitura_segundos"]
    return resultado
def escreverCsvEnriquecido(tabelaDados: pd.DataFrame, caminhoSaida: str, usarCsvCompacto: bool = True, compactarComGzip: bool = False) -> Path:
    """
    Salva o CSV enriquecido.
    No modo compacto, corta as colunas mais pesadas de processos para o arquivo não virar um monstro e a gravação não demorar uma eternidade.
    """
    caminhoArquivo = Path(caminhoSaida)
    if compactarComGzip and caminhoArquivo.suffix != ".gz":
        caminhoArquivo = caminhoArquivo.with_suffix(caminhoArquivo.suffix + ".gz")
    caminhoArquivo.parent.mkdir(parents=True, exist_ok=True)
    tabelaCsv = tabelaDados.copy()
    if "processos_alerta_priorizados" in tabelaCsv.columns:
        totaisProcessosAlerta = []
        nomesProcessosAlerta = []
        for itensProcessosAlerta in tabelaCsv["processos_alerta_priorizados"]:
            if isinstance(itensProcessosAlerta, list):
                totaisProcessosAlerta.append(len(itensProcessosAlerta))
                nomesDaLinha = []
                for processoAlerta in itensProcessosAlerta:
                    if isinstance(processoAlerta, dict):
                        nomesDaLinha.append(str(processoAlerta.get("name")))
                nomesProcessosAlerta.append(", ".join(nomesDaLinha))
            else:
                totaisProcessosAlerta.append(0)
                nomesProcessosAlerta.append("")
        tabelaCsv["total_processos_alerta"] = totaisProcessosAlerta
        tabelaCsv["processos_alerta_nomes"] = nomesProcessosAlerta
    if "alertas_metricas" in tabelaCsv.columns:
        nomesAlertasMetricas = []
        for alertasMetricas in tabelaCsv["alertas_metricas"]:
            nomesDaLinha = []
            if isinstance(alertasMetricas, list):
                for alertaMetrica in alertasMetricas:
                    if isinstance(alertaMetrica, dict):
                        nomesDaLinha.append(f"{alertaMetrica.get('codigo_componente')}:{alertaMetrica.get('status')}")
            nomesAlertasMetricas.append(", ".join(nomesDaLinha))
        tabelaCsv["alertas_metricas_nomes"] = nomesAlertasMetricas
    if usarCsvCompacto:
        colunasPreferidas = [
            "endereco_mac", "nome_usuario", "data_hora_iso",
            "id_empresa", "nome_empresa", "id_linha", "nome_linha", "id_rbc", "nome_rbc",
            "rbc_status", "rbc_status_motivo", "leitura_anterior_data_hora",
            "gap_leitura_anterior_minutos", "gap_leitura_anterior_segundos",
            "score", "criticidade", "latencia_ping_ms",
            "percentual_uso_cpu", "percentual_uso_ram", "uso_memoria",
            "percentual_uso_disco", "percentual_uso_swap",
            "memoria_total_bytes_human", "memoria_disponivel_bytes_human",
            "disco_livre_bytes_human",
            "taxa_leitura_disco_bytes_por_segundo_human",
            "taxa_escrita_disco_bytes_por_segundo_human",
            "taxa_download_rede_bytes_por_segundo_human",
            "taxa_upload_rede_bytes_por_segundo_human",
            "total_alertas_metricas", "alertas_metricas_nomes",
            "total_processos_alerta", "processos_alerta_nomes",
        ]
        tabelaCsv = tabelaCsv[[coluna for coluna in colunasPreferidas if coluna in tabelaCsv.columns]]
    else:
        if "processos_parsed" in tabelaCsv.columns:
            processosEmJson = []
            for itensProcessos in tabelaCsv["processos_parsed"]:
                if isinstance(itensProcessos, list):
                    processosLimpos = []
                    for processoItem in itensProcessos:
                        if isinstance(processoItem, dict):
                            processosLimpos.append(limparProcessos(processoItem))
                    processosEmJson.append(json.dumps(
                        processosLimpos,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ))
                else:
                    processosEmJson.append("[]")
            tabelaCsv["processos"] = processosEmJson
        elif "processos" in tabelaCsv.columns:
            processosEmJson = []
            for itensProcessos in tabelaCsv["processos"]:
                processosEmJson.append(json.dumps(
                    limparProcessosParaSaida(itensProcessos),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ))
            tabelaCsv["processos"] = processosEmJson


        if "alertas_metricas" in tabelaCsv.columns:
            alertasMetricasEmJson = []
            for alertasMetricas in tabelaCsv["alertas_metricas"]:
                alertasMetricasEmJson.append(json.dumps(
                    consertadorDeValoresBizarrosDoNumpy(alertasMetricas if isinstance(alertasMetricas, list) else []),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ))
            tabelaCsv["alertas_metricas_json"] = alertasMetricasEmJson


        if "limites_componentes" in tabelaCsv.columns:
            limitesComponentesEmJson = []
            for limitesComponentes in tabelaCsv["limites_componentes"]:
                limitesComponentesEmJson.append(json.dumps(
                    consertadorDeValoresBizarrosDoNumpy(limitesComponentes if isinstance(limitesComponentes, dict) else {}),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ))
            tabelaCsv["limites_componentes_json"] = limitesComponentesEmJson


        if "processos_alerta_priorizados" in tabelaCsv.columns:
            alertasProcessosEmJson = []
            for itensProcessosAlerta in tabelaCsv["processos_alerta_priorizados"]:
                if isinstance(itensProcessosAlerta, list):
                    alertasProcessosEmJson.append(json.dumps(
                        consertadorDeValoresBizarrosDoNumpy(itensProcessosAlerta),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ))
                else:
                    alertasProcessosEmJson.append("[]")
            tabelaCsv["processos_alerta_json"] = alertasProcessosEmJson
        
        
        tabelaCsv = tabelaCsv.drop(columns=["processos_parsed", "processos_alerta_priorizados", "alertas_metricas", "limites_componentes"], errors="ignore")

    
    tabelaCsv.to_csv(caminhoArquivo, index=False, compression="gzip" if compactarComGzip else None)
    return caminhoArquivo




def montarJsonLeitura(linhaDados: pd.Series, incluirProcessos: bool = True) -> dict:
    limitesComponentes = linhaDados.get("limites_componentes") or {}
    processosFiltrados = linhaDados.get("processos_alerta_priorizados")
    if not isinstance(processosFiltrados, list):
        processosFiltrados = processosUteis(linhaDados.get("processos_parsed", []), limitesComponentes=limitesComponentes)
    leituraJson = {
        "data_hora": linhaDados["data_hora_iso"].isoformat() if pd.notna(linhaDados.get("data_hora_iso")) else None,
        "rbc_status": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("rbc_status")),
        "gap_leitura_anterior_minutos": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("gap_leitura_anterior_minutos")),
        "gap_leitura_anterior_segundos": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("gap_leitura_anterior_segundos")),
        "leitura_anterior_data_hora": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("leitura_anterior_data_hora")),
        "rbc_status_motivo": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("rbc_status_motivo")),
        "criticidade": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("criticidade")),
        "score": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("score")),
        "alertas_metricas": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("alertas_metricas")),
        "total_alertas_metricas": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("total_alertas_metricas")),
        "limites_componentes": consertadorDeValoresBizarrosDoNumpy(limitesComponentes),
        "latencia_ping_ms": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("latencia_ping_ms")),
        "cpu": {
            "percentual_uso_cpu": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("percentual_uso_cpu")),
            "frequencia_atual": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("frequencia_cpu_atual_mhz_human")),
            "frequencia_minima": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("frequencia_cpu_minima_mhz_human")),
            "frequencia_maxima": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("frequencia_cpu_maxima_mhz_human")),
        },
        "memoria": {
            "percentual_uso_ram": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("percentual_uso_ram")),
            "total": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("memoria_total_bytes_human")),
            "disponivel": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("memoria_disponivel_bytes_human")),
        },
        "disco": {
            "percentual_uso_disco": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("percentual_uso_disco")),
            "livre": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("disco_livre_bytes_human")),
            "usado": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("disco_usado_bytes_human")),
            "leitura_por_segundo": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("taxa_leitura_disco_bytes_por_segundo_human")),
            "escrita_por_segundo": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("taxa_escrita_disco_bytes_por_segundo_human")),
        },
        "swap": {
            "percentual_uso_swap": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("percentual_uso_swap")),
        },
        "rede": {
            "download_por_segundo": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("taxa_download_rede_bytes_por_segundo_human")),
            "upload_por_segundo": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("taxa_upload_rede_bytes_por_segundo_human")),
        },
    }
    if incluirProcessos:
        leituraJson["processos_alerta"] = processosFiltrados
        leituraJson["total_processos_alerta"] = len(processosFiltrados)
    else:
        leituraJson["total_processos_alerta"] = len(processosFiltrados)
    return leituraJson
def montarJsonEmpresasLinhasRbc(tabelaDados: pd.DataFrame, quantidadeUltimasLeituras: int) -> dict:
    """
    Monta o JSON final no formato empresas > linhas > RBCs.
    Para cada RBC, pega as últimas leituras conforme o limite escolhido e encaixa tudo na hierarquia.
    """
    linhasJson = []
    chavesEmpresa = ["id_empresa", "nome_empresa"]
    for (idLinha, nomeLinha), tabelaLinha in tabelaDados.groupby(["id_linha", "nome_linha"], dropna=False):
        rbcsJson = []
        for idRbc, tabelaRbc in tabelaLinha.groupby("id_rbc", dropna=False):
            ultimasLeiturasRbc = tabelaRbc.sort_values("data_hora_iso").tail(quantidadeUltimasLeituras)
            ultimaLinhaRbc = ultimasLeiturasRbc.iloc[-1]
            rbcsJson.append({
                "id_rbc": consertadorDeValoresBizarrosDoNumpy(idRbc),
                "nome_rbc": consertadorDeValoresBizarrosDoNumpy(ultimaLinhaRbc.get("nome_rbc")),
                "endereco_mac": consertadorDeValoresBizarrosDoNumpy(ultimaLinhaRbc.get("endereco_mac")),
                "status_atual": consertadorDeValoresBizarrosDoNumpy(ultimaLinhaRbc.get("rbc_status")),
                "ultimo_gap_leitura_anterior_minutos": consertadorDeValoresBizarrosDoNumpy(ultimaLinhaRbc.get("gap_leitura_anterior_minutos")),
                "ultimo_gap_leitura_anterior_segundos": consertadorDeValoresBizarrosDoNumpy(ultimaLinhaRbc.get("gap_leitura_anterior_segundos")),
                "ultimas_leituras": [montarJsonLeitura(linhaDados, incluirProcessos=False)for _, linhaDados in ultimasLeiturasRbc.iterrows()],
            })
        rbcsJson.sort(key=chaveOrdenacaoRbcJson)
        linhasJson.append({
            "id_linha": consertadorDeValoresBizarrosDoNumpy(idLinha),
            "nome_linha": consertadorDeValoresBizarrosDoNumpy(nomeLinha),
            "rbc": rbcsJson,
        })
    linhasJson.sort(key=chaveOrdenacaoLinhaJson)
    return({
            "id_empresa": consertadorDeValoresBizarrosDoNumpy(tabelaDados['id_empresa'].iloc[0]),
            "nome_empresa": consertadorDeValoresBizarrosDoNumpy(tabelaDados['nome_empresa'].iloc[0]),
            "linhas": linhasJson,
            })       
def escreverJson(conteudoJson: dict, caminhoSaida: str, indent: Optional[int] = None) -> Path:
    """
    Salva o JSON final no disco.
    Antes de escrever, passa o consertador nos valores estranhos do numpy e do pandas para o json.dump não reclamar.
    """
    caminhoArquivo = Path(caminhoSaida)
    caminhoArquivo.parent.mkdir(parents=True, exist_ok=True)
    parametrosJson = {"ensure_ascii": False}
    if indent and indent > 0:
        parametrosJson["indent"] = indent
    else:
        parametrosJson["separators"] = (",", ":")
    with caminhoArquivo.open("w", encoding="utf-8") as arquivo:
        json.dump(consertadorDeValoresBizarrosDoNumpy(conteudoJson), arquivo, **parametrosJson)
    return caminhoArquivo
def carregarTodosCsvLocais(caminhoOuPadraoCsv: str, analisarColunaProcessos: bool = True) -> pd.DataFrame:
    """
    Lê um CSV específico ou vários CSVs usando padrão tipo *.csv.
    Também evita ler saída antiga do próprio ETL quando ela aparece no caminho, porque isso bagunça os dados e pode esconder os alertas reais.
    """
    caminhosEncontrados = sorted(glob(caminhoOuPadraoCsv))
    if not caminhosEncontrados:
        raise FileNotFoundError(f"Nenhum CSV encontrado com o padrão: {caminhoOuPadraoCsv}")
    caminhosCsv = []
    for caminhoEncontrado in caminhosEncontrados:
        caminhoNormalizado = Path(caminhoEncontrado)
        nomeArquivo = caminhoNormalizado.name.lower()
        partesCaminho = {parte.lower() for parte in caminhoNormalizado.parts}
        if "trusted" in partesCaminho:
            print(f"Pulando CSV de saída/pasta trusted: {caminhoEncontrado}")
            continue
        if nomeArquivo.startswith("maquinas_enriquecido") or nomeArquivo.startswith("empresas_linhas_rbc"):
            print(f"Pulando CSV que parece saída antiga do ETL: {caminhoEncontrado}")
            continue
        caminhosCsv.append(caminhoEncontrado)
    if not caminhosCsv:
        raise FileNotFoundError(f"Nenhum CSV de entrada sobrou depois dos filtros com o padrão: {caminhoOuPadraoCsv}")
    tabelasCsv = []
    for caminhoCsv in caminhosCsv:
        print(f"Lendo {linhas} leituras de: {caminhoCsv}")
        # print(f"Lendo CSV: {caminhoCsv}")
        tabelaCsv = carregarCsvLocal(
            caminhoCsv,
            separarColunaProcessos=analisarColunaProcessos,
        )
        tabelaCsv["arquivo_origem_csv"] = caminhoCsv
        tabelasCsv.append(tabelaCsv)
    tabelaFinal = pd.concat(tabelasCsv, ignore_index=True)
    return tabelaFinal
def imprimirResumoDiagnosticoAlertas(tabelaDados: pd.DataFrame, tabelaMaquinas: pd.DataFrame) -> None:
    """
    Mostra um resumão no terminal para descobrir por que os alertas vieram vazios.
    """
    totalLeituras = len(tabelaDados)
    colunaProcessosExiste = "processos" in tabelaDados.columns
    totalProcessosSeparados = 0
    totalLeiturasComProcessos = 0
    if "processos_parsed" in tabelaDados.columns:
        for processosLinha in tabelaDados["processos_parsed"]:
            if isinstance(processosLinha, list):
                quantidadeProcessos = len(processosLinha)
                totalProcessosSeparados += quantidadeProcessos
                if quantidadeProcessos > 0:
                    totalLeiturasComProcessos += 1
    totalAlertas = 0
    totalLeiturasComAlertas = 0
    if "processos_alerta_priorizados" in tabelaMaquinas.columns:
        for alertasLinha in tabelaMaquinas["processos_alerta_priorizados"]:
            if isinstance(alertasLinha, list):
                quantidadeAlertas = len(alertasLinha)
                totalAlertas += quantidadeAlertas
                if quantidadeAlertas > 0:
                    totalLeiturasComAlertas += 1
    print("Resumo dos alertas de processos:")
    print(f"- Leituras carregadas: {totalLeituras}")
    print(f"- Coluna processos existe: {colunaProcessosExiste}")
    print(f"- Leituras com processos separados: {totalLeiturasComProcessos}")
    print(f"- Total de processos separados: {totalProcessosSeparados}")
    print(f"- Leituras com alerta: {totalLeiturasComAlertas}")
    print(f"- Total de alertas encontrados: {totalAlertas}")
    if colunaProcessosExiste and totalProcessosSeparados == 0:
        print("Aviso: a coluna processos existe, mas nada foi separado. Provavelmente o formato do texto dos processos não está batendo com o parser.")
    if totalProcessosSeparados > 0 and totalAlertas == 0:
        print("Aviso: processos foram lidos, mas nenhum passou dos limites configurados no banco ou no fallback do .env.")
def montarJsonProcessosLeitura(linhaDados: pd.Series) -> dict:
    limitesComponentes = linhaDados.get("limites_componentes") or {}
    processosAlerta = linhaDados.get("processos_alerta_priorizados")
    if not isinstance(processosAlerta, list):
        processosAlerta = processosUteis(linhaDados.get("processos_parsed", []), limitesComponentes=limitesComponentes)
    processosCompletos = []
    for processo in linhaDados.get("processos_parsed", []) or []:
        if isinstance(processo, dict):
            processosCompletos.append(limparProcessos(processo))
    return {
        "data_hora": linhaDados["data_hora_iso"].isoformat() if pd.notna(linhaDados.get("data_hora_iso")) else None,
        "rbc_status": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("rbc_status")),
        "criticidade_maquina": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("criticidade")),
        "score_maquina": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("score")),
        "alertas_metricas": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("alertas_metricas")),
        "total_alertas_metricas": consertadorDeValoresBizarrosDoNumpy(linhaDados.get("total_alertas_metricas")),
        "limites_processos": {
            "PRS_STX": consertadorDeValoresBizarrosDoNumpy(pegarValorComponenteTexto(limitesComponentes, "PRS_STX", prefixosProcessosAltaPrioridade)),
            "PRS_CPU_PER": consertadorDeValoresBizarrosDoNumpy(limitesComponentes.get("PRS_CPU_PER")),
            "PRS_RAM_PER": consertadorDeValoresBizarrosDoNumpy(limitesComponentes.get("PRS_RAM_PER")),
            "PRS_RAM_USE": consertadorDeValoresBizarrosDoNumpy(limitesComponentes.get("PRS_RAM_USE")),
            "PRS_CPU_THR": consertadorDeValoresBizarrosDoNumpy(limitesComponentes.get("PRS_CPU_THR")),
        },
        "total_processos_lidos": len(processosCompletos),
        "total_processos_alerta": len(processosAlerta),
        "processos_alerta": processosAlerta,
        "processos_completos": processosCompletos,
    }
def detectarPossiveisCrashsProcessos(tabelaRbc: pd.DataFrame) -> List[dict]:
    """
    Detecta processo que existia em uma leitura e sumiu na próxima.
    Usa PRS_STX do banco para saber o que é alta prioridade.
    """
    eventos = []
    processosAnterioresPorIdentidade = {}
    limitesAnterioresPorIdentidade = {}
    tabelaOrdenada = tabelaRbc.sort_values("data_hora_iso")
    for _, linhaDados in tabelaOrdenada.iterrows():
        dataHoraAtual = linhaDados["data_hora_iso"].isoformat() if pd.notna(linhaDados.get("data_hora_iso")) else None
        limitesComponentes = linhaDados.get("limites_componentes") or {}
        processosAtuais = {}
        for processo in linhaDados.get("processos_parsed", []) or []:
            if not isinstance(processo, dict):
                continue
            identidade = identificarProcesso(processo)
            processosAtuais[identidade] = processo
            limitesAnterioresPorIdentidade[identidade] = limitesComponentes
        identidadesAnteriores = set(processosAnterioresPorIdentidade.keys())
        identidadesAtuais = set(processosAtuais.keys())
        processosQueSumiram = identidadesAnteriores - identidadesAtuais
        for identidade in processosQueSumiram:
            processoAnterior = processosAnterioresPorIdentidade.get(identidade, {})
            limitesDoProcessoAnterior = limitesAnterioresPorIdentidade.get(identidade, {})
            if not processoAnterior:
                continue
            textoProcesso = buscarProcessoPorTexto(processoAnterior)
            altaPrioridade = processoPossuiPrioridade(processoAnterior, limitesComponentes=limitesDoProcessoAnterior)
            if altaPrioridade or any(palavra in textoProcesso for palavra in palavrasChaveProcessosImportantes):
                eventos.append({
                    "tipo": "possivel_crash_ou_finalizacao_inesperada",
                    "data_hora_detectado": dataHoraAtual,
                    "identidade_processo": identidade,
                    "pid_anterior": consertadorDeValoresBizarrosDoNumpy(processoAnterior.get("pid")),
                    "name": consertadorDeValoresBizarrosDoNumpy(processoAnterior.get("name")),
                    "alta_prioridade": altaPrioridade,
                    "cmdline": limparLinhaComandoProcessos(processoAnterior.get("cmdline")),
                    "observacao": "Processo existia na leitura anterior e não apareceu nesta leitura.",
                })
        processosAnterioresPorIdentidade = processosAtuais
    return eventos
def detectarPossiveisVazamentosMemoriaProcessos(tabelaRbc: pd.DataFrame) -> List[dict]:
    eventos = []
    historicoPorIdentidade: Dict[str, List[dict]] = {}
    tabelaOrdenada = tabelaRbc.copy()
    tabelaOrdenada["data_hora_iso"] = pd.to_datetime(tabelaOrdenada["data_hora_iso"], errors="coerce")
    tabelaOrdenada = tabelaOrdenada.sort_values("data_hora_iso")
    for _, linhaDados in tabelaOrdenada.iterrows():
        dataHora = linhaDados["data_hora_iso"]
        limitesComponentes = linhaDados.get("limites_componentes") or {}
        for processo in linhaDados.get("processos_parsed", []) or []:
            if not isinstance(processo, dict):
                continue
            identidade = identificarProcesso(processo)
            valores = valoresNumericosDosProcessos(processo)
            historicoPorIdentidade.setdefault(identidade, []).append({
                "data_hora": dataHora,
                "pid": consertadorDeValoresBizarrosDoNumpy(processo.get("pid")),
                "name": consertadorDeValoresBizarrosDoNumpy(processo.get("name")),
                "cmdline": limparLinhaComandoProcessos(processo.get("cmdline")),
                "alta_prioridade": processoPossuiPrioridade(processo, limitesComponentes=limitesComponentes),
                "rss_mb": valores["rss_mb"],
                "memory_percent": valores["memory_percent"],
                "num_threads": valores["num_threads"],
                "limite_rss_mb_alerta": pegarLimiteComponente(limitesComponentes, "PRS_RAM_USE", "limite_alerta", limiteAlertaMemoriaResidenteMbProcesso),
            })
    for identidade, historico in historicoPorIdentidade.items():
        if len(historico) < 3:
            continue
        rssInicial = float(historico[0].get("rss_mb") or 0)
        rssFinal = float(historico[-1].get("rss_mb") or 0)
        crescimentoTotal = rssFinal - rssInicial
        crescimentosPositivos = 0
        for indice in range(1, len(historico)):
            rssAnterior = float(historico[indice - 1].get("rss_mb") or 0)
            rssAtual = float(historico[indice].get("rss_mb") or 0)
            if rssAtual > rssAnterior:
                crescimentosPositivos += 1
        proporcaoCrescimento = crescimentosPositivos / max(len(historico) - 1, 1)
        altaPrioridade = bool(historico[-1].get("alta_prioridade"))
        limiteRssBanco = float(historico[-1].get("limite_rss_mb_alerta") or limiteAlertaMemoriaResidenteMbProcesso)
        limiteCrescimento = min(limiteCrescimentoMemoriaResidenteMbProcesso * (0.5 if altaPrioridade else 1.0), limiteRssBanco)
        if crescimentoTotal >= limiteCrescimento and proporcaoCrescimento >= 0.6:
            eventos.append({
                "tipo": "possivel_vazamento_memoria",
                "identidade_processo": identidade,
                "pid_mais_recente": historico[-1].get("pid"),
                "name": historico[-1].get("name"),
                "alta_prioridade": altaPrioridade,
                "leituras_analisadas": len(historico),
                "rss_mb_inicial": round(rssInicial, 2),
                "rss_mb_final": round(rssFinal, 2),
                "crescimento_total_rss_mb": round(crescimentoTotal, 2),
                "limite_rss_mb_alerta_usado": round(limiteRssBanco, 2),
                "proporcao_leituras_com_crescimento": round(proporcaoCrescimento, 4),
                "cmdline": historico[-1].get("cmdline"),
                "observacao": "RSS cresceu de forma recorrente no histórico analisado.",
            })
    eventos.sort(key=lambda item: float(item.get("crescimento_total_rss_mb") or 0), reverse=True)
    return eventos
def montarJsonProcessosRbc(tabelaRbc: pd.DataFrame, quantidadeUltimasLeiturasProcessos: int) -> dict:
    tabelaRbc = tabelaRbc.copy()
    tabelaRbc["data_hora_iso"] = pd.to_datetime(tabelaRbc["data_hora_iso"], errors="coerce")
    tabelaRbc = tabelaRbc.sort_values("data_hora_iso")
    ultimasLeituras = tabelaRbc.tail(quantidadeUltimasLeiturasProcessos)
    ultimaLinha = ultimasLeituras.iloc[-1] 
    #eu posso reclamar da sintaxe python por horas, oddeio isso
    # havia feito uma função para buscar ultima linha com len() etc, mas isso... isso faz igual
    return {
        "id_empresa": consertadorDeValoresBizarrosDoNumpy(ultimaLinha.get("id_empresa")),
        "nome_empresa": consertadorDeValoresBizarrosDoNumpy(ultimaLinha.get("nome_empresa")),
        "id_linha": consertadorDeValoresBizarrosDoNumpy(ultimaLinha.get("id_linha")),
        "nome_linha": consertadorDeValoresBizarrosDoNumpy(ultimaLinha.get("nome_linha")),
        "id_rbc": consertadorDeValoresBizarrosDoNumpy(ultimaLinha.get("id_rbc")),
        "nome_rbc": consertadorDeValoresBizarrosDoNumpy(ultimaLinha.get("nome_rbc")),
        "endereco_mac": consertadorDeValoresBizarrosDoNumpy(ultimaLinha.get("endereco_mac")),
        "quantidade_leituras_processos": len(ultimasLeituras),
        "leituras": [
            montarJsonProcessosLeitura(linhaDados)
            for _, linhaDados in ultimasLeituras.iterrows()
        ],
        "eventos_detectados": {
            "possiveis_vazamentos_memoria": detectarPossiveisVazamentosMemoriaProcessos(ultimasLeituras),
            "possiveis_crashs_ou_finalizacoes_inesperadas": detectarPossiveisCrashsProcessos(ultimasLeituras),
        },
    }
def escreverJsonsProcessosSeparados(tabelaDados: pd.DataFrame,quantidadeUltimasLeiturasProcessos: int,diretorioSaidaProcessos: str,indent: Optional[int] = None,) -> List[Path]:
    caminhosGerados = []
    tabelaDados = tabelaDados.copy()
    tabelaDados["data_hora_iso"] = pd.to_datetime(tabelaDados["data_hora_iso"], errors="coerce")
    Path(diretorioSaidaProcessos).mkdir(parents=True, exist_ok=True)
    for idRbc, tabelaRbc in tabelaDados.groupby("id_rbc", dropna=False):
        conteudoJson = montarJsonProcessosRbc(
            tabelaRbc,
            quantidadeUltimasLeiturasProcessos=quantidadeUltimasLeiturasProcessos,
        )
        idRbcSeguro = str(conteudoJson["id_rbc"]).replace("/", "_").replace("\\", "_").replace(":", "_")
        caminhoSaida = f"{diretorioSaidaProcessos}/processos_rbc_{idRbcSeguro}.json"
        caminhosGerados.append(
            escreverJson(conteudoJson, caminhoSaida, indent=indent)
        )
    return caminhosGerados
def main():
    """
    Roda o ETL completo usando apenas as configurações do .env.
    """
    caminhoCsvEntrada = os.getenv("LOCAL_INPUT_CSV", "df.csv")
    caminhoJsonSaida = os.getenv("LOCAL_OUTPUT_JSON")
    caminhoCsvSaidaConfigurado = os.getenv("LOCAL_OUTPUT_CSV")
    diretorioJsonClient = os.getenv("CLIENT_OUTPUT_DIR", "client")
    diretorioSaidaProcessos = os.getenv("PROCESS_OUTPUT_DIR")
    quantidadeUltimasLeituras = lerVariavelAmbienteInteira("LAST_N")
    quantidadeUltimasLeiturasProcessos = lerVariavelAmbienteInteira("PROCESS_LAST_N")
    limiteMinutosSemLeitura = lerVariavelAmbienteDecimal("RBC_OFFLINE_GAP_MINUTES")
    usarBancoDados = not lerVariavelAmbienteBooleana("NO_DB")
    pularAlertasProcessos = lerVariavelAmbienteBooleana("SKIP_PROCESS_ALERTS")
    gravarCsvCompleto = lerVariavelAmbienteBooleana("FULL_CSV")
    compactarCsvComGzip = lerVariavelAmbienteBooleana("CSV_GZIP")
    indentacaoJson = lerVariavelAmbienteInteira("JSON_INDENT")
    usarCsvCompacto = False if gravarCsvCompleto else lerVariavelAmbienteBooleana("COMPACT_CSV_DEFAULT")
    tabelaDados = carregarTodosCsvLocais(    caminhoCsvEntrada,    analisarColunaProcessos = not pularAlertasProcessos)
    enderecosMacUnicos = sorted(tabelaDados["endereco_mac"].dropna().unique().tolist())
    if usarBancoDados:
        tabelaMapeamento = mapearRbcLinhaEmpresa(enderecosMacUnicos)
    else:
        tabelaMapeamento = csvSemMapear(tabelaDados)
    tabelaMaquinas = enriquecerDataframeMaquinas(tabelaDados, tabelaMapeamento)
    tabelaMaquinas = adicionarColunasStatusRbc(
        tabelaMaquinas,
        limiteMinutosSemLeitura=limiteMinutosSemLeitura
    )
    print("-" * columns)
    print("-" * columns)
    print(f"usando banco de dados:{usarBancoDados}")
    print("-" * columns)
    print("-" * columns)
    if usarBancoDados:
        idsRbc = tabelaMaquinas["id_rbc"].dropna().unique().tolist()
        tabelaLimites = buscarLimitesComponentesRbc(idsRbc)
        tabelaMaquinas = aplicarLimitesDoBanco(tabelaMaquinas, tabelaLimites)
        print(f"Limites do banco aplicados: {len(tabelaLimites)} RBC(s) com definição encontrada.")
    else:
        tabelaMaquinas["limites_componentes"] = [{} for _ in range(len(tabelaMaquinas))]
        tabelaMaquinas["alertas_metricas"] = [[] for _ in range(len(tabelaMaquinas))]
        tabelaMaquinas["total_alertas_metricas"] = 0
        print("NO_DB=true: limites do banco não foram buscados; processos usam fallback do .env.")
    print("\nResumo de empresas, linhas e RBCs encontradas:")
    totalEmpresas = tabelaMaquinas["id_empresa"].nunique(dropna=False) if "id_empresa" in tabelaMaquinas.columns else 0
    totalLinhas = tabelaMaquinas["id_linha"].nunique(dropna=False) if "id_linha" in tabelaMaquinas.columns else 0
    totalRbcs = tabelaMaquinas["id_rbc"].nunique(dropna=False) if "id_rbc" in tabelaMaquinas.columns else 0
    totalLeituras = len(tabelaMaquinas)
    print(f"- Empresas encontradas: {totalEmpresas}")
    print(f"- Linhas encontradas: {totalLinhas}")
    print(f"- RBCs/máquinas encontradas: {totalRbcs}")
    print(f"- Leituras carregadas: {totalLeituras}")
    print("\nDetalhamento:")
    for (idEmpresa, nomeEmpresa), tabelaEmpresa in tabelaMaquinas.groupby(["id_empresa", "nome_empresa"], dropna=False):
        print(f"\nEmpresa {idEmpresa} - {nomeEmpresa}")
        for (idLinha, nomeLinha), tabelaLinha in tabelaEmpresa.groupby(["id_linha", "nome_linha"], dropna=False):
            print(f"  Linha {idLinha} - {nomeLinha}")
            for idRbc, tabelaRbc in tabelaLinha.groupby("id_rbc", dropna=False):
                ultimaLeitura = tabelaRbc.sort_values("data_hora_iso").iloc[-1]
                nomeRbc = ultimaLeitura.get("nome_rbc")
                mac = ultimaLeitura.get("endereco_mac")
                status = ultimaLeitura.get("rbc_status")
                totalLeiturasRbc = len(tabelaRbc)
                print(
                    f"    RBC {idRbc} - {nomeRbc} | "
                    f"MAC: {mac} | "
                    f"Status: {status} | "
                    f"Leituras: {totalLeiturasRbc}"
                )
    if "nome_empresa" in tabelaMaquinas.columns:
        semCadastro = tabelaMaquinas[
            tabelaMaquinas["nome_empresa"].fillna("").eq("SEM_EMPRESA")
        ][["endereco_mac"]].drop_duplicates()
        if not semCadastro.empty:
            print("\nRBCs sem cadastro no MySQL:")
            for _, linha in semCadastro.iterrows():
                print(f"- MAC: {linha['endereco_mac']}")

    print("-" * columns)
    print("-" * columns)
    if pularAlertasProcessos:
        tabelaMaquinas["processos_alerta_priorizados"] = [[] for _ in range(len(tabelaMaquinas))]
    else:
        tabelaMaquinas = criarColunaAlertaProcessos(tabelaMaquinas)
    imprimirResumoDiagnosticoAlertas(tabelaDados, tabelaMaquinas)
    caminhoCsvSaida = escreverCsvEnriquecido(
        tabelaMaquinas,
        caminhoCsvSaidaConfigurado,
        usarCsvCompacto=usarCsvCompacto,
        compactarComGzip=compactarCsvComGzip,
    )
    tabelaDados = tabelaMaquinas.copy()
    tabelaDados["data_hora_iso"] = pd.to_datetime(tabelaDados["data_hora_iso"], errors="coerce")
    empresaJson = []
    chavesEmpresa = ["id_empresa", "nome_empresa"]
    for (idEmpresa, nomeEmpresa), tabelaEmpresa in tabelaDados.groupby(chavesEmpresa, dropna=False):
        conteudoJson = montarJsonEmpresasLinhasRbc(tabelaEmpresa, quantidadeUltimasLeituras=quantidadeUltimasLeituras)
        idEmpresaSeguro = str(conteudoJson["id_empresa"]).replace("/", "_").replace("\\", "_").replace(":", "_")
        caminhoSaida = escreverJson(
            conteudoJson,
            f"{diretorioJsonClient}/empresas_linhas_rbc_{idEmpresaSeguro}.json",
            indent=indentacaoJson,
        )
        print(f"JSON da empresa gerado: {caminhoSaida}")
    if not pularAlertasProcessos:
        caminhosJsonProcessos = escreverJsonsProcessosSeparados(
            tabelaDados,
            quantidadeUltimasLeiturasProcessos=quantidadeUltimasLeiturasProcessos,
            diretorioSaidaProcessos=diretorioSaidaProcessos,
            indent=indentacaoJson,
        )
        print(f"JSONs de processos gerados: {len(caminhosJsonProcessos)}")
    print(f"CSV gerado: {caminhoCsvSaida}")
if __name__ == "__main__":
    main()
 
