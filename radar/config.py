"""Perfil de prospeção da VoltSync, Lda (alvará IMPIC 117403-PUB).

Tudo o que o radar filtra vem daqui. Ajustar aqui, não nos scripts.
"""

# Prefixos CPV (Vocabulário Comum para os Contratos Públicos) que interessam.
# Comparação por prefixo: "45310000" apanha 45310000-3, 45311000-0, 45311100-1, ...
CPV_PREFIXOS = {
    "eletricidade": [
        "45310",  # instalação elétrica (geral)
        "45311",  # cablagem e aparelhagem elétrica
        "45312",  # alarmes, antenas, elevadores (sistemas)
        "45314",  # telecomunicações (cablagem estruturada)
        "45315",  # aquecimento elétrico e outras instalações elétricas de edifícios
        "45316",  # iluminação e sinalização
        "45317",  # outras instalações elétricas
        "50711",  # manutenção de instalações elétricas de edifícios
        "50532",  # manutenção de equipamento elétrico
        "31500",  # material de iluminação
        "31600",  # equipamento elétrico
        "31700",  # material eletrónico/eletrotécnico
    ],
    "projeto": [
        "71314",  # serviços de energia e afins (projeto elétrico)
        "71321",  # projeto de instalações mecânicas e elétricas
        "71323",  # projeto de sistemas industriais de energia
        "71334",  # engenharia mecânica e elétrica
        "71240",  # arquitetura/engenharia/planeamento
        "71310",  # consultoria de engenharia
    ],
    "mobilidade_eletrica": [
        "31158",  # carregadores
        "31681",  # acessórios elétricos (carregadores)
        "45223",  # estruturas/parques (quando com carregamento)
    ],
    "software_ti": [
        "72000",  # serviços TI (geral)
        "72200",  # programação e consultoria de software
        "72210",  # programação de pacotes de software
        "72220",  # consultoria de sistemas e técnica
        "72260",  # serviços relacionados com software
        "72300",  # serviços de dados
        "72400",  # serviços internet
        "72500",  # serviços informáticos
        "72600",  # apoio e consultoria informática
        "72700",  # redes informáticas
        "48000",  # pacotes de software e sistemas de informação
        "32400",  # redes
        "32420",  # equipamento de rede
        "30200",  # equipamento informático
    ],
}

# Palavras-chave no objeto/título (minúsculas, sem acentos tratados à parte).
KEYWORDS = {
    "eletricidade": [
        "eletric", "electric", "iluminacao", "iluminação", "quadro eletrico", "quadro elétrico",
        "cablagem", "baixa tensao", "baixa tensão", "posto de transformacao", "posto de transformação",
        "remodelacao eletrica", "remodelação elétrica", "luminaria", "luminária", "led",
    ],
    "projeto": [
        "projeto de execucao", "projeto de execução", "projeto de especialidades", "projetos de especialidades",
        "projeto eletrico", "projeto elétrico", "revisao de projeto", "revisão de projeto",
    ],
    "mobilidade_eletrica": [
        "carregamento", "carregador", "veiculos eletricos", "veículos elétricos", "mobilidade eletrica",
        "mobilidade elétrica", "posto de carregamento",
    ],
    "software_ti": [
        "software", "aplicacao", "aplicação", "plataforma", "sistema de informacao", "sistema de informação",
        "website", "portal", "sitio web", "sítio web", "rede informatica", "rede informática", "ciberseguranca",
        "cibersegurança", "informatic", "informátic", "inteligencia artificial", "inteligência artificial",
        "digitalizacao", "digitalização", "automatizacao", "automatização", "servidores", "cloud",
    ],
}

# Exclusões: se o objeto/CPV contiver isto, o registo não interessa (fornecimentos, não serviços).
EXCLUIR = [
    "fornecimento de energia", "fornecimento de eletricidade", "fornecimento de electricidade", "energia eletrica em regime",
    "aquisicao de energia", "aquisição de energia", "aquisicao de eletricidade", "aquisição de eletricidade",
    "combustivel", "combustível", "gasoleo", "gasóleo", "gasolina", "gas natural", "gás natural", "pellets",
    "licenciamento microsoft", "licenciamento da plataforma", "renovacao do licenciamento", "renovação do licenciamento",
    "subscricao", "subscrição", "telecomunicacoes", "telecomunicações", "comunicacoes moveis", "comunicações móveis",
    "seguro", "limpeza", "viaturas", "pneus",
]
EXCLUIR_CPV = ["09", "0931", "6421", "6422", "6431", "3410", "3411"]  # energia/combustíveis, telecomunicações, viaturas

# Geografia prioritária: concelhos do Minho (distritos de Braga e Viana do Castelo).
CONCELHOS_MINHO = [
    # Braga
    "Amares", "Barcelos", "Braga", "Cabeceiras de Basto", "Celorico de Basto", "Esposende", "Fafe",
    "Guimarães", "Póvoa de Lanhoso", "Terras de Bouro", "Vieira do Minho", "Vila Nova de Famalicão",
    "Vila Verde", "Vizela",
    # Viana do Castelo
    "Arcos de Valdevez", "Caminha", "Melgaço", "Monção", "Paredes de Coura", "Ponte da Barca",
    "Ponte de Lima", "Valença", "Viana do Castelo", "Vila Nova de Cerveira",
]
DISTRITOS_MINHO = ["Braga", "Viana do Castelo"]

# Entidades do Minho que não têm o concelho no nome.
ENTIDADES_MINHO = [
    "Universidade do Minho", "IPCA", "Instituto Politécnico do Cávado", "ULS de Braga", "Unidade Local de Saúde de Braga",
    "ULS do Alto Minho", "Unidade Local de Saúde do Alto Minho", "AGERE", "Águas do Norte", "CIM do Cávado", "CIM do Ave",
    "CIM do Alto Minho", "TUB", "Transportes Urbanos de Braga", "Vimágua", "Vitrus", "Resulima", "Resinorte",
    "Hospital de Braga", "Santa Casa da Misericórdia de Braga", "Braga Habit", "InvestBraga", "BragaParques",
]

# Teto de empreitada considerado (ajustar à classe do alvará quando confirmada). None = sem teto.
TETO_EMPREITADA_EUR = None

# Quantos meses de contratos a analisar no mapa de "quem contrata".
MESES_HISTORICO = 18
