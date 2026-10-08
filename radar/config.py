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
        "instalacao eletrica", "instalacoes eletricas", "instalacao electrica", "instalacoes electricas",
        "rede eletrica", "redes eletricas", "infraestruturas eletricas", "infraestrutura eletrica",
        "sistemas eletricos", "sistema eletrico", "material eletrico", "quadro eletrico", "quadros eletricos",
        "quadro de comando", "quadro geral", "iluminacao publica", "iluminacao exterior", "iluminacao interior",
        "luminarias", "luminaria", "cablagem", "baixa tensao", "media tensao", "posto de transformacao",
        "remodelacao eletrica", "eletricista", "eletricidade", "electricidade", "domotica", "ups",
        "grupo gerador", "ligacao a rede eletrica", "ramal eletrico", "ramais eletricos", "deteccao de incendio",
        "sadi", "cctv", "videovigilancia", "controlo de acessos",
    ],
    "projeto": [
        "projeto de execucao", "projeto de execução", "projeto de especialidades", "projetos de especialidades",
        "projeto eletrico", "projeto electrico", "revisao de projeto", "projeto de instalacoes eletricas",
        "projeto de licenciamento", "projeto de iluminacao", "certificacao energetica", "auditoria energetica",
        "elaboracao de projeto", "elaboracao do projeto", "projetos de execucao", "fiscalizacao",
    ],
    "mobilidade_eletrica": [
        "posto de carregamento", "postos de carregamento", "carregador de veiculo", "carregadores de veiculo",
        "carregador para veiculo", "carregadores para veiculo", "carregamento de veiculo", "carregamento eletrico",
        "carregamento electrico", "mobilidade eletrica", "mobilidade electrica", "carregador electrico", "carregador eletrico",
        "carregadores eletricos", "wallbox", "mobi.e", "mobie",
    ],
    "software_ti": [
        "software", "aplicacao movel", "aplicacao web", "aplicacao informatica", "desenvolvimento de aplicacao",
        "plataforma digital", "plataforma web", "plataforma online", "plataforma informatica", "plataforma de gestao",
        "sistema de informacao", "sistemas de informacao", "website", "web site", "portal", "sitio web", "site institucional",
        "rede informatica", "redes informaticas", "rede estruturada", "cablagem estruturada", "ciberseguranca",
        "seguranca informatica", "servicos informaticos", "consultoria informatica", "assistencia informatica",
        "manutencao informatica", "inteligencia artificial", "transformacao digital", "digitalizacao",
        "automatizacao", "automacao", "servidor", "servidores", "cloud", "backup", "firewall", "wi-fi", "wifi",
        "base de dados", "erp", "crm", "integracao de sistemas", "networking", "rede de dados", "switches", "data center", "datacenter",
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
EXCLUIR_CPV = ["09", "0931", "6421", "6422", "6431", "3410", "3411", "3414", "6351", "7980", "7981", "9830", "604", "5511", "5512"]  # energia, telecom, viaturas, viagens, impressão/cópia
# Padrões (regex sobre texto normalizado: minúsculas, sem acentos) — compras que não são serviço da VoltSync.
EXCLUIR_REGEX = [
    r"\b(aquisicao|fornecimento|locacao|aluguer|renting|compra) de (uma |um |duas |dois |\d+ )?(viatura|veiculo|autocarro|carrinha|furgao|automovel|ligeiro|bicicleta|trotinete)",
    r"\bviagens?\b", r"\balojamento\b", r"\bpassagens? aerea", r"\bbilhetes? de aviao", r"\b(impressao|copia|copias|fotocopia|multifuncoes|multifuncao)\b",
    r"\bconteudos\b", r"\bconsumiveis\b", r"\btoner",
    r"\bfestiv", r"\bnatal", r"\bornamental", r"\bdecorativ", r"\bsom e luz\b", r"\bsom, luz\b", r"\bledwall", r"\bpalco",
    r"\bplataformas? elevatori", r"\bmobiliario\b", r"\btablets?\b", r"\bleasing\b", r"\bfurg", r"\bcadeiras?\b",
    r"\bacesso a internet\b", r"\bservicos? de comunicacoes\b", r"\bcircuitos? de dados\b", r"\bcomunicacoes de voz\b",
    r"\bbombas?\b", r"\beletrobomba", r"\bequipamento medico\b", r"\bcirurgic",
]

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
