"""Funções partilhadas pelo radar."""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import html

from config import (CONCELHOS_MINHO, CPV_PREFIXOS, DISTRITOS_MINHO, ENTIDADES_MINHO, EXCLUIR,
                    EXCLUIR_CPV, EXCLUIR_REGEX, KEYWORDS)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def norm(s: str | None) -> str:
    """Minúsculas, sem acentos, espaços comprimidos."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


_CONCELHOS_N = [norm(c) for c in CONCELHOS_MINHO]
_DISTRITOS_N = [norm(d) for d in DISTRITOS_MINHO]
_ENTIDADES_N = [norm(e) for e in ENTIDADES_MINHO]
_EXCLUIR_RX = [re.compile(rx) for rx in EXCLUIR_REGEX]


def _flat(x) -> list[str]:
    if x is None:
        return []
    if isinstance(x, (list, tuple, set)):
        return [str(i) for i in x if i]
    return [str(x)]


def local_e_minho(local) -> bool | None:
    """Decide pelo campo 'localExecucao' do BASE ('Portugal, Braga, Guimarães').
    Devolve None se o campo não existir ou não for interpretável."""
    entradas = _flat(local)
    if not entradas:
        return None
    decidiu = False
    for e in entradas:
        partes = [norm(x) for x in e.split(",")]
        if len(partes) >= 2 and partes[0].startswith("portugal"):
            decidiu = True
            if partes[1] in _DISTRITOS_N:
                return True
    return False if decidiu else None


def e_minho(*textos, local=None) -> bool:
    """Minho = distritos de Braga e Viana do Castelo.
    Se houver 'local' de execução interpretável, manda o local; senão, procura concelhos/entidades no texto."""
    por_local = local_e_minho(local)
    if por_local is not None:
        return por_local
    t = " | ".join(norm(x) for x in textos if x)
    if not t:
        return False
    if any(re.search(r"\b" + re.escape(d) + r"\b", t) for d in _DISTRITOS_N):
        return True
    if any(re.search(r"\b" + re.escape(c) + r"\b", t) for c in _CONCELHOS_N):
        return True
    return any(re.search(r"\b" + re.escape(e) + r"\b", t) for e in _ENTIDADES_N)


def excluido(cpv: str | None, *textos: str | None) -> bool:
    t = " | ".join(norm(x) for x in textos if x)
    if any(norm(k) in t for k in EXCLUIR):
        return True
    if any(re.search(rx, t) for rx in _EXCLUIR_RX):
        return True
    return any(code.startswith(p) for code in re.findall(r"\d{8}", cpv or "") for p in EXCLUIR_CPV)


def nif_de(nome: str | None) -> str:
    """'513606084 - Águas do Norte SA' -> '513606084'; sem NIF devolve o nome normalizado."""
    if not nome:
        return "?"
    m = re.match(r"\s*(\d{9})\s*-", str(nome))
    return m.group(1) if m else norm(nome)


def nome_limpo(nome: str | None) -> str:
    if not nome:
        return "?"
    partes = [x for x in html.unescape(str(nome)).split(";") if x.strip()]
    s = re.sub(r"^\s*\d{9}\s*-\s*", "", partes[0] if partes else str(nome))
    s = re.sub(r"\s+", " ", s).strip(" -")
    if len(partes) > 1:
        s += f" (+{len(partes) - 1})"
    return s


def _kw_match(k: str, t: str) -> bool:
    """Palavras curtas (erp, crm, api, ups, sadi, cctv…) só contam como palavra inteira."""
    if len(k) <= 5:
        return re.search(r"\b" + re.escape(k) + r"\b", t) is not None
    return k in t


def categorias(cpv: str | None, *textos: str | None) -> list[str]:
    """Devolve as categorias do perfil VoltSync em que o registo encaixa (vazio se excluído)."""
    if excluido(cpv, *textos):
        return []
    cats: list[str] = []
    cpv_codes = re.findall(r"\d{8}", cpv or "")
    t = " | ".join(norm(x) for x in textos if x)
    for cat, prefixes in CPV_PREFIXOS.items():
        if any(code.startswith(p) for code in cpv_codes for p in prefixes):
            cats.append(cat)
            continue
        if any(_kw_match(norm(k), t) for k in KEYWORDS.get(cat, [])):
            cats.append(cat)
    return cats


def parse_eur(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[€\s\u00a0]", "", str(v)).strip(".,")
    # Formato PT (120.000,00) ou EN (120,000.00): o último separador é o decimal se for seguido de 1-2 dígitos.
    m = re.search(r"[.,](\d{1,2})$", s)
    if m:
        dec = s[m.start()]
        s = s[:m.start()].replace(".", "").replace(",", "") + "." + m.group(1)
    else:
        s = s.replace(".", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_date(v) -> str | None:
    """Normaliza para ISO (AAAA-MM-DD). Aceita dd-mm-aaaa, dd/mm/aaaa, ISO."""
    if not v:
        return None
    s = str(v).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def pick(d: dict, *candidates: str):
    """Primeiro campo existente (sem distinguir maiúsculas) de uma lista de nomes possíveis."""
    lower = {k.lower(): k for k in d.keys()}
    for c in candidates:
        if c.lower() in lower:
            return d[lower[c.lower()]]
    return None


def save_json(name: str, obj) -> Path:
    p = DATA_DIR / name
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def save_text(name: str, text: str) -> Path:
    p = DATA_DIR / name
    p.write_text(text, encoding="utf-8")
    return p
