from datetime import datetime
import pandas as pd
import psutil
import uuid
import time
import os
from colorama import Fore, Style, init
import subprocess
import boto3
import logging
from botocore.exceptions import ClientError
import mysql.connector
from mysql.connector import Error

INTERVALO_SEGUNDOS = 3
bucket = 's3-raw-lab-2026-04-06-erick'
caminho_arquivo_local = 'raw/'

ATRIBUTOS_PROCESSOS = [
    'pid', 'name', 'username', 'status', 'create_time',
    'cpu_percent', 'memory_info', 'num_threads',
    'cmdline', 'exe', 'cpu_times', 'memory_percent'
]

s3_client = boto3.client(
    's3',
    aws_access_key_id=,
    aws_secret_access_key=,
    aws_session_token=
)

init(autoreset=True)

def cor_status(valor, limite1=60, limite2=80):
    if valor >= limite2:
        return Fore.RED
    elif valor >= limite1:
        return Fore.YELLOW
    else:
        return Fore.GREEN


def limpar_terminal():
    os.system('cls' if os.name == 'nt' else 'clear')

def medir_ping(host="8.8.8.8"):
    try:
        resultado = subprocess.run(
            ["ping", "-n", "1", host],
            capture_output=True,
            text=True
        )

        for linha in resultado.stdout.split("\n"):
            if "tempo=" in linha.lower():
                tempo = linha.split("tempo=")[1].split("ms")[0]
                return int(tempo)

        return 0
    except:
        return 0



def listar_processos_filtrados():
    processos_filtrados = []

    for processo in psutil.process_iter(attrs=ATRIBUTOS_PROCESSOS):
        try:
            if processo.info['memory_percent'] >= 5:
                processos_filtrados.append(processo.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return processos_filtrados

def coletar_metricas_sistema():
    
    mac_numero = uuid.getnode()
    endereco_mac = ':'.join(
        ['{:02x}'.format((mac_numero >> i) & 0xff) for i in range(0, 48, 8)][::-1]
    )

    try:
        nome_usuario = os.getlogin()
    except Exception:
        nome_usuario = os.environ.get("USERNAME") or os.environ.get("USER") or "desconhecido"
    

    percentual_uso_cpu = psutil.cpu_percent(interval=None)
    frequencia_cpu = psutil.cpu_freq()

    frequencia_cpu_atual_mhz = round(frequencia_cpu.current, 2) if frequencia_cpu else 0
    frequencia_cpu_minima_mhz = round(frequencia_cpu.min, 2) if frequencia_cpu else 0
    frequencia_cpu_maxima_mhz = round(frequencia_cpu.max, 2) if frequencia_cpu else 0

    memoria_virtual = psutil.virtual_memory()
    percentual_uso_ram = memoria_virtual.percent

    memoria_swap = psutil.swap_memory()

    percentual_uso_swap = 0
    if memoria_swap.total > 0:
        percentual_uso_swap = (memoria_swap.used / memoria_swap.total) * 100

    uso_disco = psutil.disk_usage('/')

    io_disco_inicial = psutil.disk_io_counters()
    io_rede_inicial = psutil.net_io_counters()

    time.sleep(INTERVALO_SEGUNDOS)

    io_disco_final = psutil.disk_io_counters()
    io_rede_final = psutil.net_io_counters()

    latencia_ping_ms = medir_ping()
    
    taxa_leitura_disco_bytes_por_segundo = (
        io_disco_final.read_bytes - io_disco_inicial.read_bytes
    ) / INTERVALO_SEGUNDOS

    taxa_escrita_disco_bytes_por_segundo = (
        io_disco_final.write_bytes - io_disco_inicial.write_bytes
    ) / INTERVALO_SEGUNDOS

    taxa_download_rede_bytes_por_segundo = (
        io_rede_final.bytes_recv - io_rede_inicial.bytes_recv
    ) / INTERVALO_SEGUNDOS

    taxa_upload_rede_bytes_por_segundo = (
        io_rede_final.bytes_sent - io_rede_inicial.bytes_sent
    ) / INTERVALO_SEGUNDOS

    lista_processos = listar_processos_filtrados()
    
    data_hora_iso = datetime.now().isoformat()

def tratamento_das_metricas():

#degradação da CPU
    if coletar_metricas_sistema.frequencia_cpu_atual_mhz <= (coletar_metricas_sistema.frequencia_cpu_maxima_mhz * 0.50) && coletar_metricas_sistema.percentual_uso_cpu > 50:
        degradacao = "Possivel degradação da CPU devido a temperatura muito elevada (Baixa freqência de mhz e alto percentual de uso)"
    else:
        degradacao = "Sem indicios de degradação na CPU"
    

#status de uso da cpu
    if coletar_metricas_sistema.percentual_uso_cpu >= LIMITE:
        status_cpu = "CRÍTICO"
    elif coletar_metricas_sistema.percentual_uso_cpu >= LIMITE - 15:
        status_cpu = "ATENÇÃO"
    elif coletar_metricas_sistema.percentual_uso_cpu <= LIMITE - 15:
        status_cpu = "Normal"

#status da ram
    if coletar_metricas_sistema.percentual_uso_ram >= LIMITE:
        status_ram = "CRÍTICO"
    elif coletar_metricas_sistema.percentual_uso_ram >= LIMITE - 15:
        status_ram = "ATENÇÃO"
    elif coletar_metricas_sistema.percentual_uso_ram <= LIMITE - 15:
        status_ram = "Normal"

#status swap
    if coletar_metricas_sistema.percentual_uso_swap <= 5:
        status_swap = "Normal"
    elif coletar_metricas_sistema.percentual_uso_swap <= 20:
        status_swap = "Atenção"
    elif coletar_metricas_sistema.percentual_uso_swap <= 50:
        status_swap = "ALERTA"
    else:
        status_swap = "CRÍTICO"


#status disco
    if coletar_metricas_sistema.uso_disco.percent >= LIMITE:
        status_disco = "CRÍTICO"
    elif coletar_metricas_sistema.uso_disco.percent >= LIMITE - 15:
        status_disco = "ATENÇÃO"
    elif coletar_metricas_sistema.us_disco.percent <= LIMITE -15:
        status_disco = "Normal"

#processos gastando mais de 5% de RAM

limite_ram = coletar_metricas_sistema.memoria_virtual.total * 0.05

processos_pesados = []

for proc in psutil.process.iter(['pid', 'name', 'memory_info']):
    try:
        memoria_rss = ['memory_info'].rss
        memoria_mb = memoria_rss / (1024 * 1024)

        if memoria_rss > limite_ram:
            processos_pesados.append({
                'pid': proc.info['pid'],
                'name': proc.info['name'],
                'memoria_mb': round(memoria_mb, 2)
                'porcentagem_ram': (memoria_mb / (coletar_metricas_sistema.memoria_virtual.total/ (1024 * 1024))) * 100  
            })

    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass

resultados = buscar_processos_memoria(limite_ram)

print(f"Processos consumindo mais do que {limite_ram}$ de MEMÓRIA RAM")
for p in resultados:
    print(f"PID: {p['pid']} | Nome: {p['name']} | Memória: {p['memoria_mb']} MB | Porcentágem gasta: {p['procentagem_ram']}")


#status ping
    if coletar_metricas_sistema.latencia_ping_ms <= 50:
        status_ping = "Baixa latência"
    elif coletar_metricas_sistema.latencia_ping_ms <= 200:
        status_ping = "Latência moderada (Alerta)"
    else:
        status_ping = "Latêcia alta (Critico)"

    df_metricas = pd.DataFrame([{
        "endereco_mac": coletar_metricas_sistema.endereco_mac,
        "nome_usuario": coletar_metricas_sistema.nome_usuario,

        "percentual_uso_cpu": coletar_metricas_sistema.percentual_uso_cpu,
        "frequencia_cpu_atual_mhz": coletar_metricas_sistema.frequencia_cpu_atual_mhz,
        "frequencia_cpu_minima_mhz": coletar_metricas_sistema.frequencia_cpu_minima_mhz,
        "frequencia_cpu_maxima_mhz": coletar_metricas_sistema.frequencia_cpu_maxima_mhz,

        "memoria_total_bytes": int(coletar_metricas_sistema.memoria_virtual.total),
        "memoria_disponivel_bytes": int(coletar_metricas_sistema.memoria_virtual.available),
        "percentual_uso_ram": coletar_metricas_sistema.percentual_uso_ram,

        "swap_total_bytes": int(coletar_metricas_sistema.memoria_swap.total),
        "swap_usado_bytes": int(coletar_metricas_sistema.memoria_swap.used),
        "swap_livre_bytes": int(coletar_metricas_sistema.memoria_swap.free),
        "swap_entrada_bytes": int(coletar_metricas_sistema.memoria_swap.sin),
        "swap_saida_bytes": int(coletar_metricas_sistema.memoria_swap.sout),
        "percentual_uso_swap": coletar_metricas_sistema.percentual_uso_swap,

        "disco_total_bytes": int(coletar_metricas_sistema.uso_disco.total),
        "disco_usado_bytes": int(coletar_metricas_sistema.uso_disco.used),
        "disco_livre_bytes": int(coletar_metricas_sistema.uso_disco.free),
        "percentual_uso_disco": coletar_metricas_sistema.uso_disco.percent,

        "taxa_leitura_disco_bytes_por_segundo": int(coletar_metricas_sistema.taxa_leitura_disco_bytes_por_segundo),
        "taxa_escrita_disco_bytes_por_segundo": int(coletar_metricas_sistema.taxa_escrita_disco_bytes_por_segundo),

        "latencia_ping_ms": coletar_metricas_sistema.latencia_ping_ms,
        "taxa_download_rede_bytes_por_segundo": int(coletar_metricas_sistema.taxa_download_rede_bytes_por_segundo),
        "taxa_upload_rede_bytes_por_segundo": int(coletar_metricas_sistema.taxa_upload_rede_bytes_por_segundo),

        "processos": str(coletar_metricas_sistema.lista_processos),
        "data_hora_iso": coletar_metricas_sistema.data_hora_iso,

        "degradacao": coletar_metricas_sistema.degradacao,
        "status_cpu": coletar_metricas_sistema.status_cpu,
        "status_ram": coletar_metricas_sistema.status_ram,
        "status_swap": coletar_metricas_sistema.status_swap,
        "status_disco": coletar_metricas_sistema.status_disco,
        "status_ping": coletar_metricas_sistema.status_ping

    }])
    
    return df_metricas

def select_tabelas():
    try:
        conexao = mysql.connector.connect(
        host='localhost',
        database='systraintrack',
        user='root',
        password='@GOSTY0210will0511'
        )
        
        if conexao.is_connected():
            informacoes_bd = conexao.get_server_info()
            print(f"Conecção com o MySQLServer, versão:  {informacoes_bd} realizada com sucesso!")

            cursor = conexao.cursor()

            query = ""

            retorno = cursor.fetchall()
            print(f"Total de linhas retornadas: {cursor.rowcount}")

            for row in retorno:
                print(row)
            
    except Error as e:
        print(f"Erro ao conectar ao MySQL {e}")

    finally:
        if 'conexao' in locals() and conexao.is_connected():
            cursor.close()
            conexao.close()
            print(f"Conxão encerrada")


    


def salvar_csv_local(df_metricas, nome_arquivo):
    df_metricas.to_csv(
        f'./{nome_arquivo}.csv',  
        header=not os.path.exists(f'./{nome_arquivo}.csv'), 
        index=False,
        mode = "a"
    )
   



def upload_arquivo_s3(caminho_arquivo_local, bucket, idMaquina, object_name=None):
    if object_name is None:
        object_name = os.path.basename(caminho_arquivo_local)

    ano = datetime.now().strftime("%Y")
    mes = datetime.now().strftime("%m")
    dia = datetime.now().strftime("%d")
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    try:
        response = s3_client.upload_file(caminho_arquivo_local, bucket, f'raw/{ano}/{mes}/{dia}/dados_{timestamp}_{idMaquina}.csv')
    except ClientError as e:
        logging.error(e)
        return False
    return True


print(Fore.GREEN + "==========================================")
print(Fore.GREEN + "🚀 SYS TRAIN TRACK - MONITORAMENTO")
print(Fore.GREEN + "==========================================\n")

contador = 0

def ler_arquivo_s3():

    ano = datetime.now().strftime("%Y")
    mes = datetime.now().strftime("%m")
    dia = datetime.now().strftime("%d")
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")

    response = s3_client.get_object(Bucket=bucket, Key=f'raw/{ano}/{mes}/{dia}/')

    content = response['Body'].read().decode('utf-8')
    print(content)

def iniciar_captura():
    global contador
    
    df_atual = coletar_metricas_sistema()
    id_maquina = df_atual["endereco_mac"].iloc[0].replace(":", "")
    nome_arquivo = f'dados_{id_maquina}'

    salvar_csv_local(df_atual, nome_arquivo)
    contador +=  1
        
    if (contador >= 60):
        contador = 0
        upload_arquivo_s3(bucket = "s3-raw-lab-2026-04-06-erick", idMaquina = id_maquina, caminho_arquivo_local = f"./{nome_arquivo}.csv")
    
    dados = df_atual.iloc[0]
    limpar_terminal()

    print(Fore.GREEN + "==========================================")
    print(Fore.GREEN + "📊 MONITORAMENTO EM TEMPO REAL")
    print(Fore.GREEN + "==========================================\n")

    print(Fore.CYAN + f"👤 Usuário: {dados['nome_usuario']}")
    print(Fore.CYAN + f"🕒 {datetime.now().strftime('%H:%M:%S')}")
    print(Fore.CYAN + f"⏱ Intervalo: {INTERVALO_SEGUNDOS}s\n")

    cpu = dados["percentual_uso_cpu"]
    ram = dados["percentual_uso_ram"]
    disco = dados["percentual_uso_disco"]
    ping = dados["latencia_ping_ms"]

    print(Fore.WHITE + "🧠 CPU")
    print(cor_status(cpu) + f"   Uso: {cpu:.1f}%")
    print(Fore.WHITE + f"   Freq: {dados['frequencia_cpu_atual_mhz']} MHz\n")

    print(Fore.WHITE + "💾 RAM")
    print(cor_status(ram) + f"   Uso: {ram:.1f}%")
    print(Fore.WHITE + f"   Livre: {dados['memoria_disponivel_bytes'] // (1024**3)} GB\n")

    print(Fore.WHITE + "🗄 DISCO")
    print(cor_status(disco) + f"   Uso: {disco:.1f}%")
    print(Fore.WHITE + f"   Livre: {dados['disco_livre_bytes'] // (1024**3)} GB\n")

    print(Fore.WHITE + "🌐 REDE")
    print(Fore.CYAN + f"   Ping: {ping} ms")
    print(Fore.MAGENTA + f"   ↓ {dados['taxa_download_rede_bytes_por_segundo']} B/s")
    print(Fore.MAGENTA + f"   ↑ {dados['taxa_upload_rede_bytes_por_segundo']} B/s\n")

    print(Fore.WHITE + "⚙ PROCESSOS")
    print(Fore.YELLOW + f"   Processos críticos: {len(eval(dados['processos']))}\n")
    print(Fore.GREEN + "==========================================")

    

while True:
    iniciar_captura()
    