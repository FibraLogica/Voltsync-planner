"""Lista de prospeção comercial: entidades do Minho que contratam por convite (ajuste direto / consulta prévia)
nas categorias da VoltSync. Lê data/base_minho.json (gerado por base_contratos.py).

Saídas em data/:
  prospecao_minho.json    uma entrada por entidade, com NIF, contratos por categoria/procedimento, fornecedores
                          habituais, últimos contratos e uma pontuação de prioridade
  prospecao_minho.md      a mesma lista em tabela, ordenada por prioridade, pronta a trabalhar
  prospecao_minho.csv     para importar numa folha de cálculo / CRM
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import date

from common import DATA_DIR, nif_de, nome_limpo, save_json, save_text

CONVITE = ("ajuste direto", "consulta previa", "consulta prévia")
PESO_CAT = {"eletricidade": 1.0, "mobilidade_eletrica": 1.0, "fotovoltaico": 1.0, "seguranca_incendio": 0.8,
            "projeto": 0.7, "software_ti": 0.6}


def e_convite(proc: str | None) -> bool:
    p = (proc or "").lower().replace("é", "e")
    return any(k in p for k in CONVITE)


def main() -> int:
    src = DATA_DIR / "base_minho.json"
    if not src.exists():
        print("Falta data/base_minho.json (correr base_contratos.py primeiro).", file=sys.stderr)
        return 1
    regs = json.loads(src.read_text(encoding="utf-8"))["registos"]
    hoje = date.today()

    ent: dict[str, dict] = defaultdict(lambda: {
        "nif": "", "nome": "", "n": 0, "n_convite": 0, "valor": 0.0, "valor_convite": 0.0,
        "cats": Counter(), "proc": Counter(), "fornecedores": Counter(), "forn_nome": {},
        "ultimos": [], "ultima_data": "", "faixas": Counter(),
    })
    for r in regs:
        a = nif_de(r["adjudicante"])
        e = ent[a]
        e["nif"] = a if a.isdigit() else ""
        e["nome"] = e["nome"] or nome_limpo(r["adjudicante"])
        preco = r["preco"] or 0.0
        conv = e_convite(r["procedimento"])
        e["n"] += 1
        e["valor"] += preco
        if conv:
            e["n_convite"] += 1
            e["valor_convite"] += preco
        for c in r["categorias"]:
            e["cats"][c] += 1
        e["proc"][r["procedimento"] or "?"] += 1
        f = nif_de(r["adjudicatario"])
        e["fornecedores"][f] += 1
        e["forn_nome"].setdefault(f, nome_limpo(r["adjudicatario"]))
        e["faixas"]["<20k" if preco < 20000 else "20-75k" if preco < 75000 else "75-150k" if preco < 150000 else ">150k"] += 1
        d = r["data_publicacao"] or r["data_celebracao"] or ""
        e["ultima_data"] = max(e["ultima_data"], d)
        if len(e["ultimos"]) < 5:
            e["ultimos"].append({"data": d, "objeto": (r["objeto"] or "")[:120], "preco": preco,
                                 "procedimento": r["procedimento"], "fornecedor": nome_limpo(r["adjudicatario"]),
                                 "categorias": r["categorias"], "url": r["url"]})

    # Pontuação: contratos por convite ponderados pela categoria, bónus por atividade recente, penalização se um
    # único fornecedor tem quase tudo (mercado fechado).
    saida = []
    for a, e in ent.items():
        if e["n_convite"] == 0:
            continue
        peso = sum(PESO_CAT.get(c, 0.5) * k for c, k in e["cats"].items()) / max(e["n"], 1)
        recente = 1.2 if e["ultima_data"] >= (hoje.replace(year=hoje.year - 1)).isoformat() else 0.8
        top_f, top_k = e["fornecedores"].most_common(1)[0]
        concentracao = top_k / e["n"]
        aberto = 0.7 if concentracao > 0.6 else 1.0
        score = round(e["n_convite"] * peso * recente * aberto, 1)
        saida.append({
            "nif": e["nif"], "entidade": e["nome"], "prioridade": score,
            "contratos": e["n"], "por_convite": e["n_convite"],
            "valor_total": round(e["valor"]), "valor_por_convite": round(e["valor_convite"]),
            "categorias": dict(e["cats"].most_common()),
            "procedimentos": dict(e["proc"].most_common()),
            "faixas_preco": dict(e["faixas"].most_common()),
            "fornecedores_habituais": [{"nif": f, "nome": e["forn_nome"].get(f, f), "contratos": k} for f, k in e["fornecedores"].most_common(5)],
            "fornecedor_dominante_pct": round(concentracao * 100),
            "ultimo_contrato": e["ultima_data"],
            "ultimos_contratos": e["ultimos"],
            "base_url": f"https://www.base.gov.pt/Base4/pt/pesquisa/?type=contratos&adjudicante={e['nif']}" if e["nif"] else None,
        })
    saida.sort(key=lambda x: -x["prioridade"])
    save_json("prospecao_minho.json", {"gerado_em": hoje.isoformat(), "n": len(saida), "entidades": saida})

    # CSV
    with open(DATA_DIR / "prospecao_minho.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["Prioridade", "Entidade", "NIF", "Contratos (18m)", "Por convite", "Valor por convite (€)", "Categorias",
                    "Procedimentos", "Faixas de preço", "Fornecedores habituais", "Fornecedor dominante (%)", "Último contrato",
                    "Último objeto", "Estado", "Contacto", "Notas"])
        for s in saida:
            w.writerow([s["prioridade"], s["entidade"], s["nif"], s["contratos"], s["por_convite"], s["valor_por_convite"],
                        ", ".join(f"{c} ({k})" for c, k in s["categorias"].items()),
                        ", ".join(f"{p} ({k})" for p, k in s["procedimentos"].items()),
                        ", ".join(f"{p} ({k})" for p, k in s["faixas_preco"].items()),
                        "; ".join(f"{f['nome']} ({f['contratos']})" for f in s["fornecedores_habituais"][:3]),
                        s["fornecedor_dominante_pct"], s["ultimo_contrato"],
                        s["ultimos_contratos"][0]["objeto"] if s["ultimos_contratos"] else "", "", "", ""])

    # Markdown
    linhas = [f"# Prospeção comercial — quem contrata por convite no Minho (últimos 18 meses)",
              f"Gerado em {hoje.isoformat()} a partir do Portal BASE. {len(saida)} entidades com pelo menos 1 ajuste direto / consulta prévia nas categorias VoltSync.",
              "", "Prioridade = contratos por convite × peso da categoria (obra elétrica > projeto > software) × atividade recente × abertura (penaliza quem dá >60 % a um só fornecedor).", "",
              "| # | Entidade (NIF) | Prior. | Contratos | Por convite | € por convite | Categorias | Faixas | Fornecedores habituais | Dominante | Último |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, s in enumerate(saida[:60], 1):
        cats = ", ".join(f"{c} {k}" for c, k in s["categorias"].items())
        faixas = ", ".join(f"{p} {k}" for p, k in s["faixas_preco"].items())
        forn = "; ".join(f"{f['nome'][:28]} ({f['contratos']})" for f in s["fornecedores_habituais"][:3])
        linhas.append(f"| {i} | {s['entidade']} ({s['nif']}) | {s['prioridade']} | {s['contratos']} | {s['por_convite']} | {s['valor_por_convite']:,.0f} | {cats} | {faixas} | {forn} | {s['fornecedor_dominante_pct']} % | {s['ultimo_contrato']} |".replace(",", " "))
    linhas += ["", "## Como usar", "",
               "1. Começar pelas 10 primeiras: pedir reunião/visita ao serviço de compras ou ao responsável técnico (DOM/DSI) e pedir inclusão na lista de fornecedores convidados para ajuste direto e consulta prévia.",
               "2. Levar: alvará 117403-PUB (classe 2, 4.ª categoria), certidões (AT, SS), seguro RC, portefólio, e 2-3 exemplos de obras/projetos nas faixas em que a entidade compra (<20 k€ e 20-75 k€).",
               "3. Registar o estado em `Estado`/`Contacto`/`Notas` no CSV (ou na folha partilhada).",
               "4. Quando a entidade usa plataforma eletrónica (acingov, vortal, anogov, saphety), registar lá também — sem registo não há convite."]
    save_text("prospecao_minho.md", "\n".join(linhas) + "\n")
    print(f"OK: {len(saida)} entidades.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
