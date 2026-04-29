# Systrain Track — Scripts Python

Scripts de coleta, simulação e tratamento de métricas de recursos de sistema para o projeto **Systrain Track**.

O repositório reúne ferramentas para capturar métricas de máquinas em tempo real, salvar os dados em CSV, enviar os arquivos para um bucket S3 e transformar os dados brutos em arquivos tratados para análise, dashboard ou integração com outras aplicações.

## Visão geral

O fluxo principal do projeto é:

1. **Coleta de métricas** da máquina com Python e `psutil`.
2. **Geração de arquivo CSV bruto** com informações de CPU, RAM, swap, disco, rede, latência e processos.
3. **Envio periódico para S3**.
4. **Processamento ETL** dos dados brutos.
5. **Geração de arquivos tratados** separados por empresa, máquina, processos, sessões de processos, correlações e JSONs para consumo por cliente ou aplicação.

## Estrutura do repositório

```text
scripts-python-systrain/
├── pythonMainScripts/
│   ├── capturar.py              # Script principal de captura em tempo real
│   └── ETL/
│       ├── ETL.py               # Pipeline de tratamento dos dados coletados
│       └── ETL_LOCAL/           # Área para execução/localização de ETL local
├── pythonSimulacoes/
│   ├── simulacaoContinua/
│   │   └── criarProcessos.py    # Simula processos contínuos na máquina
│   ├── simulacaoInstantanea/
│   │   └── gerarSimulacao.py    # Simulações pontuais
│   └── df.csv                   # Exemplo/base de dados simulada
├── rStudioData/                 # Dados, scripts e materiais usados no R/RStudio
├── documento_definicao_metricas.md
└── README.md
```

## Funcionalidades

### Coleta de métricas

O script `pythonMainScripts/capturar.py` coleta e registra informações como:

- Endereço MAC da máquina.
- Usuário da máquina.
- Percentual de uso de CPU.
- Frequência atual, mínima e máxima da CPU.
- Memória RAM total, disponível e percentual de uso.
- Memória swap total, usada, livre, entrada e saída.
- Uso total, livre e ocupado do disco.
- Taxa de leitura e escrita em disco.
- Latência de rede via `ping`.
- Taxa de download e upload da rede.
- Lista de processos ativos com PID, nome, usuário, status, consumo de CPU, memória, threads, comando e executável.
- Data e hora da coleta em formato ISO.

Por padrão, o script salva os dados em `raw/df.csv` e envia os arquivos para o S3 a cada 5 ciclos de coleta.

### ETL dos dados

O script `pythonMainScripts/ETL/ETL.py` processa o CSV bruto vindo do S3 e gera arquivos tratados em `trusted/`.

O ETL realiza tarefas como:

- Leitura do CSV bruto no S3.
- Normalização do endereço MAC.
- Enriquecimento dos dados com informações de empresa e máquina vindas do MySQL.
- Cálculo de score de criticidade.
- Classificação em níveis como `BAIXO`, `MODERADO`, `ALTO` e `CRITICO`.
- Conversão de bytes e MHz para formatos legíveis.
- Explosão da lista de processos em um dataframe próprio.
- Criação de sessões de processos com base em intervalo de tempo.
- Cálculo de correlações entre métricas.
- Separação de dados por empresa e máquina.
- Geração de JSONs com as últimas métricas para consumo externo.
- Upload dos dados tratados para o S3.

### Simulações

A pasta `pythonSimulacoes/` contém scripts para gerar cenários de carga e testar a captura de métricas.

O script `simulacaoContinua/criarProcessos.py` cria processos artificiais com nomes relacionados a componentes RBC, variando a quantidade de processos de acordo com horário, dia da semana e ruído aleatório. Isso ajuda a simular carga de CPU e memória para testar o monitoramento.

## Principais métricas monitoradas

| Grupo | Métricas |
|---|---|
| CPU | Uso percentual, frequência atual, mínima e máxima |
| RAM | Total, disponível e percentual de uso |
| Swap | Total, usado, livre, entrada, saída e percentual de uso |
| Disco | Total, usado, livre, percentual de uso, leitura/s e escrita/s |
| Rede | Latência, download/s e upload/s |
| Processos | PID, nome, usuário, status, CPU, memória, threads, comando e executável |

## Requisitos

- Python 3.10 ou superior recomendado.
- MySQL, se for executar o ETL com enriquecimento de empresa/máquina.
- Bucket S3 ou serviço compatível com S3.
- Acesso às credenciais necessárias via arquivo `.env` ou `.env.dev`.

## Dependências

As principais bibliotecas utilizadas são:

- `psutil`
- `pandas`
- `boto3`
- `python-dotenv`
- `colorama`
- `mysql-connector-python`
- `numpy`
- `setproctitle` — usado nos scripts de simulação

Instalação sugerida:

```bash
pip install psutil pandas boto3 python-dotenv colorama mysql-connector-python numpy setproctitle
```

Opcionalmente, crie um `requirements.txt` com esse conteúdo:

```txt
psutil
pandas
boto3
python-dotenv
colorama
mysql-connector-python
numpy
setproctitle
```

E instale com:

```bash
pip install -r requirements.txt
```

## Configuração de ambiente

Antes de executar os scripts principais, configure as variáveis de ambiente.

Exemplo de `.env.dev` para captura:

```env
S3_BUCKET_NAME=nome-do-bucket
S3_INPUT_KEY=df.csv
S3_OUTPUT_PREFIX=raw
AWS_ACCESS_KEY_ID=sua_access_key
AWS_SECRET_ACCESS_KEY=sua_secret_key
AWS_DEFAULT_REGION=us-east-1
AWS_SESSION_TOKEN=
S3_ENDPOINT_URL=
```

Exemplo de `.env` para o ETL:

```env
S3_BUCKET_NAME=nome-do-bucket
S3_INPUT_KEY=raw/df.csv
S3_OUTPUT_PREFIX=trusted
AWS_ACCESS_KEY_ID=sua_access_key
AWS_SECRET_ACCESS_KEY=sua_secret_key
AWS_DEFAULT_REGION=us-east-1
AWS_SESSION_TOKEN=
S3_ENDPOINT_URL=
```

> Não versionar arquivos `.env`, `.env.dev` ou credenciais reais. Use um `.env.example` para documentar as variáveis esperadas.

## Como executar

### 1. Clone o repositório

```bash
git clone https://github.com/Projeto-Systrain-Track/scripts-python-systrain.git
cd scripts-python-systrain
```

### 2. Instale as dependências

```bash
pip install psutil pandas boto3 python-dotenv colorama mysql-connector-python numpy setproctitle
```

### 3. Configure as variáveis de ambiente

Crie os arquivos `.env.dev` e/ou `.env` conforme a necessidade do script que será executado.

### 4. Execute a captura de métricas

```bash
python pythonMainScripts/capturar.py
```

O script roda continuamente até ser interrompido manualmente com `Ctrl + C`.

### 5. Execute o ETL

```bash
python pythonMainScripts/ETL/ETL.py
```

O ETL lê o arquivo bruto do S3, transforma os dados e envia os resultados tratados para o prefixo configurado.

### 6. Execute a simulação contínua, se necessário

```bash
python pythonSimulacoes/simulacaoContinua/criarProcessos.py
```

Use esse script para gerar processos artificiais e validar o comportamento da captura em cenários de carga.

## Saídas geradas

### Captura

```text
raw/
└── df.csv
```

### ETL

```text
trusted/
├── maquinas_enriquecido.csv
├── processos_explodidos.csv
├── empresas/
├── maquinas/
├── processos/
├── correlacoes/
├── sessoes_processos/
└── json_client/
```

## Criticidade

O ETL calcula um score geral combinando CPU, memória, disco e swap:

```text
score = CPU * 0.3 + RAM * 0.3 + Disco * 0.2 + Swap * 0.2
```

Classificação aplicada:

| Score | Criticidade |
|---:|---|
| até 50 | BAIXO |
| maior que 50 | MODERADO |
| maior que 70 | ALTO |
| maior que 85 | CRITICO |

## Observações importantes

- O script de captura usa um intervalo de 3 segundos entre medições internas.
- O upload para S3 ocorre a cada 5 ciclos de captura.
- A captura de alguns processos pode depender de permissões do sistema operacional.
- O comando de `ping` é adaptado para Windows e Linux/macOS.
- O ETL depende da estrutura esperada no banco MySQL, principalmente das tabelas relacionadas a RBC, linha e empresa.
- Em ambientes Linux, a simulação contínua usa `python3` para criar subprocessos.

## Segurança

Este projeto pode lidar com dados sensíveis da máquina, como usuário, endereço MAC, lista de processos e caminhos de executáveis. Recomendações:

- Não commitar credenciais no repositório.
- Adicionar `.env` e `.env.dev` ao `.gitignore`.
- Revisar quais campos serão enviados para S3.
- Restringir acesso ao bucket S3.
- Evitar expor dados de processos em ambientes públicos.

## Documentação complementar

Consulte o arquivo [`documento_definicao_metricas.md`](./documento_definicao_metricas.md) para entender a lógica de análise das métricas, incluindo CPU, RAM, swap, disco, processos e latência.

## Status do projeto

Projeto em desenvolvimento para coleta, simulação e tratamento de métricas de infraestrutura no contexto do Systrain Track.
