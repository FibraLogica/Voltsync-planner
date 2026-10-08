"""Gera data/prospecao_minho.xlsx a partir de data/prospecao_minho.json e data/base_minho.json.
Folha de trabalho comercial: lista priorizada, últimos contratos por entidade, concorrentes, legenda."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from common import DATA_DIR, nif_de, nome_limpo

AZUL = "042EA2"; TEAL = "1AACA0"; CINZA = "4B6582"; AMARELO = "FFF2CC"; CLARO = "EAF3FB"
H_FONT = Font(name="Arial", bold=True, color="FFFFFF", size=10)
B_FONT = Font(name="Arial", size=10)
FINO = Side(style="thin", color="D0D7E2")
BORDA = Border(left=FINO, right=FINO, top=FINO, bottom=FINO)


def cab(ws, row, headers, widths):
    for i, (h, w) in enumerate(zip(headers, widths), 1):
        c = ws.cell(row=row, column=i, value=h)
        c.font = H_FONT; c.fill = PatternFill("solid", fgColor=AZUL)
        c.alignment = Alignment(vertical="center", wrap_text=True); c.border = BORDA
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[row].height = 30


def main() -> int:
    pj = json.loads((DATA_DIR / "prospecao_minho.json").read_text(encoding="utf-8"))
    ents = pj["entidades"]
    regs = json.loads((DATA_DIR / "base_minho.json").read_text(encoding="utf-8"))["registos"]
    wb = Workbook()

    # ---------------- Prospeção
    ws = wb.active; ws.title = "Prospeção"
    ws["A1"] = "Prospeção comercial VoltSync — entidades do Minho que contratam por convite (ajuste direto / consulta prévia)"
    ws["A1"].font = Font(name="Arial", bold=True, size=13, color=AZUL)
    ws["A2"] = f"Fonte: Portal BASE (IMPIC), últimos 18 meses, gerado em {pj['gerado_em']}. Preencher só as colunas amarelas (Estado, Responsável, Contacto, Próximo passo, Data, Notas)."
    ws["A2"].font = Font(name="Arial", italic=True, size=9, color=CINZA)
    headers = ["#", "Entidade", "NIF", "Prioridade", "Contratos (18 m)", "Por convite", "€ por convite", "Eletricidade", "Projeto", "Software/TI",
               "Mob. elétrica", "Fotovoltaico", "Seg./incêndio", "<20 k€", "20–75 k€", "75–150 k€", ">150 k€", "Fornecedores habituais",
               "Forn. dominante %", "Último contrato", "Último objeto", "Pesquisa no BASE",
               "Estado", "Responsável", "Contacto (nome/email/telefone)", "Próximo passo", "Data", "Notas"]
    widths = [4, 42, 11, 10, 9, 9, 13, 9, 8, 9, 8, 9, 9, 7, 8, 8, 8, 48, 9, 11, 50, 14, 16, 12, 30, 24, 11, 30]
    cab(ws, 4, headers, widths)
    r0 = 5
    for i, e in enumerate(ents, 1):
        r = r0 + i - 1
        cats = e["categorias"]; fx = e["faixas_preco"]
        vals = [i, e["entidade"], e["nif"], e["prioridade"], e["contratos"], e["por_convite"], e["valor_por_convite"],
                cats.get("eletricidade", 0), cats.get("projeto", 0), cats.get("software_ti", 0), cats.get("mobilidade_eletrica", 0),
                cats.get("fotovoltaico", 0), cats.get("seguranca_incendio", 0),
                fx.get("<20k", 0), fx.get("20-75k", 0), fx.get("75-150k", 0), fx.get(">150k", 0),
                "; ".join(f"{f['nome']} ({f['contratos']})" for f in e["fornecedores_habituais"][:3]),
                e["fornecedor_dominante_pct"] / 100, e["ultimo_contrato"],
                e["ultimos_contratos"][0]["objeto"] if e["ultimos_contratos"] else "", e["base_url"] or "",
                "Por contactar", "", "", "", "", ""]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=j, value=v); c.font = B_FONT; c.border = BORDA
            c.alignment = Alignment(vertical="top", wrap_text=j in (2, 18, 21, 25, 26, 28))
        ws.cell(row=r, column=7).number_format = "#,##0 €"
        ws.cell(row=r, column=19).number_format = "0%"
        if e["base_url"]:
            ws.cell(row=r, column=22).hyperlink = e["base_url"]; ws.cell(row=r, column=22).value = "abrir contratos"
            ws.cell(row=r, column=22).font = Font(name="Arial", size=10, color="0D74D8", underline="single")
        for j in range(23, 29):
            ws.cell(row=r, column=j).fill = PatternFill("solid", fgColor=AMARELO)
        if i <= 10:
            ws.cell(row=r, column=2).font = Font(name="Arial", size=10, bold=True)
    rN = r0 + len(ents) - 1
    dv = DataValidation(type="list", formula1='"Por contactar,Contactado,Reunião marcada,Registado como fornecedor,Convidado,Proposta entregue,Ganho,Perdido,Sem interesse"', allow_blank=True)
    ws.add_data_validation(dv); dv.add(f"W{r0}:W{rN}")
    dv2 = DataValidation(type="list", formula1='"Helder,Crislaine"', allow_blank=True)
    ws.add_data_validation(dv2); dv2.add(f"X{r0}:X{rN}")
    ws.freeze_panes = "C5"; ws.auto_filter.ref = f"A4:{get_column_letter(len(headers))}{rN}"
    ws.row_dimensions[1].height = 22

    # ---------------- Últimos contratos
    wc = wb.create_sheet("Últimos contratos")
    cab(wc, 1, ["Entidade", "NIF", "Data", "Objeto", "Preço (€)", "Procedimento", "Fornecedor", "Categorias", "Link BASE"], [40, 11, 11, 70, 12, 24, 36, 24, 14])
    r = 2
    for e in ents:
        for u in e["ultimos_contratos"]:
            vals = [e["entidade"], e["nif"], u["data"], u["objeto"], u["preco"], u["procedimento"], u["fornecedor"], ", ".join(u["categorias"]), ""]
            for j, v in enumerate(vals, 1):
                c = wc.cell(row=r, column=j, value=v); c.font = B_FONT; c.border = BORDA; c.alignment = Alignment(vertical="top", wrap_text=j == 4)
            wc.cell(row=r, column=5).number_format = "#,##0 €"
            if u.get("url"):
                wc.cell(row=r, column=9).value = "abrir"; wc.cell(row=r, column=9).hyperlink = u["url"]
                wc.cell(row=r, column=9).font = Font(name="Arial", size=10, color="0D74D8", underline="single")
            r += 1
    wc.freeze_panes = "A2"; wc.auto_filter.ref = f"A1:I{r - 1}"

    # ---------------- Concorrentes
    wk = wb.create_sheet("Concorrentes")
    forn: dict[str, dict] = defaultdict(lambda: {"nome": "", "n": 0, "valor": 0.0, "cats": Counter(), "clientes": Counter()})
    for x in regs:
        f = nif_de(x["adjudicatario"]); d = forn[f]
        d["nome"] = d["nome"] or nome_limpo(x["adjudicatario"]); d["n"] += 1; d["valor"] += x["preco"] or 0
        for c in x["categorias"]:
            d["cats"][c] += 1
        d["clientes"][nome_limpo(x["adjudicante"])] += 1
    cab(wk, 1, ["Fornecedor", "NIF", "Contratos (18 m)", "Valor total (€)", "Categorias", "Principais clientes"], [46, 11, 10, 14, 34, 60])
    r = 2
    for f, d in sorted(forn.items(), key=lambda kv: -kv[1]["n"])[:120]:
        vals = [d["nome"], f if f.isdigit() else "", d["n"], d["valor"], ", ".join(f"{c} ({k})" for c, k in d["cats"].most_common()),
                "; ".join(f"{c} ({k})" for c, k in d["clientes"].most_common(4))]
        for j, v in enumerate(vals, 1):
            c = wk.cell(row=r, column=j, value=v); c.font = B_FONT; c.border = BORDA; c.alignment = Alignment(vertical="top", wrap_text=j in (5, 6))
        wk.cell(row=r, column=4).number_format = "#,##0 €"
        r += 1
    wk.freeze_panes = "A2"; wk.auto_filter.ref = f"A1:F{r - 1}"

    # ---------------- Resumo / legenda (com fórmulas sobre a folha de trabalho)
    wl = wb.create_sheet("Resumo", 0)
    wl["A1"] = "Resumo do funil"; wl["A1"].font = Font(name="Arial", bold=True, size=13, color=AZUL)
    estados = ["Por contactar", "Contactado", "Reunião marcada", "Registado como fornecedor", "Convidado", "Proposta entregue", "Ganho", "Perdido", "Sem interesse"]
    wl["A3"] = "Estado"; wl["B3"] = "Entidades"; wl["C3"] = "€ por convite (18 m)"
    for c in ("A3", "B3", "C3"):
        wl[c].font = H_FONT; wl[c].fill = PatternFill("solid", fgColor=AZUL)
    for i, s in enumerate(estados, 4):
        wl[f"A{i}"] = s
        wl[f"B{i}"] = f'=COUNTIF(Prospeção!$W${r0}:$W${rN},A{i})'
        wl[f"C{i}"] = f'=SUMIF(Prospeção!$W${r0}:$W${rN},A{i},Prospeção!$G${r0}:$G${rN})'
        wl[f"C{i}"].number_format = "#,##0 €"
        for c in ("A", "B", "C"):
            wl[f"{c}{i}"].font = B_FONT; wl[f"{c}{i}"].border = BORDA
    fim = 4 + len(estados)
    wl[f"A{fim}"] = "Total"; wl[f"B{fim}"] = f"=SUM(B4:B{fim - 1})"; wl[f"C{fim}"] = f"=SUM(C4:C{fim - 1})"; wl[f"C{fim}"].number_format = "#,##0 €"
    for c in ("A", "B", "C"):
        wl[f"{c}{fim}"].font = Font(name="Arial", bold=True, size=10); wl[f"{c}{fim}"].border = BORDA
    wl.column_dimensions["A"].width = 30; wl.column_dimensions["B"].width = 12; wl.column_dimensions["C"].width = 20

    leg = fim + 2
    wl[f"A{leg}"] = "Como ler a folha Prospeção"; wl[f"A{leg}"].font = Font(name="Arial", bold=True, size=11, color=AZUL)
    notas = [
        "Prioridade = n.º de contratos por convite × peso da categoria (obra elétrica 1,0; segurança 0,8; projeto 0,7; software 0,6) × 1,2 se contratou nos últimos 12 meses (0,8 se não) × 0,7 se um só fornecedor leva mais de 60 % (mercado fechado).",
        "Por convite = ajuste direto (regime geral) + consulta prévia. Limiares CCP desde 1 out 2026 (DL 177/2026): ajuste direto até 150.000 € empreitadas / 75.000 € serviços; consulta prévia até 1.000.000 € / 130.000 €.",
        "Faixas de preço = quantos contratos a entidade fez em cada faixa: diz em que escalão a VoltSync deve apresentar-se.",
        "Fornecedor dominante % = quota do fornecedor mais usado; acima de 60 % é difícil entrar.",
        "Células amarelas são as únicas a preencher. Estado e Responsável têm lista pendente. O Resumo atualiza-se sozinho.",
        "Alvará VoltSync 117403-PUB: classe 2 (empreitadas até 332.000 €), 4.ª categoria, subcategorias 1.ª–8.ª, 10.ª–12.ª, 16.ª–19.ª.",
        "Fonte dos dados: dataset oficial do IMPIC (dados.gov.pt), contratos publicados no Portal BASE. Regenerado todas as segundas-feiras pelo pipeline Radar VoltSync (GitHub).",
    ]
    for i, n in enumerate(notas, leg + 1):
        wl[f"A{i}"] = n; wl[f"A{i}"].font = B_FONT; wl[f"A{i}"].alignment = Alignment(wrap_text=True, vertical="top")
        wl.merge_cells(f"A{i}:F{i}"); wl.row_dimensions[i].height = 32
    wl.column_dimensions["D"].width = 20; wl.column_dimensions["E"].width = 20; wl.column_dimensions["F"].width = 20

    out = DATA_DIR / "prospecao_minho.xlsx"
    wb.save(out)
    print(f"OK: {out} ({len(ents)} entidades)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
