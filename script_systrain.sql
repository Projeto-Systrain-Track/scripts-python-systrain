drop database if exists systraintrack;
create database systraintrack;
use systraintrack;


CREATE TABLE empresa (
    idEmpresa INT AUTO_INCREMENT,
    razaoSocial VARCHAR(100) UNIQUE,
    token CHAR(10) UNIQUE,
    dataCadastro DATETIME DEFAULT CURRENT_TIMESTAMP,
    cnpj VARCHAR(40) UNIQUE,
    email VARCHAR(100),
    telefone VARCHAR(15) DEFAULT NULL,
    url_jira VARCHAR(200),
	email_usuario_jira VARCHAR(200),
	token_usuario_jira VARCHAR(200),
    PRIMARY KEY (idEmpresa)
);
INSERT INTO empresa (razaoSocial, token, dataCadastro, cnpj, email, telefone, url_jira, email_usuario_jira, token_usuario_jira) VALUES
('Via Paulista Mobilidade', 'VPMB1234A1', DEFAULT, '12345678000101', 'contato@viapaulista.com', '11987654321', '', '', '');


INSERT INTO empresa (razaoSocial, token, dataCadastro, cnpj, email, telefone) VALUES
('Ferrovia Bandeirante S.A.', 'FBSA5678B2', DEFAULT, '12345678000102', 'suporte@ferrobandeirante.com', '11987654322');

INSERT INTO empresa (razaoSocial, token, dataCadastro, cnpj, email, telefone, url_jira, email_usuario_jira, token_usuario_jira) VALUES
('Rota Trilhos Tecnologia', 'RTTC9012C3', DEFAULT, '12345678000103', 'atendimento@rotatrilhos.com', '11987654323', '','','');

CREATE TABLE linha (
    idLinha INT AUTO_INCREMENT,
    nomeLinha VARCHAR(45),
    corLinha VARCHAR(45),
    numeroLinha VARCHAR(45),
    trecho VARCHAR(45),
    fkEmpresa INT,
    PRIMARY KEY (idLinha),
    CONSTRAINT fkEmpresaLinha FOREIGN KEY (fkEmpresa) REFERENCES empresa (idEmpresa)
);

INSERT INTO linha(idLinha, nomeLinha, numeroLinha, corLinha, trecho, fkEmpresa) VALUES
(1, "DIAMANTE", 8,"#898989","Amador Bueno.", 1),
(2, "SAFIRA", 12, "#0F52BA", "Calmon Viana ", 1),
(3, "CORAL", 11, "#D75413", "Mogi das Cruzes", 2),
(4, "JADE",13, "#00A86B", "Aeroporto-Guarulhos", 2),
(5, "ESMERALDA",9, "#00674f", "Osasco", 3);


CREATE TABLE rbc (
    idRbc INT AUTO_INCREMENT,
    nomeServidor VARCHAR(45),
    macAdress VARCHAR(45) UNIQUE NOT NULL,
    fkLinha INT,
    objetivoFinanceiro DOUBLE,
    PRIMARY KEY (idRbc),
    CONSTRAINT fkLinhaRbc FOREIGN KEY (fkLinha) REFERENCES linha (idLinha)
);

INSERT INTO rbc (idRbc, nomeServidor, macAdress, objetivoFinanceiro, fkLinha) VALUES
(1,'SV-PRIM','81:09:80:5a:9c:47', 100.0,1),
(2,'SV-MHRT','c4:8b:08:05:ff:b6', 1100.0, 2),
(3,'SV-JOKT','13:47:52:e1:8a:7f', 1500.0, 2),
(4,'RB_ALPH','0c-cc-47-e3-5f-90', 1902.9, 5),
(5,'RB_BETA','06:71:a3:c2:10:07', 1900.9, 4),
(6,'RB_KAIO','50-b3-63-01-79-02', 1500.10, 5);

CREATE TABLE componente (
    idComponente INT AUTO_INCREMENT,
    nome VARCHAR(99),
    tipo VARCHAR(99),
    parametros VARCHAR(99),
    unidade VARCHAR(99) DEFAULT NULL,
    PRIMARY KEY (idComponente)
);

INSERT INTO componente (idComponente, nome, tipo, parametros, unidade) values
(1, "CPU_PER", "%", "uso de cpu", NULL),
(5, "RAM_PER", "%", "uso de ram", NULL),
(8, "VOL_PER", "%", "uso de disco", NULL),
(13, "WEB_NUM", "num", "latencia de rede", "ms"),
(16, "PRS_NUM", "num", "quantidade de processos", NULL),
(17, "PRS_STX", "txt", "sintaxe de prioridade", NULL),
(18, "PRS_RAM_PER", "%", "uso de ram", NULL),
(19, "PRS_RAM_USE", "num", "uso de memoria", "MB"),
(20, "PRS_CPU_PER", "%", "uso de cpu", NULL),
(21, "PRS_CPU_THR", "num", "quantidade de threads", NULL),
(22, 'SWP_PER', '%', 'uso de swap', NULL);


CREATE TABLE endereco (
    idEndereco INT AUTO_INCREMENT,
    estado VARCHAR(99),
    cep VARCHAR(9),
    numero VARCHAR(9),
    rua VARCHAR(99),
    complemento VARCHAR(99),
    fkEmpresa INT,
    PRIMARY KEY (idEndereco),
    CONSTRAINT fk_end_empresa FOREIGN KEY (fkEmpresa) REFERENCES empresa(idEmpresa)
);

INSERT INTO endereco (estado, cep, numero, rua, complemento, fkEmpresa) VALUES
('SP', '01001-000', '120', 'Rua da Consolação', 'Bloco A', 1),
('SP', '02002-000', '245', 'Avenida Tiradentes', 'Sala 12', 2),
('SP', '03003-000', '89', 'Rua Vergueiro', 'Andar 3', 3);


CREATE TABLE usuario (
    idUsuario INT AUTO_INCREMENT,
    nome VARCHAR(45),
    email VARCHAR(45) UNIQUE,
    senha VARCHAR(200),
    fkEmpresa INT,
    tipoUsuario VARCHAR(45),
    PRIMARY KEY (idUsuario),
    CONSTRAINT fk_empresa_usuario FOREIGN KEY (fkEmpresa) REFERENCES empresa (idEmpresa)
);

INSERT INTO usuario (nome, email, senha, fkEmpresa, tipoUsuario) VALUES
('Thiago', 'thiago@viapaulista.com', '12345', 1, "Operador"),
('Brandão', 'brandao@viapaulista.com', '12345', 1, "Gerente de operações"),
('Marina Souza', 'marina.souza@viapaulista.com', '12345', 1, "Coordenador de incidentes"),
('Carlos Henrique', 'carlos.henrique@ferrobandeirante.com', '12345', 2, "Operador"),
('Fernanda Lima', 'fernanda.lima@ferrobandeirante.com', '12345', 2, "Gerente de operações"),
('Henrique Lima', 'henrique.lima@ferrobandeirante.com', '12345', 2, "Coordenador de incidentes"),
('Alvares Tino', 'alvares.tino@rotatrilhos.com', '12345', 3, "Operador"),
('Thiago Alves', 'thiago.alves@rotatrilhos.com', '12345', 3, "Gerente de operações"),
('Amanda Castro', 'amanda.castro@rotatrilhos.com', '12345', 3, "Coordenador de incidentes");

CREATE TABLE rbcComponente (
    fkRbc INT,
    fkComponente INT,
    definicao VARCHAR(99),
    PRIMARY KEY(fkRbc, fkComponente),
    CONSTRAINT fk_componente_rbc FOREIGN KEY (fkComponente) REFERENCES componente(idComponente),
    CONSTRAINT fk_rbc_componente FOREIGN KEY (fkRbc) REFERENCES rbc(idRbc)
);

INSERT INTO rbcComponente (fkRbc, fkComponente, definicao) VALUES

-- CPU_PER
(1, 1, 'limite_alerta=85;limite_critico=95'),
(2, 1, 'limite_alerta=85;limite_critico=95'),
(3, 1, 'limite_alerta=85;limite_critico=95'),
(4, 1, 'limite_alerta=85;limite_critico=95'),
(5, 1, 'limite_alerta=85;limite_critico=95'),
(6, 1, 'limite_alerta=85;limite_critico=95'),

-- RAM_PER
(1, 5, 'limite_alerta=80;limite_critico=90'),
(2, 5, 'limite_alerta=80;limite_critico=90'),
(3, 5, 'limite_alerta=80;limite_critico=90'),
(4, 5, 'limite_alerta=80;limite_critico=90'),
(5, 5, 'limite_alerta=80;limite_critico=90'),
(6, 5, 'limite_alerta=80;limite_critico=90'),

-- VOL_PER
(1, 8, 'limite_alerta=80;limite_critico=90'),
(2, 8, 'limite_alerta=80;limite_critico=90'),
(3, 8, 'limite_alerta=80;limite_critico=90'),
(4, 8, 'limite_alerta=80;limite_critico=90'),
(5, 8, 'limite_alerta=80;limite_critico=90'),
(6, 8, 'limite_alerta=80;limite_critico=90'),

-- WEB_NUM
(1, 13, 'limite_alerta=120;limite_critico=250'),
(2, 13, 'limite_alerta=120;limite_critico=250'),
(3, 13, 'limite_alerta=120;limite_critico=250'),
(4, 13, 'limite_alerta=120;limite_critico=250'),
(5, 13, 'limite_alerta=120;limite_critico=250'),
(6, 13, 'limite_alerta=120;limite_critico=250'),

-- PRS_NUM
(1, 16, 'limite_alerta=250;limite_critico=350'),
(2, 16, 'limite_alerta=250;limite_critico=350'),
(3, 16, 'limite_alerta=250;limite_critico=350'),
(4, 16, 'limite_alerta=250;limite_critico=350'),
(5, 16, 'limite_alerta=250;limite_critico=350'),
(6, 16, 'limite_alerta=250;limite_critico=350'),

-- PRS_STX
(1, 17, 'RBC_'),
(2, 17, 'RBC_'),
(3, 17, 'RBC_'),
(4, 17, 'RBC_'),
(5, 17, 'RBC_'),
(6, 17, 'RBC_'),

-- PRS_RAM_PER
(1, 18, 'limite_alerta=10;limite_critico=20'),
(2, 18, 'limite_alerta=10;limite_critico=20'),
(3, 18, 'limite_alerta=10;limite_critico=20'),
(4, 18, 'limite_alerta=10;limite_critico=20'),
(5, 18, 'limite_alerta=10;limite_critico=20'),
(6, 18, 'limite_alerta=10;limite_critico=20'),

-- PRS_RAM_USE
(1, 19, 'limite_alerta=200;limite_critico=500'),
(2, 19, 'limite_alerta=200;limite_critico=500'),
(3, 19, 'limite_alerta=200;limite_critico=500'),
(4, 19, 'limite_alerta=200;limite_critico=500'),
(5, 19, 'limite_alerta=200;limite_critico=500'),
(6, 19, 'limite_alerta=200;limite_critico=500'),

-- PRS_CPU_PER
(1, 20, 'limite_alerta=15;limite_critico=30'),
(2, 20, 'limite_alerta=15;limite_critico=30'),
(3, 20, 'limite_alerta=15;limite_critico=30'),
(4, 20, 'limite_alerta=15;limite_critico=30'),
(5, 20, 'limite_alerta=15;limite_critico=30'),
(6, 20, 'limite_alerta=15;limite_critico=30'),

-- PRS_CPU_THR
(1, 21, 'limite_alerta=75;limite_critico=120'),
(2, 21, 'limite_alerta=75;limite_critico=120'),
(3, 21, 'limite_alerta=75;limite_critico=120'),
(4, 21, 'limite_alerta=75;limite_critico=120'),
(5, 21, 'limite_alerta=75;limite_critico=120'),
(6, 21, 'limite_alerta=75;limite_critico=120'),

-- SWP_PER
(1, 22, 'limite_alerta=50;limite_critico=80'),
(2, 22, 'limite_alerta=50;limite_critico=80'),
(3, 22, 'limite_alerta=50;limite_critico=80'),
(4, 22, 'limite_alerta=50;limite_critico=80'),
(5, 22, 'limite_alerta=50;limite_critico=80'),
(6, 22, 'limite_alerta=50;limite_critico=80');


CREATE TABLE administrador (
    idAdministrador INT AUTO_INCREMENT,
    nome VARCHAR(45),
    email VARCHAR(50) UNIQUE,
    senha VARCHAR(45),
    nivel INT,
    PRIMARY KEY (idAdministrador)
);

INSERT INTO administrador(nome, email, senha, nivel) VALUES
('Geraldo', 'geraldo@systrain', 'systrain_adm', 3);


CREATE TABLE faleConosco (
    idMensagem INT AUTO_INCREMENT,
    mensagem VARCHAR(400),
    emailContato VARCHAR(100),
    PRIMARY KEY (idMensagem)
);


CREATE TABLE eventoOperacional (
    idEvento INT AUTO_INCREMENT,
    titulo VARCHAR(45),
    descricao VARCHAR(45),
    classificacao VARCHAR(45),
    PRIMARY KEY (idEvento)
);
use systraintrack;
SELECT
	COUNT(r.idRbc) AS quantidade_servidores
    FROM rbc as r
		JOIN linha  as  l ON r.fkLinha   = l.idLinha
		JOIN empresa as e ON e.idEmpresa = l.fkEmpresa
	WHERE e.idEmpresa = 1 and l.idLinha = 2;
    