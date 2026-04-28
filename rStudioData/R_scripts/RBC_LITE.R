install.packages(c(
  "tidyverse", "readr", "dplyr", "tidyr", "purrr", "ggplot2",
  "lubridate", "jsonlite", "stringr", "anomalize", "zoo", "plotly"
))

library(tidyverse)
library(lubridate)
library(plotly)
library(readr)
library(dplyr)
library(tidyr)
library(purrr)
library(ggplot2)
library(jsonlite)
library(stringr)
library(anomalize)
library(zoo)
library(patchwork)


df <- read_csv("df.csv")

df <- df %>%
  mutate(
    data_hora = ymd_hms(data_hora_iso),
    hora = hour(data_hora),
    dia = wday(data_hora, label = TRUE)
  )

summary(df)

df %>%
  select(percentual_uso_cpu, percentual_uso_ram, percentual_uso_disco) %>%
  cor()

ggplot(df, aes(data_hora)) +
  geom_line(aes(y = percentual_uso_cpu), color = "red") +
  geom_line(aes(y = percentual_uso_ram), color = "blue") +
  geom_line(aes(y = percentual_uso_disco), color = "green") +
  labs(title = "Uso de recursos ao longo do tempo")

df <- df %>%
  mutate(
    cpu_alta = percentual_uso_cpu > 80,
    ram_alta = percentual_uso_ram > 80,
    disco_alto = percentual_uso_disco > 85,
    swap_critico = percentual_uso_swap > 50,
    latencia_alta = latencia_ping_ms > 150
  )

df %>%
  summarise(
    cpu_critico = mean(cpu_alta, na.rm = TRUE) * 100,
    ram_critico = mean(ram_alta, na.rm = TRUE) * 100,
    disco_critico = mean(disco_alto, na.rm = TRUE) * 100,
    swap_critico_pct = mean(swap_critico, na.rm = TRUE) * 100
  )

python_list_to_json <- function(x) {
  x %>%
    str_replace_all("\\bNone\\b", "null") %>%
    str_replace_all("\\bTrue\\b", "true") %>%
    str_replace_all("\\bFalse\\b", "false") %>%
    str_replace_all("'", "\"")
}

parse_processos <- function(x) {
  if (is.na(x) || x == "" || x == "[]") return(NULL)
  
  x_json <- python_list_to_json(x)
  
  tryCatch(
    fromJSON(x_json, simplifyVector = FALSE),
    error = function(e) NULL
  )
}

df$processos_list <- lapply(df$processos, parse_processos)

df$quantidade_processos <- purrr::map_int(
  df$processos_list,
  ~ if (is.null(.x)) 0 else length(.x)
)

processos_df <- df %>%
  mutate(
    linha = row_number(),
    processos_list = lapply(processos, parse_processos)
  ) %>%
  select(linha, data_hora_iso, processos_list) %>%
  mutate(
    processos_list = map(processos_list, ~ if (is.null(.x)) list() else .x)
  ) %>%
  unnest_longer(processos_list) %>%
  unnest_wider(processos_list)

df <- df %>%
  mutate(
    health_score = 100 - (
      percentual_uso_cpu * 0.3 +
        percentual_uso_ram * 0.3 +
        percentual_uso_disco * 0.2 +
        percentual_uso_swap * 0.2
    )
  )

df <- df %>%
  mutate(
    cpu_z = (percentual_uso_cpu - mean(percentual_uso_cpu, na.rm = TRUE)) /
      sd(percentual_uso_cpu, na.rm = TRUE),
    anomalia_cpu = abs(cpu_z) > 2
  )

df <- df %>%
  mutate(
    uso_memoria = percentual_uso_ram,
    uso_swap = percentual_uso_swap
  )

df <- df %>%
  mutate(
    score =
      percentual_uso_cpu * 0.3 +
      uso_memoria * 0.3 +
      percentual_uso_disco * 0.2 +
      uso_swap * 0.2
  )

df <- df %>%
  mutate(
    classe_refinada = case_when(
      score > 85 ~ "CRITICO",
      score > 70 ~ "ALTO",
      score > 50 ~ "MODERADO",
      TRUE ~ "BAIXO"
    )
  )

df <- df %>%
  mutate(
    ram_critica = percentual_uso_ram >= 85,
    swap_critico = percentual_uso_swap >= 30,
    swap_ativo = swap_entrada_bytes > 0 | swap_saida_bytes > 0,
    anomalia_ram_regra = ram_critica | (percentual_uso_ram >= 80 & swap_critico)
  )


df <- df %>%
  arrange(data_hora) %>%
  mutate(
    ram_media_movel = zoo::rollmean(percentual_uso_ram, k = 30, fill = NA, align = "right"),
    ram_sd_movel = zoo::rollapply(percentual_uso_ram, width = 30, FUN = sd, fill = NA, align = "right"),
    z_ram_local = (percentual_uso_ram - ram_media_movel) / ram_sd_movel,
    anomalia_ram = abs(z_ram_local) > 3
  )

ggplot(df, aes(data_hora, percentual_uso_ram)) +
  geom_line() +
  geom_point(
    data = df %>% filter(anomalia_ram),
    aes(data_hora, percentual_uso_ram),
    color = "red"
  )

df <- df %>%
  mutate(
    classe_ram = case_when(
      percentual_uso_ram >= 90 & percentual_uso_swap >= 40 ~ "MEMORIA_CRITICA",
      percentual_uso_ram >= 85 & (swap_entrada_bytes > 0 | swap_saida_bytes > 0) ~ "PRESSAO_DE_MEMORIA",
      anomalia_ram ~ "ANOMALIA_RAM",
      TRUE ~ "NORMAL"
    )
  )














df <- df %>%
  mutate(
    delta_ram = percentual_uso_ram - lag(percentual_uso_ram, default = first(percentual_uso_ram)),
    media_movel_ram = zoo::rollmean(percentual_uso_ram, k = 30, fill = NA, align = "right")
  )











df <- df %>%
  mutate(
    classe_ram = case_when(
      percentual_uso_ram >= 90 & percentual_uso_swap >= 40 ~ "MEMORIA_CRITICA",
      percentual_uso_ram >= 85 & swap_ativo ~ "PRESSAO_DE_MEMORIA",
      percentual_uso_ram >= 80 & delta_ram > 0 & lead(media_movel_ram, 10) > media_movel_ram ~ "SUSPEITA_MEMORY_LEAK",
      anomalia_ram ~ "ANOMALIA_RAM",
      TRUE ~ "NORMAL"
    )
  )

df %>%
  filter(percentual_uso_cpu > 85) %>%
  select(data_hora, percentual_uso_cpu, quantidade_processos)

df %>%
  ggplot(aes(data_hora)) +
  geom_line(aes(y = percentual_uso_ram)) +
  geom_line(aes(y = percentual_uso_swap), color = "red")

ggplot(df, aes(data_hora)) +
  geom_line(aes(y = taxa_escrita_disco_bytes_por_segundo), color = "red") +
  geom_line(aes(y = taxa_leitura_disco_bytes_por_segundo), color = "steelblue")




ggplot(df, aes(x = data_hora)) +
  geom_line(aes(y = taxa_download_rede_bytes_por_segundo), color = "red") +
  geom_line(aes(y = latencia_ping_ms * 10000), color = "blue") +
  scale_y_continuous(
    name = "Download (bytes/s)",
    sec.axis = sec_axis(~ . / 10000, name = "Latência (ms)")
  ) +
  labs(title = "Rede: Download vs Latência")

p1 <- ggplot(df, aes(data_hora, taxa_download_rede_bytes_por_segundo)) +
  geom_line() +
  labs(title = "Download")

p2 <- ggplot(df, aes(data_hora, latencia_ping_ms)) +
  geom_line() +
  labs(title = "Latência")


p1 / p2

df %>%
  group_by(hora) %>%
  summarise(cpu_media = mean(percentual_uso_cpu, na.rm = TRUE)) %>%
  ggplot(aes(hora, cpu_media)) +
  geom_line()

processos_df %>%
  group_by(name) %>%
  summarise(cpu_medio = mean(cpu_percent, na.rm = TRUE)) %>%
  arrange(desc(cpu_medio)) %>%
  head(10)

processos_df %>%
  group_by(name) %>%
  summarise(mem_medio = mean(memory_percent, na.rm = TRUE)) %>%
  arrange(desc(mem_medio)) %>%
  head(10)

ggplot(df, aes(data_hora, health_score)) +
  geom_line() +
  labs(title = "Saúde da máquina")

ts_cpu <- df %>%
  select(data_hora, percentual_uso_cpu)

ggplot(df, aes(data_hora, percentual_uso_cpu)) +
  geom_line() +
  geom_point(
    data = df %>% filter(anomalia_cpu),
    aes(data_hora, percentual_uso_cpu),
    color = "red"
  )
