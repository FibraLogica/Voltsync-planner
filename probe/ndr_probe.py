"""Verifica se a pesquisa do BASE honra o filtro «numeroanuncio» (n.º do anúncio no DR)."""
import json, re, sys, time
from playwright.sync_api import sync_playwright

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
JS = """async (form) => { const r = await fetch('/Base4/pt/resultados/', {method:'POST', credentials:'include', headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest','Accept':'text/plain, */*; q=0.01'}, body:new URLSearchParams(form).toString()}); return {status:r.status, text:(await r.text()).trim()}; }"""

CASOS = [
    ("25368/2026", "Prestação de Serviços de Fiscalização da Exploração da Central de Valorização Energética"),
    ("25343/2026", "Serviços de Manutenção da Rede Informática – ULSVDL"),
]

def pesquisa(pg, query):
    r = pg.evaluate(JS, {"type": "search_anuncios", "version": "120.0", "query": query, "sort": "-drPublicationDate", "page": "0", "size": "25"})
    if r["status"] != 200:
        return r["status"], None, r["text"][:120]
    try:
        d = json.loads(r["text"])
    except Exception as e:
        return r["status"], None, r["text"][:200]
    return r["status"], d.get("total"), [(x.get("id"), (x.get("contractDesignation") or "")[:60], x.get("drPublicationDate")) for x in d.get("items", [])[:4]]

with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(user_agent=UA, locale="pt-PT")
    pg.route("**/*", lambda route: route.abort() if route.request.resource_type in ("image", "font", "stylesheet", "media") else route.continue_())
    r = pg.goto("https://www.base.gov.pt/Base4/pt/pesquisa/", wait_until="domcontentloaded", timeout=90000); pg.wait_for_timeout(2500)
    print("goto", r.status, pg.title(), flush=True)
    html = pg.content()
    # nomes dos campos do formulário de anúncios + como o JS monta a query
    nomes = sorted(set(re.findall(r'(?:name|id)="([a-zA-Z_]*(?:numero|anuncio|texto|cpv)[a-zA-Z_]*)"', html, flags=re.I)))
    print("campos relacionados:", nomes, flush=True)
    for m in re.finditer(r'numero[a-z_]*anuncio[^\n]{0,160}', html, flags=re.I):
        print("  ctx:", m.group(0)[:200].replace("\n", " "), flush=True)
    # scripts externos que montem a query
    srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)
    print("scripts:", [s for s in srcs if "base" in s.lower() or "pesquisa" in s.lower() or "search" in s.lower()][:8], flush=True)
    for s in srcs:
        if not re.search(r'pesquisa|search|base4|main|app', s, re.I):
            continue
        try:
            txt = pg.evaluate("async (u) => { const r = await fetch(u); return await r.text(); }", s)
        except Exception as e:
            print("  falhou", s, e); continue
        for m in re.finditer(r'[^\n;]{0,120}numero[a-z_]*anuncio[^\n;]{0,160}', txt, flags=re.I):
            print("  JS", s[-40:], "::", m.group(0).strip()[:260], flush=True)
        time.sleep(0.8)
    time.sleep(1)
    for ndr, titulo in CASOS:
        for q in (f"numeroanuncio={ndr}&tipocontrato=0&tipoacto=0&tipomodelo=0",
                  f"numeroanuncio={ndr.split('/')[0]}&tipocontrato=0&tipoacto=0&tipomodelo=0"):
            st, total, itens = pesquisa(pg, q)
            print(f"\nQ {q}\n  status={st} total={total}")
            if isinstance(itens, list):
                for it in itens: print("   ", it)
            else:
                print("   ", itens)
            time.sleep(1.5)
    b.close()
