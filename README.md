# Radar VoltSync

Prospeção automática de trabalho para a VoltSync, Lda (instalações elétricas, projeto elétrico,
mobilidade elétrica, software e consultoria TI) no Minho.

Corre no GitHub Actions todos os dias úteis às 06:40 (Lisboa) e escreve em `data/`:

| Ficheiro | O que é | Frequência |
|---|---|---|
| `data/anuncios.json` / `data/anuncios_resumo.md` | Concursos públicos abertos que encaixam no perfil (A = Minho, B = fora do Minho, C = fora de perfil) | diária |
| `data/base_minho.json` / `data/base_minho_resumo.md` | Quem contratou eletricidade/projeto/software no Minho nos últimos 18 meses, por que procedimento e a quem (lista de prospeção comercial e mapa da concorrência) | segundas-feiras |

Fontes: Portal BASE (base.gov.pt), dataset oficial do IMPIC em dados.gov.pt, Diário da República (Parte L), BidsFactory (agregador, recurso).

Como lê o BASE: abre o portal num Chromium real (Playwright), escolhe "Anúncios DR", pesquisa, e depois repete o
pedido ajax do próprio portal (`/Base4/pt/resultados/`, `type=search_anuncios`) na mesma sessão para ler as páginas
seguintes (JSON com `contractDesignation`, `contractingEntity`, `basePrice`, `proposalDeadline`, `drPublicationDate`, `id`).
Pedidos diretos sem browser são bloqueados pelo portal (devolvem `null`).

Classes: **A** = perfil + Minho (distritos de Braga e Viana do Castelo). **B** = perfil, fora do Minho, mas
alcançável: obra/instalação só no Norte (`DISTRITOS_NORTE`), serviços/projeto/software em qualquer ponto do país até
`TETO_B_SERVICOS_EUR` (250.000 €). **C** = resto (listado em 1 linha, para subempreitada).

O perfil (CPV, palavras-chave, exclusões, concelhos, tetos) está em `radar/config.py`. Nada mais precisa de ser tocado.
Diagnóstico de cada execução: `data/log_anuncios.txt`, `data/log_base.txt`, `data/base_debug.txt`.

Os relatórios são lidos todos os dias por um agente Claude ("Radar VoltSync") que os cruza com o DR e entrega o resumo ao Helder.

Correr à mão: Actions → "Radar VoltSync" → "Run workflow".
