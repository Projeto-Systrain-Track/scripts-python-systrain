install.packages(c("readr", "dplyr", "tidyr", "purrr", "ggplot2", "lubridate", "jsonlite", "stringr"))

library(plotly)
library(readr)
library(dplyr)
library(tidyr)
library(purrr)
library(ggplot2)
library(lubridate)
library(jsonlite)
library(stringr)


#                 ______  __       __  _______    ______   _______   ________  ________                     ______                     _______   ________                   ______    ______   __     __ 
#                /      |/  \     /  |/       \  /      \ /       \ /        |/        |                   /      \                   /       \ /        |                 /      \  /      \ /  |   /  |
#                $$$$$$/ $$  \   /$$ |$$$$$$$  |/$$$$$$  |$$$$$$$  |$$$$$$$$/ $$$$$$$$/                   /$$$$$$  |                  $$$$$$$  |$$$$$$$$/                 /$$$$$$  |/$$$$$$  |$$ |   $$ |
#                  $$ |  $$$  \ /$$$ |$$ |__$$ |$$ |  $$ |$$ |__$$ |   $$ |   $$ |__                      $$ |  $$ |                  $$ |  $$ |$$ |__                    $$ |  $$/ $$ \__$$/ $$ |   $$ |
#                  $$ |  $$$$  /$$$$ |$$    $$/ $$ |  $$ |$$    $$<    $$ |   $$    |                     $$ |  $$ |                  $$ |  $$ |$$    |                   $$ |      $$      \ $$  \ /$$/ 
#                  $$ |  $$ $$ $$/$$ |$$$$$$$/  $$ |  $$ |$$$$$$$  |   $$ |   $$$$$/                      $$ |  $$ |                  $$ |  $$ |$$$$$/                    $$ |   __  $$$$$$  | $$  /$$/  
#                 _$$ |_ $$ |$$$/ $$ |$$ |      $$ \__$$ |$$ |  $$ |   $$ |   $$ |_____                   $$ \__$$ |                  $$ |__$$ |$$ |             __       $$ \__/  |/  \__$$ |  $$ $$/   
#                / $$   |$$ | $/  $$ |$$ |      $$    $$/ $$ |  $$ |   $$ |   $$       |                  $$    $$/                   $$    $$/ $$ |            /  |      $$    $$/ $$    $$/    $$$/    
#                $$$$$$/ $$/      $$/ $$/        $$$$$$/  $$/   $$/    $$/    $$$$$$$$/                    $$$$$$/                    $$$$$$$/  $$/             $$/        $$$$$$/   $$$$$$/      $/     
                                                                                                                                                                                        
                                                                                                                                                                                        
df <- df %>%
  mutate(data = ymd_hms(data))


# INDICAR GARGALO DE CPU
# UM CHECK PARA SABER SE
# CPU ESTA SENDO USADA DE FORMA INEFICIENTE E/OU ESTA DEGRADADA


df <- df %>%
  mutate(
    cpu_gargalo_flag = porcentagem_uso_da_cpu > 50 &
      frequencia_atual < 0.6 * frequencia_max
  )



# INDICA USO EXESSIVO DE RAM
df <- df %>%
  mutate(
    memoria_livre_gib = memoria_livre / (1024 * 1024 * 1024),
    memoria_baixa_flag = memoria_livre_gib < 48.15
  )


formatar_processos <- function(x) {
  x %>%
    str_replace_all("'", "\"") %>%
    str_replace_all("None", "null") %>%
    str_replace_all("True", "true") %>%
    str_replace_all("False", "false")
}


processos_df <- df %>%
  mutate(processos_json = purrr::map(processos, formatar_processos)) %>%
  mutate(processos_list = purrr::map(processos_json, ~ fromJSON(.x, simplifyDataFrame = TRUE)))


proc_long <- processos_df %>%
  select(data, processos_list) %>%
  mutate(processos_list = purrr::map(processos_list, as_tibble)) %>%
  unnest(processos_list)


proc_long <- proc_long %>%
  unnest_wider(memory_info, names_sep = "_")







ggplotly(
  ggplot(df, aes(x = data, y = porcentagem_uso_da_cpu)) +
    geom_line() +
    labs(
      title = "USO DE CPU POR MINUTO",
      x = "TEMPO",
      y = "CPU (%)"
    ) +
    theme_minimal()
)


ggplot(df, aes(x = data, y = frequencia_atual)) +
  geom_line() +
  labs(
    title = "USO DE CPU POR MINUTO",
    x = "TEMPO",
    y = "FREQUENCIA CPU (HTZ)"
  ) +
  theme_minimal()


ggplot(df, aes(x = data, y = memoria_livre / 1024^3)) +
  geom_line() +
  labs(
    title = "MEMORIA LIVRE POR MINUTO",
    x = "TEMPO",
    y = "MEMORIA LIVRE (GiB)"
  ) +
  theme_minimal()


df_io <- df %>%
  select(data, read_rate_Bps, write_rate_Bps) %>%
  pivot_longer(
    cols = c(read_rate_Bps, write_rate_Bps),
    names_to = "metric",
    values_to = "value"
  )

ggplot(df_io, aes(x = data, y = value, color = metric)) +
  geom_line() +
  labs(
    title = "Disk I/O",
    x = "TEMPO",
    y = "BYTES POR SEGUNDO"
  ) +
  theme_minimal()




ggplot(df, aes(x = data, y = porcentagem_uso_da_cpu)) +
  geom_line() +
  geom_point(
    data = df %>% filter(cpu_gargalo_flag),
    aes(x = data, y = porcentagem_uso_da_cpu),
    size = 1,
    color = "red"
  ) +
  labs(
    title = "CPU USO COM GARGALOS EM VERMELHOs",
    x = "TEMPO",
    y = "CPU (%)"
  ) +
  theme_minimal()








ggplot(df, aes(x = data, y = memoria_livre_gib)) +
  geom_line() +
  geom_point(
    data = df %>% filter(memoria_baixa_flag),
    aes(x = data, y = memoria_livre_gib),
    size = 3,
    color = "red"
  ) +
  labs(
    title = "MEMORIA LIVRE COM PONTOS DE SOBREUSO",
    x = "TEMPO",
    y = "MEMORIA LIVRE (GiB)"
  ) +
  theme_minimal()






ggplotly(
  ggplot(proc_long, aes(x = data, y = cpu_percent, color = name)) +
    geom_line() +
    labs(
      title = "Per-process CPU usage",
      x = "Time",
      y = "CPU (%)"
    ) +
    theme_minimal() 
)


ggplot(proc_long, aes(x = data, y = memory_info_rss / 1024^2, color = name)) +
  geom_line() +
  labs(
    title = "Per-process RSS memory",
    x = "Time",
    y = "RSS (MiB)"
  ) +
  theme_minimal()


