"""Mapa de quem contrata no Minho (contratos celebrados) a partir do dataset oficial do Portal BASE
publicado pelo IMPIC em dados.gov.pt.

Saídas em data/:
  base_minho.json         registos filtrados (Minho ∩ perfil VoltSync), últimos MESES_HISTORICO meses
  base_minho_resumo.md    quem contrata, por quanto, a quem, e por que procedimento
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import date, timedelta

import requests

from common import categorias, e_minho, norm, parse_date, parse_eur, pick, save_json, save_text
from config import MESES_HISTORICO

API = "https://dados.gov.pt/api/1/datasets/contratos-publicos-portal-base-impic-contratos-de-2012-a-2026/"
UA = {"User-Agent": "VoltSync-Radar/1.0 (+https://voltsync.pt)"}


def resource_urls() -> dict[str, str]:
    """Devolve {ano: url} para os zips mais recentes do dataset."""
    r = requests.get(API, headers=UA, timeout=60)
    r.raise_for_status()
    out: dict[str, str] = {}
    for res in r.json().get("resources", []):
        title = (res.get("title") or "").lower()
        if title.endswith(".zip") and "contratos" in title:
            ano = "".join(ch for ch in title if ch.isdigit())[-4:]
            out[ano] = res["url"]
    return out


def load_year(url: str) -> list[dict]:
    print(f"  a descarregar {url}", flush=True)
    r = requests.get(url, headers=UA, timeout=600)
    r.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    print(f"  ficheiros no zip: {names}", flush=True)
    rows: list[dict] = []
    for name in names:
        with zf.open(name) as fh:
            raw = fh.read()
        if name.lower().endswith(".json"):
            data = json.loads(raw.decode("utf-8", errors="replace"))
            if isinstance(data, dict):
                # formatos comuns: {"contratos": [...]} ou {"data": [...]}
                for v in data.values():
                    if isinstance(v, list):
                        data = v
                        break
            rows.extend(data if isinstance(data, list) else [])
        elif name.lower().endswith(".csv"):
            import csv
            text = raw.decode("utf-8-sig", errors="replace")
            rows.extend(csv.DictReader(io.StringIO(text), delimiter=";" if ";" in text[:2000] else ","))
    print(f"  registos: {len(rows)}", flush=True)
    return rows


def normaliza(r: dict) -> dict:
    adjudicante = pick(r, "adjudicante", "adjudicantes", "entidadeAdjudicante", "entidade_adjudicante")
    adjudicatario = pick(r, "adjudicatarios", "adjudicatario", "adjudicatários", "entidadeAdjudicataria")
    if isinstance(adjudicante, list):
        adjudicante = "; ".join(str(x.get("description", x) if isinstance(x, dict) else x) for x in adjudicante)
    if isinstance(adjudicatario, list):
        adjudicatario = "; ".join(str(x.get("description", x) if isinstance(x, dict) else x) for x in adjudicatario)
    return {
        "id": pick(r, "idcontrato", "id", "idContrato"),
        "objeto": pick(r, "objectoContrato", "objetoContrato", "objeto", "objecto", "descricao", "description"),
        "adjudicante": adjudicante,
        "adjudicatario": adjudicatario,
        "procedimento": pick(r, "tipoprocedimento", "tipoProcedimento", "procedimento"),
        "tipo_contrato": pick(r, "tipoContrato", "tipocontrato", "tipo"),
        "cpv": str(pick(r, "cpv", "cpvs", "CPV") or ""),
        "preco": parse_eur(pick(r, "precoContratual", "precoContrato", "preco", "valor")),
        "data_publicacao": parse_date(pick(r, "dataPublicacao", "data_publicacao", "publicationDate")),
        "data_celebracao": parse_date(pick(r, "dataCelebracaoContrato", "dataCelebracao", "signingDate")),
        "local": pick(r, "localExecucao", "localExecução", "local_execucao", "executionPlace"),
        "prazo": pick(r, "prazoExecucao", "prazo_execucao", "executionDeadline"),
        "url": (f"https://www.base.gov.pt/Base4/pt/detalhe/?type=contratos&id={pick(r, 'idcontrato', 'id', 'idContrato')}"
                if pick(r, "idcontrato", "id", "idContrato") else None),
    }


def main() -> int:
    urls = resource_urls()
    hoje = date.today()
    anos = {str(hoje.year), str(hoje.year - 1)} if hoje.month <= MESES_HISTORICO - 12 + 12 else {str(hoje.year)}
    anos = {a for a in urls if a in {str(hoje.year), str(hoje.year - 1)}}
    if not anos:
        print("Sem recursos encontrados no dataset.", file=sys.stderr)
        return 1
    limite = (hoje - timedelta(days=30 * MESES_HISTORICO)).isoformat()
    sel: list[dict] = []
    total = 0
    for ano in sorted(anos):
        for r in load_year(urls[ano]):
            total += 1
            n = normaliza(r)
            d = n["data_publicacao"] or n["data_celebracao"] or ""
            if d and d < limite:
                continue
            if not e_minho(n["adjudicante"], n["local"]):
                continue
            cats = categorias(n["cpv"], n["objeto"])
            if not cats:
                continue
            n["categorias"] = cats
            sel.append(n)
    sel.sort(key=lambda x: (x["data_publicacao"] or x["data_celebracao"] or ""), reverse=True)
    save_json("base_minho.json", {"gerado_em": hoje.isoformat(), "fonte": API, "total_lidos": total, "selecionados": len(sel), "registos": sel})

    # Resumo
    por_adj: dict[str, dict] = defaultdict(lambda: {"n": 0, "valor": 0.0, "cats": Counter(), "proc": Counter(), "fornecedores": Counter()})
    por_forn: Counter = Counter()
    valor_forn: Counter = Counter()
    for n in sel:
        a = (n["adjudicante"] or "?").strip()
        f = (n["adjudicatario"] or "?").strip()
        por_adj[a]["n"] += 1
        por_adj[a]["valor"] += n["preco"] or 0
        for c in n["categorias"]:
            por_adj[a]["cats"][c] += 1
        por_adj[a]["proc"][str(n["procedimento"] or "?")] += 1
        por_adj[a]["fornecedores"][f] += 1
        por_forn[f] += 1
        valor_forn[f] += n["preco"] or 0

    linhas = [f"# Quem contrata eletricidade/projeto/software no Minho — últimos {MESES_HISTORICO} meses",
              f"Gerado em {hoje.isoformat()} a partir do Portal BASE (dados.gov.pt). Registos lidos: {total}. Selecionados: {len(sel)}.", "",
              "## Entidades adjudicantes (por n.º de contratos)", "",
              "| Entidade | Contratos | Valor total (€) | Categorias | Procedimentos | Fornecedores mais usados |", "|---|---|---|---|---|---|"]
    for a, info in sorted(por_adj.items(), key=lambda kv: (-kv[1]["n"], -kv[1]["valor"]))[:60]:
        cats = ", ".join(f"{c} ({k})" for c, k in info["cats"].most_common())
        proc = ", ".join(f"{p} ({k})" for p, k in info["proc"].most_common(3))
        forn = "; ".join(f"{f} ({k})" for f, k in info["fornecedores"].most_common(3))
        linhas.append(f"| {a} | {info['n']} | {info['valor']:,.0f} | {cats} | {proc} | {forn} |".replace(",", " "))
    linhas += ["", "## Fornecedores que mais ganham no Minho nestas categorias (concorrência)", "",
               "| Fornecedor | Contratos | Valor total (€) |", "|---|---|---|"]
    for f, k in por_forn.most_common(40):
        linhas.append(f"| {f} | {k} | {valor_forn[f]:,.0f} |".replace(",", " "))
    linhas += ["", "## Últimos 40 contratos selecionados", "",
               "| Data | Entidade | Objeto | Procedimento | Preço (€) | Fornecedor | Link |", "|---|---|---|---|---|---|---|"]
    for n in sel[:40]:
        obj = (n["objeto"] or "")[:110].replace("|", "/")
        linhas.append(f"| {n['data_publicacao'] or n['data_celebracao'] or ''} | {n['adjudicante']} | {obj} | {n['procedimento']} | {(n['preco'] or 0):,.0f} | {n['adjudicatario']} | {n['url'] or ''} |".replace(",", " "))
    save_text("base_minho_resumo.md", "\n".join(linhas) + "\n")
    print(f"OK: {len(sel)} registos selecionados de {total}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
