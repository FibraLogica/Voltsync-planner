"""Anúncios de procedimento abertos (concursos públicos) que encaixam no perfil VoltSync.

Fonte principal: Portal BASE, lido com um browser real (Playwright), porque o portal bloqueia pedidos
automáticos simples. Fonte de recurso: agregador BidsFactory (HTML simples).

Saídas em data/:
  anuncios.json        lista normalizada (origem, entidade, objeto, preço base, prazo, cpv, links)
  anuncios_resumo.md   tabela pronta a ler, A/B/C
"""
from __future__ import annotations

import re
import sys
import time
from datetime import date, datetime, timedelta

import requests
from bs4 import BeautifulSoup

from common import categorias, e_minho, norm, parse_date, parse_eur, save_json, save_text
from config import DISTRITOS_NORTE, TETO_B_SERVICOS_EUR, TETO_EMPREITADA_EUR

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"}


# ---------------------------------------------------------------- BASE (Playwright)
BASE_URL = "https://www.base.gov.pt"


def _abrir_pesquisa_anuncios(page, desde: date, debug: list[str]) -> list:
    page.goto(f"{BASE_URL}/Base4/pt/pesquisa/", wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(6000)
    debug.append(f"title={page.title()!r}")
    # O formulário de anúncios só aparece depois de escolher "Anúncios DR" no seletor de tipo de pesquisa.
    page.select_option("#sel_search", "anuncios")
    page.wait_for_selector("#desdedatapublicacao", state="visible", timeout=20000)
    page.evaluate("(v) => { const el = document.querySelector('#desdedatapublicacao'); el.value = v; el.dispatchEvent(new Event('change', {bubbles: true})); }",
                  desde.strftime("%d-%m-%Y"))
    captured: list = []

    def _on_request(req):
        if "resultados" in req.url and req.method == "POST":
            captured.append({"url": req.url, "post_data": req.post_data, "headers": dict(req.headers)})
    page.on("request", _on_request)
    page.click("#search_anuncios")
    page.wait_for_selector("table tbody tr", timeout=60000)
    page.wait_for_timeout(2000)
    page.remove_listener("request", _on_request)
    debug.append(f"pedidos ajax capturados={len(captured)}; " + "; ".join(f"{c['url']} :: {(c['post_data'] or '')[:300]}" for c in captured[:3]))
    return captured


def _linhas_tabela(page) -> list[dict]:
    """Lê a tabela de resultados visível: Objeto | Tipo de ato | Tipo de procedimento | Entidade | Preço base | Publicação."""
    rows = page.eval_on_selector_all(
        "table tbody tr",
        """trs => trs.map(tr => {
            const tds = Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim());
            const a = tr.querySelector('a[href]');
            return {tds, href: a ? a.getAttribute('href') : null, onclick: tr.getAttribute('onclick') || (a ? a.getAttribute('onclick') : null)};
        })""")
    out = []
    for r in rows:
        tds = r["tds"]
        if len(tds) < 6:
            continue
        href = r.get("href") or ""
        m = re.search(r"id=(\d+)", href) or re.search(r"(\d{5,})", r.get("onclick") or "")
        aid = m.group(1) if m else None
        url = (BASE_URL + href if href.startswith("/") else href) if "detalhe" in href else (
            f"{BASE_URL}/Base4/pt/detalhe/?type=anuncios&id={aid}" if aid else None)
        out.append({
            "origem": "BASE", "id": aid or (href or tds[0][:80]), "url": url,
            "titulo": tds[0], "tipo_ato": tds[1], "procedimento": tds[2], "entidade": tds[3],
            "preco_base": parse_eur(tds[4]) if tds[4] not in ("-", "") else None,
            "publicado": tds[5],
        })
    return out


def _linhas_json(body: str) -> list[dict]:
    """Interpreta a resposta ajax do BASE (JSON com lista de anúncios, ou HTML de tabela)."""
    import json as _json
    body = body.strip()
    if not body or body == "null":
        return []
    items = None
    try:
        data = _json.loads(body)
        if isinstance(data, dict):
            for k in ("items", "data", "results", "anuncios", "rows"):
                if isinstance(data.get(k), list):
                    items = data[k]
                    break
            if items is None:
                items = next((v for v in data.values() if isinstance(v, list)), [])
        elif isinstance(data, list):
            items = data
    except ValueError:
        soup = BeautifulSoup(body, "html.parser")
        out = []
        for tr in soup.select("tr"):
            tds = [td.get_text(" ", strip=True) for td in tr.select("td")]
            a = tr.select_one("a[href*='detalhe']")
            if len(tds) < 6 or not a:
                continue
            m = re.search(r"id=(\d+)", a.get("href", ""))
            out.append({"origem": "BASE", "id": m.group(1) if m else tds[0][:80], "url": BASE_URL + a["href"].replace("&amp;", "&") if a["href"].startswith("/") else a["href"],
                        "titulo": tds[0], "tipo_ato": tds[1], "procedimento": tds[2], "entidade": tds[3],
                        "preco_base": parse_eur(tds[4]) if tds[4] not in ("-", "") else None, "publicado": tds[5]})
        return out
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        g = lambda *ks: next((it[k] for k in ks if k in it and it[k] not in (None, "")), None)
        aid = g("id", "idanuncio", "idAnuncio")
        ent = g("contractingEntity", "entidade", "emissora", "entidadeEmissora", "nomeEntidade", "adjudicante")
        if isinstance(ent, dict):
            ent = ent.get("description") or ent.get("nome") or str(ent)
        if isinstance(ent, list):
            ent = "; ".join(str(e.get("description", e) if isinstance(e, dict) else e) for e in ent)
        out.append({
            "origem": "BASE", "id": str(aid) if aid else (g("objecto", "objeto", "description") or "")[:80],
            "url": f"{BASE_URL}/Base4/pt/detalhe/?type=anuncios&id={aid}" if aid else None,
            "titulo": g("contractDesignation", "objecto", "objeto", "description", "descricao"),
            "tipo_ato": g("type", "tipoActo", "tipoacto", "tipo_ato", "tipoAto"),
            "procedimento": g("contractingProcedureType", "tipoProcedimento", "tipoprocedimento", "modeloAnuncio", "tipomodelo"),
            "entidade": ent, "preco_base": parse_eur(g("basePrice", "precoBase", "precobase", "preco_base")),
            "publicado": _fmt_pt(g("drPublicationDate", "dataPublicacao", "datapublicacao", "publicationDate", "data_publicacao")),
            "n_dr": g("drNumber", "numeroAnuncio", "numeroanuncio", "nAnuncio"), "cpv": str(g("cpv", "cpvs") or "") or None,
            "prazo_propostas": _fmt_pt(g("proposalDeadline", "prazoPropostas", "dataLimite", "prazo")),
        })
    return out


def _fmt_pt(v) -> str | None:
    if not v:
        return None
    s = str(v)[:10]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%d-%m-%Y")
        except ValueError:
            continue
    return str(v)


def _data_pt(s: str | None) -> date | None:
    try:
        return datetime.strptime((s or "").strip()[:10], "%d-%m-%Y").date()
    except ValueError:
        return None


def base_anuncios_playwright(desde: date) -> list[dict]:
    """Abre o BASE num Chromium real, pesquisa anúncios publicados desde `desde` e lê as páginas de resultados."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # pragma: no cover
        print(f"  playwright indisponível: {e}")
        return []
    rows: list[dict] = []
    debug: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=UA["User-Agent"], locale="pt-PT")
        try:
            captured = _abrir_pesquisa_anuncios(page, desde, debug)
            novas = _linhas_tabela(page)
            debug.append(f"pagina 1 (DOM): {len(novas)} linhas; primeira pub={novas[0]['publicado'] if novas else None}; ultima pub={novas[-1]['publicado'] if novas else None}")
            debug.append("exemplo=" + repr(novas[:2]))
            rows += novas
            # Páginas seguintes: repetir o pedido ajax que o próprio portal fez (mesma sessão/cookies do browser).
            if captured:
                from urllib.parse import parse_qsl
                c = captured[-1]
                form = dict(parse_qsl(c["post_data"] or "", keep_blank_values=True))
                debug.append(f"form_base={form}")
                hdr = {k: v for k, v in c["headers"].items() if k.lower() in ("accept", "content-type", "x-requested-with", "referer", "origin")}
                for pagina in range(0, 30):
                    form_p = dict(form)
                    form_p["page"] = str(pagina)
                    form_p["size"] = "100"
                    try:
                        resp = page.request.post(c["url"], form=form_p, headers=hdr, timeout=60000)
                        body = resp.text()
                    except Exception as e:
                        debug.append(f"ajax pagina {pagina} falhou: {e}")
                        break
                    if pagina == 0:
                        debug.append(f"ajax status={resp.status} inicio={body[:600]!r}")
                    novas = _linhas_json(body)
                    debug.append(f"pagina {pagina + 1} (ajax): {len(novas)} linhas; ultima pub={novas[-1]['publicado'] if novas else None}")
                    if not novas:
                        break
                    rows += novas
                    ult = _data_pt(novas[-1]["publicado"])
                    if ult and ult < desde:
                        break
                    time.sleep(0.7)
        except Exception as e:
            print(f"  BASE via browser falhou: {e}")
            debug.append(f"erro={e}")
        finally:
            browser.close()
            save_text("base_debug.txt", "\n".join(debug) + "\n")
    seen, out = set(), []
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        out.append(r)
    return out


def base_detalhes(urls: list[str]) -> dict[str, dict]:
    """Lê as páginas de detalhe de vários anúncios no BASE com um único browser."""
    res: dict[str, dict] = {}
    if not urls:
        return res
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return res
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=UA["User-Agent"], locale="pt-PT")
        for url in urls:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)
                txt = page.inner_text("body")
            except Exception as e:
                res[url] = {"erro": str(e)}
                continue

            def grab(*labels):
                for label in labels:
                    m = re.search(re.escape(label) + r"\s*[:\n\t]+\s*([^\n\t]+)", txt, re.I)
                    if m:
                        return m.group(1).strip()
                return None
            res[url] = {
                "objeto": grab("Descrição", "Objeto do contrato", "Objeto"),
                "prazo_propostas": grab("Prazo para apresentação de propostas", "Prazo para apresentação das propostas", "Data limite de apresentação", "Data limite"),
                "cpv": grab("CPV", "CPVs"),
                "n_dr": grab("Número do anúncio", "N.º do anúncio", "Nº do anúncio"),
                "plataforma": grab("Plataforma eletrónica", "Plataforma"),
                "local": grab("Local de execução", "Local"),
                "texto": txt[:4000],
            }
        browser.close()
    return res


# ---------------------------------------------------------------- BidsFactory (recurso)
BF = "https://bidsfactory.com"
BF_LISTAS = [
    "/en/tenders/sector/construction/country/pt",
    "/en/tenders/sector/energy/country/pt",
    "/en/tenders/sector/ict/country/pt",
    "/en/tenders/source/base_gov_pt",
]


def bidsfactory_listas() -> list[dict]:
    out, seen = [], set()
    for path in BF_LISTAS:
        for page_n in (1, 2, 3):
            url = f"{BF}{path}" + (f"?page={page_n}" if page_n > 1 else "")
            try:
                r = requests.get(url, headers=UA, timeout=60)
                r.raise_for_status()
            except Exception as e:
                print(f"  bidsfactory {url}: {e}")
                break
            soup = BeautifulSoup(r.text, "html.parser")
            novos = 0
            for a in soup.select("a[href^='/en/tenders/']"):
                href = a.get("href", "")
                if href.count("/") != 3 or "/tenders/sector/" in href or "/tenders/source/" in href or "/tenders/country/" in href or "/tenders/browse" in href or "/tenders/categories" in href:
                    continue
                if href in seen:
                    continue
                titulo = a.get_text(" ", strip=True)
                if len(titulo) < 12:
                    continue
                seen.add(href)
                novos += 1
                out.append({"origem": "BidsFactory", "url": BF + href, "titulo_en": titulo})
            if novos == 0:
                break
            time.sleep(1)
    return out


def bidsfactory_detalhe(url: str) -> dict:
    try:
        r = requests.get(url, headers=UA, timeout=60)
        r.raise_for_status()
    except Exception as e:
        return {"erro": str(e)}
    soup = BeautifulSoup(r.text, "html.parser")
    txt = soup.get_text("\n", strip=True)

    def grab(*labels):
        for label in labels:
            m = re.search(re.escape(label) + r"\s*[:\n]+\s*([^\n]+)", txt, re.I)
            if m:
                return m.group(1).strip()
        return None

    titulo_pt = grab("Original title", "Título original", "Original Title")
    # O BidsFactory concentra os dados numa linha: "Concurso público. CPV: 45310000-3, ... Base price: 18.000,00 €. DR announcement nr: 24802/2026. Model type: ..."
    m_cpv = re.search(r"CPV:\s*(\d{8}-\d)", txt)
    m_price = re.search(r"Base price:\s*€?\s*([\d.,\s]*\d)", txt)
    m_dr = re.search(r"DR announcement nr:\s*(\d{3,6}/20\d{2})", txt)
    m_proc = re.search(r"Model type:\s*([^\n.]+)", txt)
    m_pub = re.search(r"Published:?\s*([A-Za-z]+ \d{1,2}, \d{4})", txt)
    m_dead = re.search(r"Deadline:?\s*([A-Za-z]+ \d{1,2}, \d{4})", txt)
    return {
        "titulo_pt": titulo_pt,
        "entidade": grab("Contracting Authority", "Buyer", "Entidade adjudicante", "Authority"),
        "preco_base": parse_eur(m_price.group(1).strip()) if m_price else None,
        "publicado": m_pub.group(1) if m_pub else grab("Published", "Publication date"),
        "prazo_propostas": m_dead.group(1) if m_dead else None,
        "procedimento": m_proc.group(1).strip() if m_proc else grab("Procedure", "Procedure type"),
        "cpv": m_cpv.group(1) if m_cpv else grab("CPV"),
        "n_dr": m_dr.group(1) if m_dr else None,
    }


# ---------------------------------------------------------------- Classificação e saída
def _norte(a: dict) -> bool:
    t = norm(" | ".join(str(a.get(k) or "") for k in ("entidade", "titulo", "local")))
    return any(re.search(r"\b" + re.escape(norm(d)) + r"\b", t) for d in DISTRITOS_NORTE)


def classifica(a: dict) -> str:
    """A = Minho e no perfil. B = fora do Minho mas alcançável (Norte para obra; serviços até ao teto). C = resto."""
    cats = a.get("categorias") or []
    if not cats:
        return "C"
    preco = a.get("preco_base") or 0
    obra = bool({"eletricidade", "mobilidade_eletrica", "fotovoltaico", "seguranca_incendio"} & set(cats)) and \
        not ({"software_ti", "projeto"} & set(cats))
    if TETO_EMPREITADA_EUR and obra and preco > TETO_EMPREITADA_EUR:
        return "C"  # acima da classe 2 do alvará: só consórcio/subempreitada
    if a.get("minho"):
        return "A"
    so_servicos = not ({"eletricidade", "mobilidade_eletrica", "fotovoltaico", "seguranca_incendio"} & set(cats))
    if so_servicos:
        return "B" if (not TETO_B_SERVICOS_EUR or preco <= TETO_B_SERVICOS_EUR) else "C"
    return "B" if _norte(a) else "C"


def main() -> int:
    hoje = date.today()
    desde = hoje - timedelta(days=3)
    anuncios: list[dict] = []

    print("1) Portal BASE via browser…", flush=True)
    base_rows = base_anuncios_playwright(desde)
    print(f"   {len(base_rows)} linhas", flush=True)
    relevantes = []
    for r in base_rows:
        ta = norm(r.get("tipo_ato"))
        if any(k in ta for k in ("retificacao", "prorrogacao", "adjudicacao", "anulacao", "revogacao")):
            continue  # só anúncios que abrem procedimento
        cats = categorias(None, r["titulo"])
        minho = e_minho(r["entidade"], r["titulo"])
        if not cats and not minho:
            continue
        r["categorias"] = cats
        r["minho"] = minho
        relevantes.append(r)
    print(f"   {len(relevantes)} relevantes (perfil ou Minho)", flush=True)
    dets = base_detalhes([r["url"] for r in relevantes if r.get("url")][:60])
    for r in relevantes:
        det = dets.get(r.get("url") or "", {})
        a = {**r, **{k: v for k, v in det.items() if k != "texto" and v and not (k == "prazo_propostas" and r.get("prazo_propostas"))}}
        a["categorias"] = categorias(a.get("cpv"), a.get("titulo"), a.get("objeto"))
        a["minho"] = e_minho(a.get("entidade"), a.get("titulo"), a.get("local"))
        if not a["categorias"] and not a["minho"]:
            continue
        anuncios.append(a)

    print("2) BidsFactory (recurso)…", flush=True)
    for r in bidsfactory_listas():
        t = r["titulo_en"]
        # Sem pré-filtro pelo título inglês: as palavras-chave são em português, lê-se sempre o detalhe.
        det = bidsfactory_detalhe(r["url"])
        a = {"origem": "BidsFactory", "url": r["url"], "titulo": det.get("titulo_pt") or t, "titulo_en": t, **det}
        a["categorias"] = categorias(a.get("cpv"), a.get("titulo"))
        a["minho"] = e_minho(a.get("entidade"), a.get("titulo"))
        if not a["categorias"] and not a["minho"]:
            continue  # nem perfil nem Minho: não interessa
        anuncios.append(a)
        time.sleep(0.4)

    # Duplicados entre fontes (mesma entidade + objeto): fica o do BASE, herdando o n.º DR do BidsFactory.
    chave = lambda a: (norm(a.get("entidade"))[:40], norm(a.get("titulo"))[:70])
    base_por_chave = {chave(a): a for a in anuncios if a["origem"] == "BASE"}
    unicos = []
    for a in anuncios:
        if a["origem"] != "BASE" and chave(a) in base_por_chave:
            b = base_por_chave[chave(a)]
            for k in ("n_dr", "cpv", "preco_base"):
                if not b.get(k) and a.get(k):
                    b[k] = a[k]
            b["url_bidsfactory"] = a["url"]
            continue
        unicos.append(a)
    anuncios = unicos

    for a in anuncios:
        a["classe"] = classifica(a)
        for k in ("prazo_propostas", "publicado"):
            iso = parse_date(a.get(k))
            if iso:
                a[k] = iso
    ordem = {"A": 0, "B": 1, "C": 2}
    anuncios.sort(key=lambda x: (ordem[x["classe"]], x.get("prazo_propostas") or "9999"))
    save_json("anuncios.json", {"gerado_em": datetime.now().isoformat(timespec="minutes"), "n": len(anuncios), "anuncios": anuncios})

    linhas = [f"# Radar VoltSync — anúncios abertos ({hoje.isoformat()})", "",
              f"Fontes: BASE via browser ({len(base_rows)} anúncios lidos desde {desde.isoformat()}), BidsFactory. Candidatos: {len(anuncios)}.", "",
              "| Classe | Entidade | Objeto | Preço base (€) | Prazo propostas | Procedimento | CPV | N.º DR | Link |",
              "|---|---|---|---|---|---|---|---|---|"]
    for a in anuncios:
        if a["classe"] == "C":
            continue
        linhas.append("| {c} | {e} | {o} | {p} | {pr} | {proc} | {cpv} | {dr} | {u} |".format(
            c=a["classe"], e=a.get("entidade") or "?", o=(a.get("titulo") or "")[:120].replace("|", "/"),
            p=f"{a['preco_base']:,.0f}".replace(",", " ") if a.get("preco_base") else "?",
            pr=a.get("prazo_propostas") or "?", proc=a.get("procedimento") or "?", cpv=(a.get("cpv") or "?")[:10],
            dr=a.get("n_dr") or "", u=a["url"]))
    cs = [a for a in anuncios if a["classe"] == "C"]
    if cs:
        linhas += ["", "## Fora de perfil / só subempreitada (C)", ""] + [f"- {a.get('entidade') or '?'} — {(a.get('titulo') or '')[:100]} — {a['url']}" for a in cs[:30]]
    if not any(a["classe"] in ("A", "B") for a in anuncios):
        linhas += ["", "**Sem resultados A/B hoje.**"]
    save_text("anuncios_resumo.md", "\n".join(linhas) + "\n")
    print(f"OK: {len(anuncios)} candidatos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
