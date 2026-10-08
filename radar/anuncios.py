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
def base_anuncios_playwright(desde: date) -> list[dict]:
    """Abre o BASE num Chromium real, pesquisa anúncios desde `desde` e lê a tabela de resultados."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # pragma: no cover
        print(f"  playwright indisponível: {e}")
        return []
    rows: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=UA["User-Agent"], locale="pt-PT")
        try:
            page.goto("https://www.base.gov.pt/Base4/pt/pesquisa/", wait_until="networkidle", timeout=90000)
            # separador "Anúncios"
            for sel in ["a[href='#anuncios']", "text=Anúncios", "#tab-anuncios"]:
                try:
                    page.click(sel, timeout=5000)
                    break
                except Exception:
                    continue
            page.fill("#desdedatapublicacao", desde.strftime("%Y-%m-%d"))
            page.click("#search_anuncios")
            page.wait_for_selector("table tbody tr", timeout=60000)
            # pagina enquanto houver "seguinte"
            for _ in range(20):
                html = page.content()
                rows += _parse_base_table(html)
                nxt = page.query_selector("a[id^=page_]:has-text('›'), a:has-text('Seguinte')")
                if not nxt:
                    break
                nxt.click()
                page.wait_for_timeout(1500)
        except Exception as e:
            print(f"  BASE via browser falhou: {e}")
        finally:
            browser.close()
    # remover duplicados por id
    seen, out = set(), []
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        out.append(r)
    return out


def _parse_base_table(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for tr in soup.select("table tbody tr"):
        tds = [td.get_text(" ", strip=True) for td in tr.select("td")]
        a = tr.select_one("a[href*='detalhe']")
        if not a or len(tds) < 4:
            continue
        m = re.search(r"id=(\d+)", a.get("href", ""))
        out.append({
            "origem": "BASE",
            "id": m.group(1) if m else a.get("href"),
            "url": "https://www.base.gov.pt" + a.get("href") if a.get("href", "").startswith("/") else a.get("href"),
            "colunas": tds,
        })
    return out


def base_detalhe(url: str) -> dict:
    """Lê a página de detalhe de um anúncio no BASE (texto corrido) e extrai os campos principais."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(user_agent=UA["User-Agent"], locale="pt-PT")
            page.goto(url, wait_until="networkidle", timeout=60000)
            txt = page.inner_text("body")
            browser.close()
    except Exception as e:
        return {"erro": str(e)}
    def grab(label):
        m = re.search(re.escape(label) + r"\s*[:\n]\s*(.+)", txt)
        return m.group(1).strip() if m else None
    return {
        "entidade": grab("Entidade adjudicante") or grab("Entidade emissora"),
        "objeto": grab("Descrição") or grab("Objeto"),
        "preco_base": parse_eur(grab("Preço base")),
        "prazo_propostas": grab("Prazo para apresentação de propostas") or grab("Data limite"),
        "procedimento": grab("Tipo de procedimento") or grab("Tipo de acto"),
        "cpv": grab("CPV"),
        "n_dr": grab("Número do anúncio"),
        "plataforma": grab("Plataforma"),
    }


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
    m_price = re.search(r"Base price:\s*€?\s*([\d.,\s]+)\s*€?", txt)
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
    for r in base_rows[:150]:
        texto = " ".join(r["colunas"])
        cats = categorias(texto, texto)
        if not cats and not e_minho(texto):
            continue
        det = base_detalhe(r["url"]) if r.get("url") else {}
        a = {"origem": "BASE", "url": r["url"], "titulo": det.get("objeto") or texto[:200], **det}
        a["categorias"] = categorias(a.get("cpv"), a.get("titulo"), a.get("objeto"))
        a["minho"] = e_minho(a.get("entidade"), a.get("titulo"), texto)
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
              f"Fontes: BASE via browser ({len(base_rows)} linhas lidas), BidsFactory. Candidatos: {len(anuncios)}.", "",
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
