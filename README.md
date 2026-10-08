# Radar VoltSync

Prospeção automática de trabalho para a VoltSync, Lda (instalações elétricas, projeto elétrico,
mobilidade elétrica, software e consultoria TI) no Minho.

Corre no GitHub Actions todos os dias úteis às 06:40 (Lisboa) e escreve em `data/`:

| Ficheiro | O que é | Frequência |
|---|---|---|
| `data/anuncios.json` / `data/anuncios_resumo.md` | Concursos públicos abertos que encaixam no perfil (A = Minho, B = fora do Minho, C = fora de perfil) | diária |
| `data/base_minho.json` / `data/base_minho_resumo.md` | Quem contratou eletricidade/projeto/software no Minho nos últimos 18 meses, por que procedimento e a quem (lista de prospeção comercial e mapa da concorrência) | segundas-feiras |

Fontes: Portal BASE (base.gov.pt), dataset oficial do IMPIC em dados.gov.pt, Diário da República (Parte L), BidsFactory (agregador, recurso).

O perfil (CPV, palavras-chave, concelhos) está em `radar/config.py`. Nada mais precisa de ser tocado.

Os relatórios são lidos todos os dias por um agente Claude ("Radar VoltSync") que os cruza com o DR e entrega o resumo ao Helder.

Correr à mão: Actions → "Radar VoltSync" → "Run workflow".
