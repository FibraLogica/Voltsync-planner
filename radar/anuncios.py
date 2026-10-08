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

from common import categorias, e_minho, norm, parse_eur, save_json, save_text
from config import TETO_EMPREITADA_EUR

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"}


# ---------------------------------------------------------------- BASE (Playwright)
BASE_URL = "https://www.base.gov.pt"


def _abrir_pesquisa_anuncios(page, desde: date, debug: list[str]) -> None:
    page.goto(f"{BASE_URL}/Base4/pt/pesquisa/", wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(6000)
    debug.append(f"title={page.title()!r}")
    # O formulário de anúncios só aparece depois de escolher "Anúncios DR" no seletor de tipo de pesquisa.
    page.select_option("#sel_search", "anuncios")
    page.wait_for_selector("#desdedatapublicacao", state="visible", timeout=20000)
    page.evaluate("(v) => { const el = document.querySelector('#desdedatapublicacao'); el.value = v; el.dispatchEvent(new Event('change', {bubbles: true})); }",
                  desde.strftime("%d-%m-%Y"))
    page.click("#search_anuncios")
    page.wait_for_selector("table tbody tr", timeout=60000)
    page.wait_for_timeout(2000)


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
            _abrir_pesquisa_anuncios(page, desde, debug)
            for pagina in range(1, 40):
                novas = _linhas_tabela(page)
                debug.append(f"pagina {pagina}: {len(novas)} linhas; primeira pub={novas[0]['publicado'] if novas else None}; ultima pub={novas[-1]['publicado'] if novas else None}")
                if pagina == 1:
                    debug.append("exemplo=" + repr(novas[:2]))
                    pag_html = page.evaluate("() => { const t = document.querySelector('table'); const c = t ? t.closest('div') : null; return c ? c.outerHTML.slice(-3000) : ''; }")
                    debug.append("fim_tabela_html=" + pag_html.replace("\n", " "))
                rows += novas
                if not novas:
                    break
                ult = _data_pt(novas[-1]["publicado"])
                if ult and ult < desde:
                    break
                # próxima página
                nxt = None
                for sel in ["a[rel='next']", "li.next a", "a.next", "a:has-text('›')", "a:has-text('»')", "a:has-text('Seguinte')", "a:has-text('Próxima')", f"a:has-text('{pagina + 1}')"]:
                    try:
                        cand = page.query_selector(sel)
                        if cand and cand.is_visible():
                            nxt = cand
                            debug.append(f"next via {sel}")
                            break
                    except Exception:
                        continue
                if not nxt:
                    debug.append("sem link para a página seguinte")
                    break
                primeira = novas[0]["titulo"]
                nxt.click()
                try:
                    page.wait_for_function("t => { const td = document.querySelector('table tbody tr td'); return td && td.innerText.trim() !== t; }", arg=primeira, timeout=30000)
                except Exception:
                    debug.append("tabela não mudou após clique")
                    break
                page.wait_for_timeout(800)
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
def classifica(a: dict) -> str:
    cats = a.get("categorias") or []
    if not cats:
        return "C"
    if TETO_EMPREITADA_EUR and "eletricidade" in cats and (a.get("preco_base") or 0) > TETO_EMPREITADA_EUR:
        return "C"
    return "A" if a.get("minho") else "B"


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
        a = {**r, **{k: v for k, v in det.items() if k != "texto" and v}}
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

    for a in anuncios:
        a["classe"] = classifica(a)
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
            pr=a.get("prazo_propostas") or "?", proc=a.get("procedimento") or "?", cpv=a.get("cpv") or "?",
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
