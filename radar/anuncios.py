"""Anúncios de procedimento abertos (concursos públicos) que encaixam no perfil VoltSync.

Fonte principal: Portal BASE, lido com um browser real (Playwright), porque o portal bloqueia pedidos
automáticos simples. Fonte de recurso: agregador BidsFactory (HTML simples), usado só quando o BASE falha.

Como funciona (desde 2026-10-26):
  1. Abre a pesquisa de anúncios no BASE num Chromium e lê TODAS as páginas de resultados publicados
     desde a última execução (mínimo JANELA_DIAS dias; JANELA_ARRANQUE dias na primeira execução ou
     depois de uma falha). Os pedidos ajax são feitos PELO PRÓPRIO BROWSER (`page.evaluate(fetch)`):
     o canal HTTP do Playwright/Node falha desde 2026-10-20 porque o BASE deixou de enviar o certificado
     intermédio; o Chromium resolve isso sozinho (AIA).
  2. Lê o detalhe de cada anúncio (`type=detail_anuncios`, ~0,3 s): CPV, NIF, preço base, prazo, tipo de
     contrato, plataforma, n.º no DR, PDF do DR, id do procedimento. A classificação usa o CPV e o objeto,
     não só o título da lista.
  3. Um registo por PROCEDIMENTO: uma retificação/prorrogação atualiza o anúncio original (e fica
     registada em `alteracoes`) em vez de aparecer como concurso novo; adjudicação/anulação/revogação
     encerram-no.
  4. A lista é CUMULATIVA: carrega o anuncios.json anterior, funde os anúncios novos e só retira os que
     já passaram o prazo de propostas (ou, sem prazo conhecido, com mais de DIAS_SEM_PRAZO dias).
     Antes, cada execução substituía o ficheiro por «o que saiu nos últimos 3 dias».

Saídas em data/:
  anuncios.json        lista normalizada (origem, entidade, objeto, preço base, prazo, cpv, links, estatísticas)
  anuncios_resumo.md   tabela pronta a ler, A/B/C
  base_debug.txt       diagnóstico da leitura do BASE
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from urllib.parse import parse_qsl

import requests
from bs4 import BeautifulSoup

from common import DATA_DIR, categorias, e_minho, excluido, norm, parse_date, parse_eur, save_json, save_text
from config import DISTRITOS_NORTE, TETO_B_SERVICOS_EUR, TETO_EMPREITADA_EUR

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"}

# Janela mínima lida em cada execução (cobre fim de semana + um dia de avaria). A lista é cumulativa.
JANELA_DIAS = 7
# Janela na primeira execução ou quando a execução anterior não conseguiu ler o BASE.
JANELA_ARRANQUE = 30
# Nunca se lê mais do que isto para trás.
JANELA_MAX = 45
# Sem prazo conhecido, um anúncio mantém-se tantos dias depois da publicação.
DIAS_SEM_PRAZO = 45
# Limites de proteção (25 anúncios por página; ~60 anúncios por dia útil).
MAX_PAGINAS = 120
MAX_DETALHES = 2500
# Ritmo. O BASE tem uma firewall (WebKnight) que bloqueia o IP ao fim de ~200 pedidos em poucos minutos
# (viu-se com ~200 em 4-5 min, a 2,5/s e a 1/s; 123 pedidos em 9 min passaram). Por isso trabalha-se por
# lotes: MAX_PEDIDOS_POR_LOTE pedidos, pausa longa, outro lote — até TEMPO_MAX_S. O que ficar por ler passa
# para a execução seguinte (a lista é cumulativa).
PAUSA_PAGINA_S = 1.0
PAUSA_DETALHE_S = 1.2
MAX_PEDIDOS_POR_LOTE = int(os.environ.get("RADAR_MAX_PEDIDOS_LOTE") or 100)
PAUSA_ENTRE_LOTES_S = int(os.environ.get("RADAR_PAUSA_LOTE_S") or 1200)
TEMPO_MAX_S = int(os.environ.get("RADAR_TEMPO_MAX_S") or 150 * 60)
# Ao primeiro bloqueio espera-se isto e tenta-se outra vez; ao segundo, pára-se.
ESPERA_BLOQUEIO_S = int(os.environ.get("RADAR_ESPERA_BLOQUEIO_S") or 1500)


# ---------------------------------------------------------------- BASE (Playwright)
BASE_URL = "https://www.base.gov.pt"

_POST_NO_BROWSER = """async (form) => {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 60000);
  try {
    const r = await fetch('/Base4/pt/resultados/', {
      method: 'POST', credentials: 'include', signal: ctl.signal,
      headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'X-Requested-With': 'XMLHttpRequest', 'Accept': 'text/plain, */*; q=0.01'},
      body: new URLSearchParams(form).toString()});
    return {status: r.status, text: (await r.text()).trim()};
  } finally { clearTimeout(t); }
}"""


def _post_base(page, form: dict) -> dict:
    """POST ao endpoint de resultados feito PELO browser (mesma sessão, cookies e cadeia de certificados)."""
    return page.evaluate(_POST_NO_BROWSER, form)


def _form_pesquisa(desde: date) -> dict:
    """O pedido que o próprio portal faz quando se pesquisa «Anúncios DR» (confirmado em base_debug.txt)."""
    return {
        "type": "search_anuncios", "version": "120.0",
        "query": f"tipocontrato=0&desdedatapublicacao={desde.strftime('%d-%m-%Y')}&tipoacto=0&tipomodelo=0",
        "sort": "-drPublicationDate", "page": "0", "size": "25",
    }


def _abrir_pesquisa_anuncios(page, desde: date, debug: list[str]) -> dict | None:
    """Abre a pesquisa no portal e devolve o formulário ajax que o portal usou (ou None se não o apanhou).
    Lança RuntimeError se a firewall bloquear logo a página."""
    resp = page.goto(f"{BASE_URL}/Base4/pt/pesquisa/", wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(5000)
    debug.append(f"goto status={resp.status if resp else '?'} title={page.title()!r}")
    if (resp and resp.status == 999) or "WebKnight" in page.title():
        raise RuntimeError("firewall do BASE (WebKnight) bloqueou este IP")
    captured: list = []
    try:
        # O formulário de anúncios só aparece depois de escolher "Anúncios DR" no seletor de tipo de pesquisa.
        page.select_option("#sel_search", "anuncios")
        page.wait_for_selector("#desdedatapublicacao", state="visible", timeout=20000)
        page.evaluate("(v) => { const el = document.querySelector('#desdedatapublicacao'); el.value = v; el.dispatchEvent(new Event('change', {bubbles: true})); }",
                      desde.strftime("%d-%m-%Y"))

        def _on_request(req):
            if "resultados" in req.url and req.method == "POST":
                captured.append({"url": req.url, "post_data": req.post_data})
        page.on("request", _on_request)
        page.click("#search_anuncios")
        page.wait_for_selector("table tbody tr", timeout=60000)
        page.wait_for_timeout(1500)
        page.remove_listener("request", _on_request)
    except Exception as e:
        debug.append(f"pesquisa no portal falhou (uso o formulário conhecido): {str(e)[:200]}")
    debug.append(f"pedidos ajax capturados={len(captured)}; " + "; ".join(f"{c['url']} :: {(c['post_data'] or '')[:300]}" for c in captured[:2]))
    if not captured:
        return None
    form = dict(parse_qsl(captured[-1]["post_data"] or "", keep_blank_values=True))
    return form if form.get("type") == "search_anuncios" and form.get("query") else None


def _texto(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, dict):
        return v.get("description") or v.get("nome") or None
    if isinstance(v, list):
        return "; ".join(x for x in (_texto(i) for i in v) if x) or None
    s = str(v).strip()
    return s or None


def _linha_json(it: dict) -> dict | None:
    """Uma linha da lista ajax do BASE → registo mínimo."""
    if not isinstance(it, dict):
        return None
    g = lambda *ks: next((it[k] for k in ks if k in it and it[k] not in (None, "")), None)
    aid = g("id", "idanuncio", "idAnuncio")
    if not aid:
        return None
    return {
        "origem": "BASE", "id": str(aid), "url": f"{BASE_URL}/Base4/pt/detalhe/?type=anuncios&id={aid}",
        "titulo": _texto(g("contractDesignation", "objecto", "objeto", "description", "descricao")),
        "tipo_ato": _texto(g("type", "tipoActo", "tipoacto", "tipo_ato", "tipoAto")),
        "procedimento": _texto(g("contractingProcedureType", "tipoProcedimento", "tipoprocedimento", "modeloAnuncio", "tipomodelo")),
        "entidade": _texto(g("contractingEntity", "entidade", "emissora", "entidadeEmissora", "nomeEntidade", "adjudicante")),
        "preco_base": parse_eur(g("basePrice", "precoBase", "precobase", "preco_base")),
        "publicado": _fmt_pt(g("drPublicationDate", "dataPublicacao", "datapublicacao", "publicationDate", "data_publicacao")),
        "prazo_propostas": _texto(g("proposalDeadline", "prazoPropostas", "dataLimite", "prazo")),
    }


def _linhas_json(body: str) -> tuple[list[dict], int | None]:
    """Interpreta a resposta ajax do BASE (JSON com lista de anúncios). Devolve (linhas, total anunciado)."""
    body = (body or "").strip()
    if not body or body == "null":
        return [], None
    try:
        data = json.loads(body)
    except ValueError:
        return [], None
    items, total = None, None
    if isinstance(data, dict):
        total = data.get("total") if isinstance(data.get("total"), int) else None
        for k in ("items", "data", "results", "anuncios", "rows"):
            if isinstance(data.get(k), list):
                items = data[k]
                break
        if items is None:
            items = next((v for v in data.values() if isinstance(v, list)), [])
    elif isinstance(data, list):
        items = data
    out = []
    for it in items or []:
        r = _linha_json(it)
        if r:
            out.append(r)
    return out, total


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


def _data_iso(s: str | None) -> date | None:
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def _bloqueado(r: dict | None) -> bool:
    """Resposta da firewall do BASE (WebKnight): status 999 e uma página HTML em vez de JSON."""
    if not r:
        return False
    texto = (r.get("text") or "")[:600]
    return r.get("status") == 999 or "WebKnight" in texto or "Firewall Alert" in texto


def base_detalhe(page, aid: str) -> dict:
    """Detalhe de um anúncio (`type=detail_anuncios`). Em erro devolve {"erro": …} e, se for a firewall, {"bloqueado": True}."""
    try:
        r = _post_base(page, {"type": "detail_anuncios", "version": "155.0", "id": str(aid)})
    except Exception as e:
        return {"erro": str(e)[:200]}
    if _bloqueado(r):
        return {"erro": "firewall do BASE (WebKnight) bloqueou o pedido", "bloqueado": True}
    return _detalhe_de_resposta(r)


def _detalhe_de_resposta(r: dict) -> dict:
    """Resposta de `detail_anuncios` → CPV, NIF, prazo, tipo de contrato, plataforma, DR, id do procedimento."""
    try:
        d = json.loads(r["text"])
    except Exception as e:
        return {"erro": f"{str(e)[:120]} (status {r.get('status')}: {(r.get('text') or '')[:100]!r})"}
    if not isinstance(d, dict) or d.get("id") is None:
        return {"erro": f"resposta sem detalhe (status {r.get('status')}): {(r.get('text') or '')[:120]!r}"}
    ents = [e for e in (d.get("contractingEntities") or []) if isinstance(e, dict)]
    ent = ents[0] if ents else {}
    url_ok = lambda v: v if isinstance(v, str) and v.startswith("http") else None
    return {
        "titulo": _texto(d.get("contractDesignation")),
        "tipo_ato": _texto(d.get("type")),
        "procedimento": _texto(d.get("modelType")),
        "tipo_contrato": _texto(d.get("contractType")),
        "entidade": _texto([e.get("description") for e in ents]) or None,
        "nif": str(ent.get("nif")) if ent.get("nif") else None,
        "preco_base": parse_eur(d.get("basePrice")),
        "cpv": _texto(d.get("cpvs")),
        "local": _texto(d.get("executionPlace") or d.get("localExecucao") or d.get("executionPlaces")),
        "n_dr": _texto(d.get("announcementNumber")),
        "dr_numero": _texto(d.get("dreNumber")),
        "dr_pdf": url_ok(d.get("reference")),
        "plataforma_url": url_ok(d.get("contractingProcedureUrl")),
        "procedimento_id": str(d["contractingProcedureId"]) if d.get("contractingProcedureId") else None,
        "prazo_propostas": _texto(d.get("proposalDeadline")),
        "publicado": _fmt_pt(d.get("drPublicationDate")),
    }


def _prazo_iso(prazo: str | None, publicado_iso: str | None) -> tuple[str | None, bool]:
    """«13 dias.» → publicação + 13 dias (estimado); «02-11-2026» → ISO. Devolve (iso, estimado)."""
    if not prazo:
        return None, False
    m = re.match(r"^\s*(\d{1,3})\s*dias?", prazo, re.I)
    if m:
        pub = _data_iso(publicado_iso)
        if not pub:
            return None, False
        return (pub + timedelta(days=int(m.group(1)))).isoformat(), True
    return parse_date(prazo), False


TIPOS_ENCERRAM = ("adjudica", "anula", "revoga", "caducid", "extin", "nao adjudica")
TIPOS_ALTERAM = ("retifica", "rectifica", "prorroga", "altera", "correcao", "corrige")
TIPOS_IGNORAR = ("pre-informacao", "pre informacao", "preinformacao")


def _tipo(tipo_ato: str | None) -> str:
    """Classifica o tipo de ato do BASE: abre | altera | encerra | ignora."""
    t = norm(tipo_ato)
    if any(k in t for k in TIPOS_IGNORAR):
        return "ignora"
    if any(k in t for k in TIPOS_ENCERRAM):
        return "encerra"
    if any(k in t for k in TIPOS_ALTERAM):
        return "altera"
    return "abre"


CAMPOS_DETALHE = ("tipo_contrato", "nif", "cpv", "local", "n_dr", "dr_numero", "dr_pdf", "plataforma_url", "procedimento_id")


def _reabrir(page, debug: list[str]) -> None:
    try:
        page.goto(f"{BASE_URL}/Base4/pt/pesquisa/", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(3000)
    except Exception as e:
        debug.append(f"não consegui reabrir a pesquisa: {str(e)[:120]}")


def _pedir_com_pausa(page, form: dict, estado: dict, debug: list[str]) -> dict | None:
    """Um pedido ao BASE a ritmo controlado e por lotes. Esgotado o lote, pausa longa (se houver tempo)
    e continua; sem tempo, devolve None e fica `estado["sem_tempo"]`. Se a firewall bloquear, espera uma
    vez e repete; ao segundo bloqueio marca `estado["bloqueado"]` e devolve None."""
    if estado.get("bloqueado") or estado.get("sem_tempo"):
        return None
    if estado["pedidos_lote"] >= MAX_PEDIDOS_POR_LOTE:
        decorrido = time.time() - estado["inicio"]
        if decorrido + PAUSA_ENTRE_LOTES_S + 60 > TEMPO_MAX_S:
            estado["sem_tempo"] = True
            debug.append(f"lote {estado['lote']} esgotado ({estado['pedidos_lote']} pedidos) e sem tempo para outro; paro aqui")
            return None
        debug.append(f"lote {estado['lote']} esgotado ({estado['pedidos_lote']} pedidos, {round(decorrido)} s); pausa de {PAUSA_ENTRE_LOTES_S} s")
        time.sleep(PAUSA_ENTRE_LOTES_S)
        estado["lote"] += 1
        estado["pedidos_lote"] = 0
        _reabrir(page, debug)
    for tentativa in (1, 2):
        estado["pedidos_lote"] += 1
        estado["pedidos"] += 1
        try:
            r = _post_base(page, form)
        except Exception as e:
            debug.append(f"pedido falhou: {str(e)[:200]}")
            return None
        if not _bloqueado(r):
            return r
        if tentativa == 1 and not estado.get("ja_esperou"):
            estado["ja_esperou"] = True
            debug.append(f"firewall do BASE bloqueou (status {r.get('status')}) ao pedido {estado['pedidos']}; espero {ESPERA_BLOQUEIO_S} s e tento outra vez")
            time.sleep(ESPERA_BLOQUEIO_S)
            estado["lote"] += 1
            estado["pedidos_lote"] = 0
            _reabrir(page, debug)
            continue
        estado["bloqueado"] = True
        debug.append(f"firewall do BASE continua a bloquear (pedido {estado['pedidos']}); paro aqui (o resto fica pendente para a próxima execução)")
        return None
    return None


def base_anuncios_playwright(desde: date, conhecidos: set[str] | None = None, pendentes: set[str] | None = None,
                             titulos_seguidos: set[str] | None = None) -> tuple[list[dict], dict[str, dict], list[str], dict]:
    """Lê todas as páginas de anúncios publicados desde `desde` e o detalhe dos que podem interessar.
    `conhecidos`: ids cujo detalhe já temos (não se repete). `pendentes`: ids cujo detalhe ficou por ler
    numa execução anterior (lê-se mesmo fora da janela). `titulos_seguidos`: títulos (normalizados) dos
    procedimentos já na lista — serve para só ler o detalhe das alterações que lhes digam respeito.
    Devolve (linhas da lista, detalhes por id, diagnóstico, estado)."""
    conhecidos = conhecidos or set()
    pendentes = pendentes or set()
    titulos_seguidos = titulos_seguidos or set()
    estado: dict = {"bloqueado": False, "ja_esperou": False, "sem_tempo": False, "detalhes_por_ler": 0, "descoberta_por_ler": 0,
                    "pedidos": 0, "pedidos_lote": 0, "lote": 1, "inicio": time.time()}
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # pragma: no cover
        return [], {}, [f"playwright indisponível: {e}"], estado
    rows: list[dict] = []
    detalhes: dict[str, dict] = {}
    debug: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=UA["User-Agent"], locale="pt-PT")
        # Imagens, tipos de letra e CSS não fazem falta e contam para a firewall.
        page.route("**/*", lambda route: route.abort() if route.request.resource_type in ("image", "font", "stylesheet", "media") else route.continue_())
        try:
            form = _abrir_pesquisa_anuncios(page, desde, debug) or _form_pesquisa(desde)
            form["sort"] = "-drPublicationDate"
            debug.append(f"form_base={form}")
            # Paginação pelo próprio browser. O portal ignora o filtro de data e limita o tamanho da página:
            # lê-se por ordem decrescente de publicação e pára-se ao passar a data `desde`.
            vistos: set[str] = set()
            t0 = time.time()
            for pagina in range(0, MAX_PAGINAS):
                r = _pedir_com_pausa(page, dict(form, page=str(pagina), size="25"), estado, debug)
                if r is None:
                    break
                linhas, total = _linhas_json(r["text"])
                if pagina == 0:
                    debug.append(f"ajax status={r['status']} total={total} inicio={r['text'][:200]!r}")
                novas = [x for x in linhas if x["id"] not in vistos]
                vistos.update(x["id"] for x in novas)
                ult = _data_pt(linhas[-1]["publicado"]) if linhas else None
                if pagina < 3 or pagina % 10 == 9 or not linhas:
                    debug.append(f"pagina {pagina + 1}: {len(linhas)} linhas ({len(novas)} novas); ultima pub={ult}")
                if not linhas:
                    break
                rows += novas
                if ult and ult < desde:
                    break
                time.sleep(PAUSA_PAGINA_S)
            debug.append(f"lista: {len(rows)} anúncios em {round(time.time() - t0)} s")
            tipos: dict[str, int] = {}
            for x in rows:
                tipos[x.get("tipo_ato") or "?"] = tipos.get(x.get("tipo_ato") or "?", 0) + 1
            debug.append("tipos de ato: " + "; ".join(f"{k}={v}" for k, v in sorted(tipos.items(), key=lambda kv: -kv[1])))

            # Detalhes: só do que está na janela, ainda não conhecido e não excluído logo pelo título
            # (fornecimentos, viaturas…). As alterações só interessam se disserem respeito a um procedimento
            # que seguimos ou se o título, por si, for relevante.
            # Ordem: 1) pendentes de execuções anteriores; 2) relevantes pelo título/Minho (abre);
            # 3) alterações de procedimentos seguidos; 4) o resto (descoberta pelo CPV), se sobrar lote.
            titulos_lista = {norm(x.get("titulo"))[:70] for x in rows if _tipo(x.get("tipo_ato")) == "abre"}
            prioridade: dict[int, list[str]] = {1: [], 2: [], 3: [], 4: []}
            n_conhecidos = n_alt_ignoradas = 0
            for x in rows:
                if (_data_pt(x["publicado"]) or desde) < desde or _tipo(x.get("tipo_ato")) == "ignora":
                    continue
                if excluido(None, x.get("titulo")):
                    continue
                if x["id"] in pendentes:
                    prioridade[1].append(x["id"])
                    continue
                if x["id"] in conhecidos:
                    n_conhecidos += 1
                    continue
                relevante = bool(categorias(None, x.get("titulo"))) or e_minho(x.get("entidade"), x.get("titulo"))
                if _tipo(x.get("tipo_ato")) == "altera":
                    t = norm(x.get("titulo"))[:70]
                    if t in titulos_seguidos or t in titulos_lista or relevante:
                        prioridade[3].append(x["id"])
                    else:
                        n_alt_ignoradas += 1
                    continue
                prioridade[2 if relevante else 4].append(x["id"])
            ids_rows = {x["id"] for x in rows}
            prioridade[1] += [i for i in sorted(pendentes) if i not in ids_rows]
            candidatos = prioridade[1] + prioridade[2] + prioridade[3] + prioridade[4]
            essenciais = len(prioridade[1]) + len(prioridade[2]) + len(prioridade[3])

            def por_ler(n: int) -> None:
                # O que fica por ler: os essenciais contam como leitura incompleta; a descoberta pelo CPV não.
                estado["detalhes_por_ler"] = max(0, essenciais - n)
                estado["descoberta_por_ler"] = max(0, len(candidatos) - max(n, essenciais))
            debug.append(f"candidatos a detalhe: {len(candidatos)} (pendentes {len(prioridade[1])}, relevantes pelo título {len(prioridade[2])}, "
                         f"alterações {len(prioridade[3])}, descoberta por CPV {len(prioridade[4])}; {n_conhecidos} já conhecidos, "
                         f"{n_alt_ignoradas} alterações sem interesse) de {len(rows)} linhas")
            falhas = 0
            t0 = time.time()
            for n, aid in enumerate(candidatos[:MAX_DETALHES]):
                if estado["bloqueado"] or estado["sem_tempo"]:
                    por_ler(n)
                    break
                r = _pedir_com_pausa(page, {"type": "detail_anuncios", "version": "155.0", "id": aid}, estado, debug)
                if r is None:
                    por_ler(n)
                    break
                d = _detalhe_de_resposta(r)
                if d.get("erro"):
                    falhas += 1
                    if falhas <= 3:
                        debug.append(f"detalhe {aid} falhou: {d['erro']}")
                    if falhas >= 25 and falhas > len(detalhes):
                        debug.append("demasiadas falhas nos detalhes; paro")
                        por_ler(n)
                        break
                else:
                    detalhes[aid] = d
                time.sleep(PAUSA_DETALHE_S)
            debug.append(f"detalhes: {len(detalhes)} ok, {falhas} falhas, {estado['detalhes_por_ler']} essenciais por ler, "
                         f"{estado['descoberta_por_ler']} de descoberta por ler, {round(time.time() - t0)} s; "
                         f"{estado['pedidos']} pedidos em {estado['lote']} lote(s)")
        except Exception as e:
            print(f"  BASE via browser falhou: {e}")
            debug.append(f"erro={e}")
        finally:
            browser.close()
    return rows, detalhes, debug, estado


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
    m_dr = re.search(r"DR announcement nr:?\s*(\d{3,6}/20\d{2})", txt)
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


_MESES_EN = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def _data_en(v: str | None) -> str | None:
    """«Oct 15, 2026» / «October 15, 2026» → ISO."""
    if not v:
        return None
    m = re.match(r"\s*([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),\s*(\d{4})", str(v))
    if not m or m.group(1).lower() not in _MESES_EN:
        return parse_date(v)
    return f"{m.group(3)}-{_MESES_EN[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"


# ---------------------------------------------------------------- Classificação e saída
OBRA = {"eletricidade", "mobilidade_eletrica", "fotovoltaico", "seguranca_incendio"}
_INSTALA_RX = re.compile(r"\b(instala|montag|execu|coloca|substitui|implementa|desenvolv|manuten|reabilita|remodela|beneficia|requalifica|empreitada)")


def _norte(a: dict) -> bool:
    t = norm(" | ".join(str(a.get(k) or "") for k in ("entidade", "titulo", "local")))
    return any(re.search(r"\b" + re.escape(norm(d)) + r"\b", t) for d in DISTRITOS_NORTE)


def fornecimento_puro(a: dict) -> bool:
    """Compra de bens sem instalação/serviço associado (a VoltSync não é distribuidora)."""
    tc = norm(a.get("tipo_contrato"))
    if not tc or "bens" not in tc or "servico" in tc or "empreitada" in tc or "obra" in tc:
        return False
    return not _INSTALA_RX.search(norm(a.get("titulo")))


def classifica(a: dict) -> str:
    """A = Minho e no perfil. B = fora do Minho mas alcançável (Norte para obra; serviços até ao teto).
    C = resto (fora de perfil, acima do alvará, ou só fornecimento)."""
    cats = a.get("categorias") or []
    if not cats or fornecimento_puro(a):
        return "C"
    preco = a.get("preco_base") or 0
    obra = bool(OBRA & set(cats)) and not ({"software_ti", "projeto"} & set(cats))
    if TETO_EMPREITADA_EUR and obra and preco > TETO_EMPREITADA_EUR:
        return "C"  # acima da classe 2 do alvará: só consórcio/subempreitada
    if a.get("minho"):
        return "A"
    so_servicos = not (OBRA & set(cats))
    if so_servicos:
        return "B" if (not TETO_B_SERVICOS_EUR or preco <= TETO_B_SERVICOS_EUR) else "C"
    return "B" if _norte(a) else "C"


def _chave(a: dict) -> str:
    """Chave estável de um registo entre execuções: BASE pelo id do anúncio; outras fontes pelo URL."""
    if a.get("origem") == "BASE" and a.get("id"):
        return f"BASE-{a['id']}"
    return f"{a.get('origem')}-{a.get('url')}"


def _normalizar_datas(a: dict) -> None:
    """Datas em ISO; prazo «N dias.» → publicação + N (prazo_estimado=True). Idempotente."""
    pub = parse_date(a.get("publicado")) or _data_en(a.get("publicado"))
    if pub:
        a["publicado"] = pub
    prazo = a.get("prazo_propostas")
    if isinstance(prazo, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", prazo):
        a["prazo_estimado"] = bool(a.get("prazo_estimado"))
        return
    prazo_iso, estimado = _prazo_iso(prazo, a.get("publicado"))
    if not prazo_iso:
        prazo_iso = _data_en(prazo)
    a["prazo_propostas"] = prazo_iso
    a["prazo_estimado"] = bool(estimado) if prazo_iso else False


VISTOS_DIAS = 60


def carregar_vistos() -> dict[str, str]:
    """Ids do BASE cujo detalhe já foi lido e não interessou (id → data de publicação ISO). Evita reler
    todos os dias os mesmos anúncios fora de perfil."""
    try:
        d = json.loads((DATA_DIR / "anuncios_vistos.json").read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in d.get("vistos", {}).items()}
    except Exception:
        return {}


def guardar_vistos(vistos: dict[str, str], hoje: date) -> None:
    limite = (hoje - timedelta(days=VISTOS_DIAS)).isoformat()
    vivos = {k: v for k, v in vistos.items() if v >= limite}
    save_json("anuncios_vistos.json", {"gerado_em": hoje.isoformat(), "n": len(vivos), "vistos": vivos})


def carregar_anterior() -> tuple[dict[str, dict], dict]:
    """Lista da execução anterior (a lista é cumulativa), indexada pela chave origem-id, e o seu cabeçalho."""
    p = DATA_DIR / "anuncios.json"
    try:
        dados = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}, {}
    itens: dict[str, dict] = {}
    for a in dados.get("anuncios", []):
        if not isinstance(a, dict) or not a.get("origem"):
            continue
        if a.get("origem") != "BASE" and not a.get("id") and a.get("url"):
            a["id"] = a["url"].rsplit("/", 1)[-1][-16:]  # registos antigos do BidsFactory não tinham id
        _normalizar_datas(a)
        itens[_chave(a)] = a
    cabecalho = {k: v for k, v in dados.items() if k != "anuncios"}
    return itens, cabecalho


def janela(hoje: date, cabecalho: dict) -> date:
    """Desde quando ler o BASE: pelo menos JANELA_DIAS; até ao dia anterior à última leitura completa do
    BASE (`ultima_leitura_ok` nas estatísticas); JANELA_ARRANQUE na primeira execução de todas.
    RADAR_DESDE=AAAA-MM-DD força a data."""
    forcado = _data_iso(os.environ.get("RADAR_DESDE"))
    if forcado:
        return max(forcado, hoje - timedelta(days=JANELA_MAX))
    estat = cabecalho.get("estatisticas") or {}
    ultima = _data_iso(estat.get("ultima_leitura_ok")) or (_data_iso(cabecalho.get("gerado_em")) if estat.get("base_ok") else None)
    if ultima:
        desde = min(hoje - timedelta(days=JANELA_DIAS), ultima - timedelta(days=1))
    else:
        desde = hoje - timedelta(days=JANELA_ARRANQUE)
    return max(desde, hoje - timedelta(days=JANELA_MAX))


def ainda_aberto(a: dict, hoje: date) -> bool:
    prazo = _data_iso(a.get("prazo_propostas"))
    if prazo:
        return prazo >= hoje
    pub = _data_iso(a.get("publicado"))
    return bool(pub) and (hoje - pub).days <= DIAS_SEM_PRAZO


def _fundir(antigo: dict | None, novo: dict, hoje_iso: str) -> dict:
    """Mantém o que já sabíamos (primeira vez, alterações, url do BidsFactory) e atualiza com o lido hoje."""
    a = {**antigo, **{k: v for k, v in novo.items() if v not in (None, "", [])}} if antigo else dict(novo)
    a.setdefault("primeira_vez", hoje_iso)
    a["ultima_vez"] = hoje_iso
    return a


def main() -> int:
    hoje = date.today()
    hoje_iso = hoje.isoformat()
    anteriores, cabecalho = carregar_anterior()
    desde = janela(hoje, cabecalho)
    print(f"0) Lista anterior: {len(anteriores)} anúncios (gerada em {cabecalho.get('gerado_em') or '?'}); leio o BASE desde {desde.isoformat()}", flush=True)

    # ---- 1. BASE: lista + detalhes
    print("1) Portal BASE via browser…", flush=True)
    base_ant = {a["id"]: a for a in anteriores.values() if a.get("origem") == "BASE" and a.get("id")}
    vistos = carregar_vistos()
    conhecidos = {i for i, a in base_ant.items() if a.get("procedimento_id") or a.get("cpv")} | set(vistos)
    pendentes = {i for i, a in base_ant.items() if a.get("detalhe_pendente")}
    titulos_seguidos = {norm(a.get("titulo"))[:70] for a in base_ant.values() if a.get("titulo")}
    base_rows, detalhes, debug, estado_base = base_anuncios_playwright(desde, conhecidos, pendentes, titulos_seguidos)
    base_ok = len(base_rows) > 0
    leitura_completa = base_ok and not estado_base.get("bloqueado") and not estado_base.get("detalhes_por_ler")
    print(f"   {len(base_rows)} anúncios na lista desde {desde.isoformat()}; {len(detalhes)} detalhes lidos "
          f"({estado_base.get('pedidos', 0)} pedidos em {estado_base.get('lote', 1)} lote(s))"
          + ("; FIREWALL bloqueou — leitura incompleta" if estado_base.get("bloqueado") else "")
          + ("; sem tempo para mais lotes" if estado_base.get("sem_tempo") else "")
          + (f"; {estado_base['detalhes_por_ler']} detalhes ficam para a próxima execução" if estado_base.get("detalhes_por_ler") else ""), flush=True)

    novos: dict[str, dict] = {}          # chave → anúncio que abre procedimento, relevante
    por_proc: dict[str, str] = {}        # procedimento_id / plataforma_url → chave
    alteracoes: list[dict] = []
    encerramentos: list[dict] = []
    n_sem_detalhe = n_excluidos = 0
    for r in base_rows:
        if (_data_pt(r["publicado"]) or desde) < desde:
            continue
        d = detalhes.get(r["id"])
        if not d and r["id"] in base_ant and r["id"] in conhecidos:
            d = {k: v for k, v in base_ant[r["id"]].items() if k in CAMPOS_DETALHE}
        if not d and r["id"] in vistos:
            continue  # já lido numa execução anterior e sem interesse
        pendente = False
        if not d:
            # Sem detalhe (firewall ou falha): classifica pelo título e fica pendente para a próxima execução.
            if _tipo(r.get("tipo_ato")) != "abre" or excluido(None, r.get("titulo")):
                continue
            d = {}
            pendente = True
            n_sem_detalhe += 1
        a = {**r, **{k: v for k, v in d.items() if v not in (None, "", [])}}
        # A lista traz a data-limite absoluta («04-11-2026»); o detalhe só «N dias.». Fica a data.
        if parse_date(r.get("prazo_propostas")):
            a["prazo_propostas"] = r["prazo_propostas"]
        a["detalhe_pendente"] = pendente
        a["categorias"] = categorias(a.get("cpv"), a.get("titulo"))
        a["minho"] = e_minho(a.get("entidade"), a.get("titulo"), local=a.get("local"))
        _normalizar_datas(a)
        tipo = _tipo(a.get("tipo_ato"))
        if tipo == "encerra":
            encerramentos.append(a)
            continue
        if tipo == "altera":
            alteracoes.append(a)
            continue
        if not a["categorias"] and not a["minho"]:
            n_excluidos += 1
            if not pendente and a.get("publicado"):
                vistos[r["id"]] = a["publicado"]  # lido e sem interesse: não voltar a ler
            continue
        k = _chave(a)
        novos[k] = a
        for ref in (a.get("procedimento_id"), a.get("plataforma_url")):
            if ref:
                por_proc[ref] = k
    # Detalhes pendentes de execuções anteriores que chegaram agora.
    n_pendentes_resolvidos = 0
    for i in pendentes:
        d = detalhes.get(i)
        a = base_ant.get(i)
        if not d or not a or _chave(a) in novos:
            continue
        a.update({k: v for k, v in d.items() if v not in (None, "", [])})
        a["detalhe_pendente"] = False
        a["categorias"] = categorias(a.get("cpv"), a.get("titulo"))
        a["minho"] = e_minho(a.get("entidade"), a.get("titulo"), local=a.get("local"))
        _normalizar_datas(a)
        n_pendentes_resolvidos += 1
    print(f"   {len(novos)} anúncios de procedimento relevantes (perfil ou Minho); {n_excluidos} fora de perfil; "
          f"{len(alteracoes)} retificações/prorrogações; {len(encerramentos)} encerramentos; {n_sem_detalhe} só com título (pendentes); "
          f"{n_pendentes_resolvidos} pendentes resolvidos", flush=True)

    # ---- 2. Fusão com a lista anterior (cumulativa)
    lista: dict[str, dict] = {}
    for k, antigo in anteriores.items():
        if antigo.get("origem") != "BASE":
            continue
        for ref in (antigo.get("procedimento_id"), antigo.get("plataforma_url")):
            if ref:
                por_proc.setdefault(ref, k)
        lista[k] = antigo
    for k, a in novos.items():
        lista[k] = _fundir(lista.get(k), a, hoje_iso)

    # Retificações/prorrogações: ficam registadas no anúncio original e podem alargar o prazo.
    n_alt_aplicadas = 0
    for alt in alteracoes:
        k = next((por_proc[ref] for ref in (alt.get("procedimento_id"), alt.get("plataforma_url")) if ref and ref in por_proc), None)
        registo = {"tipo": alt.get("tipo_ato"), "publicado": alt.get("publicado"), "id": alt["id"], "url": alt["url"],
                   "n_dr": alt.get("n_dr"), "prazo_propostas": alt.get("prazo_propostas")}
        if k and k in lista:
            orig = lista[k]
            orig.setdefault("alteracoes", [])
            if not any(x.get("id") == alt["id"] for x in orig["alteracoes"]):
                orig["alteracoes"].append(registo)
                n_alt_aplicadas += 1
            novo_prazo = alt.get("prazo_propostas")
            if novo_prazo and (not orig.get("prazo_propostas") or novo_prazo > orig["prazo_propostas"]):
                orig["prazo_propostas"] = novo_prazo
                orig["prazo_estimado"] = bool(alt.get("prazo_estimado"))
            orig["ultima_vez"] = hoje_iso
        elif alt.get("categorias") or alt.get("minho"):
            # Retificação de um anúncio que não temos (publicado antes da janela): entra como anúncio, assinalado.
            alt["alteracoes"] = [registo]
            lista[_chave(alt)] = _fundir(anteriores.get(_chave(alt)), alt, hoje_iso)
            for ref in (alt.get("procedimento_id"), alt.get("plataforma_url")):
                if ref:
                    por_proc[ref] = _chave(alt)
    n_encerrados = 0
    for enc in encerramentos:
        k = next((por_proc[ref] for ref in (enc.get("procedimento_id"), enc.get("plataforma_url")) if ref and ref in por_proc), None)
        if k and k in lista:
            lista.pop(k)
            n_encerrados += 1

    # ---- 3. BidsFactory: só de recurso, quando o BASE não respondeu (o BASE é a fonte dos próprios dados do BidsFactory).
    n_bf = 0
    if not base_ok:
        print("2) BASE sem resposta → BidsFactory (recurso)…", flush=True)
        for r in bidsfactory_listas():
            t = r["titulo_en"]
            det = bidsfactory_detalhe(r["url"])
            a = {"origem": "BidsFactory", "id": r["url"].rsplit("/", 1)[-1][-16:], "url": r["url"], "titulo": det.get("titulo_pt") or t, "titulo_en": t, **det}
            a["categorias"] = categorias(a.get("cpv"), a.get("titulo"))
            a["minho"] = e_minho(a.get("entidade"), a.get("titulo"))
            time.sleep(0.4)
            if not a["categorias"] and not a["minho"]:
                continue
            _normalizar_datas(a)
            lista[_chave(a)] = _fundir(anteriores.get(_chave(a)), a, hoje_iso)
            n_bf += 1
        print(f"   {n_bf} do BidsFactory", flush=True)
    else:
        print("2) BidsFactory: não é preciso (BASE respondeu)", flush=True)
    # Registos BidsFactory antigos: mantêm-se enquanto o prazo correr e não existir o mesmo anúncio vindo do BASE.
    por_ndr = {a["n_dr"]: k for k, a in lista.items() if a.get("origem") == "BASE" and a.get("n_dr")}
    por_titulo = {norm(a.get("titulo"))[:70]: k for k, a in lista.items() if a.get("origem") == "BASE" and a.get("titulo")}
    n_bf_substituidos = 0
    for k, antigo in list(anteriores.items()) + list(lista.items()):
        if antigo.get("origem") != "BidsFactory":
            continue
        kb = por_ndr.get(antigo.get("n_dr") or "") or por_titulo.get(norm(antigo.get("titulo"))[:70])
        if kb:
            lista[kb].setdefault("url_bidsfactory", antigo["url"])
            if k in lista:
                lista.pop(k)
            n_bf_substituidos += 1
            continue
        lista.setdefault(k, antigo)

    # ---- 4. Expiração, classificação e corte do que não interessa fora do Minho.
    # As categorias são recalculadas para toda a lista: uma alteração ao perfil (config.py) aplica-se também
    # ao que já lá estava.
    expirados = [k for k, a in lista.items() if not ainda_aberto(a, hoje)]
    for k in expirados:
        lista.pop(k)
    anuncios = []
    n_c_fora = 0
    for a in lista.values():
        a["categorias"] = categorias(a.get("cpv"), a.get("titulo"))
        a["minho"] = e_minho(a.get("entidade"), a.get("titulo"), local=a.get("local"))
        a.setdefault("primeira_vez", a.get("publicado") or hoje_iso)
        a["classe"] = classifica(a)
        if a["classe"] == "C" and not a.get("minho"):
            n_c_fora += 1  # fora de perfil E fora do Minho: não há nada a fazer com isto
            continue
        anuncios.append(a)
    ordem = {"A": 0, "B": 1, "C": 2}
    anuncios.sort(key=lambda x: (ordem[x["classe"]], x.get("prazo_propostas") or "9999"))
    estat_ant = cabecalho.get("estatisticas") or {}
    estat = {
        "base_ok": base_ok,
        "leitura_completa": leitura_completa,
        "ultima_leitura_ok": hoje_iso if leitura_completa else estat_ant.get("ultima_leitura_ok"),
        "firewall_bloqueou": bool(estado_base.get("bloqueado")),
        "detalhes_pendentes": sum(1 for a in anuncios if a.get("detalhe_pendente")),
        "descoberta_por_ler": int(estado_base.get("descoberta_por_ler") or 0),
        "vistos_sem_interesse": len(vistos),
        "janela_desde": desde.isoformat(),
        "base_lidos": len(base_rows),
        "base_detalhes": len(detalhes),
        "base_relevantes_hoje": len(novos),
        "alteracoes_aplicadas": n_alt_aplicadas,
        "encerrados": n_encerrados,
        "bidsfactory_novos": n_bf,
        "bidsfactory_substituidos": n_bf_substituidos,
        "expirados_removidos": len(expirados),
        "c_fora_do_minho_omitidos": n_c_fora,
        "por_classe": {c: sum(1 for a in anuncios if a["classe"] == c) for c in ("A", "B", "C")},
    }
    debug.append("estatisticas=" + json.dumps(estat, ensure_ascii=False))
    save_text("base_debug.txt", "\n".join(debug) + "\n")
    save_json("anuncios.json", {"gerado_em": datetime.now().isoformat(timespec="minutes"), "n": len(anuncios), "estatisticas": estat, "anuncios": anuncios})
    guardar_vistos(vistos, hoje)

    linhas = [f"# Radar VoltSync — anúncios abertos ({hoje.isoformat()})", "",
              f"Fontes: BASE via browser ({len(base_rows)} anúncios lidos desde {desde.isoformat()}, {len(detalhes)} detalhes)"
              + (f", BidsFactory ({n_bf} de recurso)" if n_bf else "") + ". "
              f"Lista cumulativa: {len(anuncios)} abertos ({estat['por_classe']['A']} A, {estat['por_classe']['B']} B, {estat['por_classe']['C']} C); "
              f"{len(expirados)} expirados removidos hoje; {n_alt_aplicadas} retificações registadas.", "",
              "| Classe | Entidade | Objeto | Preço base (€) | Prazo propostas | Procedimento | CPV | N.º DR | Link |",
              "|---|---|---|---|---|---|---|---|---|"]
    for a in anuncios:
        if a["classe"] == "C":
            continue
        linhas.append("| {c} | {e} | {o} | {p} | {pr} | {proc} | {cpv} | {dr} | {u} |".format(
            c=a["classe"], e=(a.get("entidade") or "?").replace("|", "/"), o=(a.get("titulo") or "")[:120].replace("|", "/"),
            p=f"{a['preco_base']:,.0f}".replace(",", " ") if a.get("preco_base") else "?",
            pr=(a.get("prazo_propostas") or "?") + ("≈" if a.get("prazo_estimado") else "") + (" (retif.)" if a.get("alteracoes") else ""),
            proc=a.get("procedimento") or "?", cpv=(a.get("cpv") or ("pendente" if a.get("detalhe_pendente") else "?"))[:10], dr=a.get("n_dr") or "", u=a["url"]))
    cs = [a for a in anuncios if a["classe"] == "C"]
    if cs:
        linhas += ["", "## Minho, fora de perfil / acima do alvará / só fornecimento (C)", ""] + \
                  [f"- {a.get('entidade') or '?'} — {(a.get('titulo') or '')[:100]} — {a['url']}" for a in cs[:40]]
    if not any(a["classe"] in ("A", "B") for a in anuncios):
        linhas += ["", "**Sem resultados A/B.**"]
    if not base_ok:
        linhas += ["", "**Atenção: o BASE não respondeu nesta execução — a lista só tem o que já existia e o BidsFactory.**"]
    elif not leitura_completa:
        motivo = "a firewall do BASE interrompeu a leitura" if estado_base.get("bloqueado") else "acabou o tempo da execução"
        linhas += ["", f"**Atenção: {motivo} — {estat['detalhes_pendentes']} anúncios estão classificados só pelo título (CPV «pendente») e serão completados na próxima execução.**"]
    save_text("anuncios_resumo.md", "\n".join(linhas) + "\n")
    print(f"OK: {len(anuncios)} anúncios abertos ({estat['por_classe']}); {len(expirados)} expirados removidos; {n_c_fora} C fora do Minho omitidos; "
          f"leitura {'completa' if leitura_completa else 'INCOMPLETA'}.")
    return 0 if base_ok else 1


if __name__ == "__main__":
    sys.exit(main())
