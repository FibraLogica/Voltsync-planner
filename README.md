# Radar VoltSync

Prospeção automática de trabalho para a VoltSync, Lda (instalações elétricas, projeto elétrico,
mobilidade elétrica, software e consultoria TI) no Minho.

Corre no GitHub Actions todos os dias úteis às 06:40 (Lisboa) e escreve em `data/`:

| Ficheiro | O que é | Frequência |
|---|---|---|
| `data/anuncios.json` / `data/anuncios_resumo.md` | Concursos públicos abertos que encaixam no perfil (A = Minho, B = fora do Minho, C = fora de perfil) | diária |
| `data/base_minho.json` / `data/base_minho_resumo.md` | Quem contratou eletricidade/projeto/software no Minho nos últimos 18 meses, por que procedimento e a quem (lista de prospeção comercial e mapa da concorrência) | segundas-feiras |

Fontes: Portal BASE (base.gov.pt), dataset oficial do IMPIC em dados.gov.pt, Diário da República (Parte L), BidsFactory (agregador, recurso).

Como lê o BASE (desde 2026-10-26): abre o portal num Chromium real (Playwright), escolhe "Anúncios DR", pesquisa, e
depois faz os pedidos ajax do próprio portal (`/Base4/pt/resultados/`, `type=search_anuncios`) **a partir do browser**
(`page.evaluate(fetch)`), página a página (25 por página), até passar a data de início da janela. Pedidos feitos pelo
Node/Playwright fora do browser falham desde 2026-10-20 porque o portal deixou de enviar o certificado intermédio;
pedidos sem browser são bloqueados (devolvem `null`). Para cada anúncio lê o detalhe (`type=detail_anuncios`): CPV,
NIF, tipo de contrato, prazo, plataforma, n.º no DR, PDF do DR e id do procedimento — a classificação usa o CPV e o
objeto, não só o título.

Ritmo: ~1 pedido por segundo, em **lotes de ~150 pedidos com uma hora de pausa entre lotes** (o portal tem uma
firewall, WebKnight, que bloqueia o IP por mais de 15 min ao fim de ~200 pedidos numa janela de cerca de uma hora,
independentemente do ritmo — daí o `timeout-minutes: 180` no workflow; cada execução do Actions tem IP novo). Os detalhes lêem-se por prioridade: pendentes da execução anterior → relevantes pelo título ou
Minho → alterações de procedimentos seguidos → o resto (descoberta pelo CPV). Se a firewall bloquear ou acabar o
tempo, o que ficou por ler fica marcado `detalhe_pendente` (classificado só pelo título) e completa-se na execução
seguinte. A data-limite das propostas vem da lista (data absoluta); o detalhe só traz «N dias», usado como
estimativa (`prazo_estimado`) quando a lista não a tiver.

A lista é **cumulativa**: cada execução lê os últimos 7 dias (30 na primeira, ou até à última leitura completa),
funde com a lista anterior e só retira os anúncios cujo prazo de propostas já passou (ou, sem prazo conhecido, com
mais de 45 dias). Uma retificação/prorrogação fica registada no anúncio original (`alteracoes`) e pode alargar-lhe o
prazo; não aparece como concurso novo. Campos por anúncio: `origem`, `id`, `url`, `titulo`, `entidade`, `nif`,
`tipo_ato`, `procedimento`, `tipo_contrato`, `preco_base`, `publicado`, `prazo_propostas` (ISO; `prazo_estimado`
quando foi calculado a partir de «N dias»), `cpv`, `n_dr`, `dr_pdf`, `plataforma_url`, `procedimento_id`,
`categorias`, `minho`, `classe`, `primeira_vez`, `ultima_vez`, `alteracoes`, `detalhe_pendente`. O cabeçalho do
ficheiro traz `estatisticas` (base_ok, leitura_completa, ultima_leitura_ok, firewall_bloqueou, detalhes_pendentes…).
`data/anuncios_vistos.json` guarda, por 60 dias, os ids cujo detalhe já foi lido e não interessou, para não os
reler todos os dias (uma alteração ao perfil só se aplica a esses passados os 60 dias).

BidsFactory só entra quando o BASE não responde (é um espelho do próprio BASE e enviesava a lista para compras de
material informático). Compras puras de bens (sem instalação) e de licenças/equipamento informático ficam de fora.

Classes: **A** = perfil + Minho (distritos de Braga e Viana do Castelo). **B** = perfil, fora do Minho, mas
alcançável: obra/instalação só no Norte (`DISTRITOS_NORTE`), serviços/projeto/software em qualquer ponto do país até
`TETO_B_SERVICOS_EUR` (250.000 €). **C** = Minho mas fora de perfil, acima do alvará (classe 2: 332.000 €) ou só
fornecimento (listado em 1 linha, para subempreitada/consórcio). Fora do Minho e fora de perfil não entra.

Correr à mão com outra janela: `RADAR_DESDE=AAAA-MM-DD python anuncios.py` (máximo 45 dias para trás).

O perfil (CPV, palavras-chave, exclusões, concelhos, tetos) está em `radar/config.py`. Nada mais precisa de ser tocado.
Diagnóstico de cada execução: `data/log_anuncios.txt`, `data/log_base.txt`, `data/base_debug.txt`.

Os relatórios são lidos todos os dias por um agente Claude ("Radar VoltSync") que os cruza com o DR e entrega o resumo ao Helder.

Correr à mão: Actions → "Radar VoltSync" → "Run workflow".
