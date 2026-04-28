install.packages(c(
  "dplyr", "ggplot2",
  "stringr", "plotly", "htmlwidgets"
))



library("dplyr")
library("ggplot2")
library("stringr")
library("plotly")
library("htmlwidgets")



linhaAzul <- data[,2:25];
linhaVerde <- data[,28:42];
linhaVermelha <- data[,45:63];

linhaPrata <- data[,66:77];


nomesEstacoesLinhaAzul <- c(
  "jabaquara", "conceicao", "saoJudas", "saude", "pracaDaArvore",
  "santaCruz", "vilaMariana", "anaRosa", "paraiso", "vergueiro",
  "saoJoaquim", "liberdade", "se", "saoBento", "luz",
  "tiradentes", "amenia", "portuguesaTiete", "carandiru",
  "santana", "jardimSaoPaulo", "paradaInglesa", "tucuruvi", "total"
)
nomesEstacoesLinhaVerde <- c(
  "vilaMadalena",  "sumare",  "clinicas",  "consolacao",
  "trianonMasp",  "brigadeiro",  "paraiso",  "anaRosa",
  "chacaraKlabin",  "santosImigrantes",  "altoDoIpiranga",
  "sacoma",  "tamanduatei",  "vilaPrudente",  "total"
)
nomesEstacoesLinhaVermelha <- c(
  "palmeirasBarraFunda",  "marechalDeodoro",  "santaCecilia",
  "republica",  "anhangabau",  "se",  "pedroII",  "bras",
  "bresserMooca",  "belem",  "tatuape",  "carraoAssaiAtacadista",
  "penhaLojasBesni",  "vilaMatilde",  "guilherminaEsperanca",
  "patriarcaVilaRe",  "arturAlvim",  "corinthiansItaquera",  "total"
)
nomesEstacoesLinhaPrata <- c(
  "vilaPrudente",  "oratorio",  "saoLucas",  "camiloHaddad",
  "vilaTolstoi",  "vilaUniao",  "jardimPlanalto",  "sapopemba",
  "fazendaDaJuta",  "saoMateus",  "jardimColonial",  "total"
)






intervaloMeses <- list(
  janeiro = c(7, 38),
  fevereiro = c(43, 74),
  marco = c(79, 110),
  abril = c(115, 146),
  maio = c(150, 181),
  junho = c(185, 216),
  julho = c(220, 251),
  agosto = c(255, 286),
  setembro = c(290, 321),
  outubro = c(325, 356),
  novembro = c(360, 391),
  dezembro = c(395, 426)
)


processarMesAzul <- function(data, inicio, fim, nomesEstacoesLinhaAzul) {
  data %>%
    slice(inicio:fim) %>%
    setNames(nomesEstacoesLinhaAzul)
}
linhaAzulMeses <- list()
for (mes in names(intervaloMeses)) {
  intervalo <- intervaloMeses[[mes]]
  linhaAzulMeses[[mes]] <- processarMesAzul(
    linhaAzul,
    intervalo[1],
    intervalo[2],
    nomesEstacoesLinhaAzul
  )
}




processarMesVerde <- function(data, inicio, fim, nomesEstacoesLinhaVerde) {
  data %>%
    slice(inicio:fim) %>%
    setNames(nomesEstacoesLinhaVerde)
}
linhaVerdeMeses <- list()
for (mes in names(intervaloMeses)) {
  intervalo <- intervaloMeses[[mes]]
  linhaVerdeMeses[[mes]] <- processarMesVerde(
    linhaVerde,
    intervalo[1],
    intervalo[2],
    nomesEstacoesLinhaVerde
  )
}



processarMesVermelha <- function(data, inicio, fim, nomesEstacoesLinhaVermelha) {
  data %>%
    slice(inicio:fim) %>%
    setNames(nomesEstacoesLinhaVermelha)
}
linhaVermelhaMeses <- list()
for (mes in names(intervaloMeses)) {
  intervalo <- intervaloMeses[[mes]]
  linhaVermelhaMeses[[mes]] <- processarMesVermelha(
    linhaVermelha,
    intervalo[1],
    intervalo[2],
    nomesEstacoesLinhaVermelha
  )
}





processarMesPrata <- function(data, inicio, fim, nomesEstacoesLinhaPrata) {
  data %>%
    slice(inicio:fim) %>%
    setNames(nomesEstacoesLinhaPrata)
}
linhaPrataMeses <- list()
for (mes in names(intervaloMeses)) {
  intervalo <- intervaloMeses[[mes]]
  linhaPrataMeses[[mes]] <- processarMesPrata(
    linhaPrata,
    intervalo[1],
    intervalo[2],
    nomesEstacoesLinhaPrata
  )
}























mesEscolhido <- "janeiro"

  
  
ggplotly(
  ggplot(
    bind_rows(
      linhaAzulMeses[[mesEscolhido]] %>%
        slice(-n()) %>%
        mutate(dia = row_number(), linha = "Azul"),
      
      linhaVerdeMeses[[mesEscolhido]] %>%
        slice(-n()) %>%
        mutate(dia = row_number(), linha = "Verde"),
      
      linhaVermelhaMeses[[mesEscolhido]] %>%
        slice(-n()) %>%
        mutate(dia = row_number(), linha = "Vermelha"),
      linhaPrataMeses[[mesEscolhido]] %>%
        slice(-n()) %>%
        mutate(dia = row_number(), linha = "Prata")
    ),
    aes(x = dia, y = as.numeric(total), color = linha)
  ) +
    geom_line(linewidth = 1) +
    labs(
      title = paste("Comparação das Linhas no mês de", mesEscolhido),
      x = "Dia do mês",
      y = "Quantidade de passageiros"
    ) +
    theme_minimal()
)


ggplot(
bind_rows(
linhaAzulMeses[[mesEscolhido]] %>%
slice(-n()) %>%
mutate(dia = row_number(), linha = "Azul"),
linhaVerdeMeses[[mesEscolhido]] %>%
slice(-n()) %>%
mutate(dia = row_number(), linha = "Verde"),
linhaVermelhaMeses[[mesEscolhido]] %>%
slice(-n()) %>%
mutate(dia = row_number(), linha = "Vermelha"),
linhaPrataMeses[[mesEscolhido]] %>%
slice(-n()) %>%
mutate(dia = row_number(), linha = "Prata")
),
aes(x = dia, y = as.numeric(total), color = linha)
) +
geom_line(linewidth = 1) +
labs(
title = paste("Comparação das Linhas no mês de", mesEscolhido),
x = "Dia do mês",
y = "Quantidade de passageiros"
) +
theme_minimal()






saveWidget(
  p_interativo,
  "comparacao_linhas_janeiro.html",
  selfcontained = TRUE
)

































































