"""
TradingView Scraper v3
======================
FASE 1 → Lê MÚLTIPLOS arquivos HTML locais, mescla tudo e remove duplicatas por URL.
FASE 2 → Acessa cada página interna e extrai Views e Tags.

Arquivos de entrada configurados em HTML_FILES abaixo.

Uso:
    pip install beautifulsoup4 lxml requests
    python tradingview_scraper_final.py
"""

import csv
import json
import re
import time
import random
import os
import sys
from datetime import datetime
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ── Configuração ──────────────────────────────────────────────────────────────
HTML_FILES = [
    "base_de_extensão.htm",
    "Base de indicadores v2.htm",
    "base de indicadores  editor choice v2.htm",
]

OUTPUT_CSV      = "tradingview_completo.csv"
OUTPUT_JSON     = "tradingview_completo.json"
CHECKPOINT_FILE = "checkpoint.json"

FETCH_INNER = True    # False = só FASE 1, sem acessar páginas internas
DELAY_MIN   = 2.5     # segundos mínimos entre requests
DELAY_MAX   = 5.0     # segundos máximos
MAX_SCRIPTS = None    # None = todos; ex: 10 para testar

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.tradingview.com/scripts/",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}
# ─────────────────────────────────────────────────────────────────────────────


def _fmt_date(raw: str) -> str:
    """Converte qualquer string de data para dd/mm/aaaa. Retorna '' se falhar."""
    if not raw:
        return ""
    # Formatos mais comuns primeiro (do mais específico ao mais genérico)
    FMTS = [
        "%Y-%m-%dT%H:%M:%S.%fZ",    # 2026-04-24T23:09:10.000Z  ← o que apareceu
        "%Y-%m-%dT%H:%M:%SZ",        # 2026-04-24T23:09:10Z
        "%Y-%m-%dT%H:%M:%S.%f%z",   # com timezone numérico
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
        "%d %b %Y",
        "%d/%m/%Y",
    ]
    cleaned = raw.strip()
    for fmt in FMTS:
        try:
            return datetime.strptime(cleaned, fmt).strftime("%d/%m/%Y")
        except ValueError:
            pass
    # Último recurso: email.utils (RFC 2822)
    try:
        return parsedate_to_datetime(cleaned).strftime("%d/%m/%Y")
    except Exception:
        return raw  # devolve como veio


# ══════════════════════════════════════════════════════════════════════════════
#  FASE 1 — Listagem local (múltiplos HTMLs + deduplicação)
# ══════════════════════════════════════════════════════════════════════════════

def parse_all_listings(html_paths: list) -> list:
    all_records = []
    seen_urls   = set()

    for path in html_paths:
        if not os.path.exists(path):
            print(f"[AVISO] Arquivo não encontrado, pulando: {path}")
            continue

        print(f"[FASE 1] Lendo '{path}' ...")
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            html = f.read()

        soup  = BeautifulSoup(html, "lxml")
        cards = soup.find_all("article", class_=re.compile(r"card-exterior"))
        print(f"         {len(cards)} cards encontrados.")

        novos = 0
        for card in cards:
            rec = _parse_card(card)
            url = rec["url"]
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_records.append(rec)
                novos += 1

        print(f"         {novos} adicionados (únicos).")

    print(f"\n[FASE 1] Total único: {len(all_records)} scripts.\n")
    return all_records


def _parse_card(card) -> dict:
    # Título e URL
    tl    = card.find("a", attrs={"data-qa-id": "ui-lib-card-link-title"})
    url   = tl.get("href", "") if tl else ""
    title = tl.get_text(strip=True) if tl else ""

    # Autor
    ae         = card.find("address", attrs={"username": True})
    author     = ae.get("username", "") if ae else ""
    author_url = ""
    if ae:
        a = ae.find("a")
        if a:
            author_url = a.get("href", "")

    # Data de atualização → dd/mm/aaaa
    te           = card.find("time")
    date_updated = _fmt_date(te.get("datetime", "") if te else "")

    # Boosts
    be     = card.find(attrs={"aria-label": re.compile(r"\d+ boosts?", re.I)})
    boosts = ""
    if be:
        m = re.search(r"([\d,]+)\s+boosts?", be.get("aria-label", ""), re.I)
        boosts = m.group(1).replace(",", "") if m else ""

    # Comentários
    ce       = card.find("a", attrs={"aria-label": re.compile(r"\d+ comments?", re.I)})
    comments = ""
    if ce:
        m = re.search(r"(\d+)\s+comments?", ce.get("aria-label", ""), re.I)
        comments = m.group(1) if m else ""

    return {
        "titulo":           title,
        "url":              url,
        "autor":            author,
        "url_autor":        author_url,
        "data_atualizacao": date_updated,
        "boosts":           boosts,
        "comentarios":      comments,
        # preenchidos na FASE 2
        "views":            "",
        "tags":             "",
        "_status":          "",
    }


# ══════════════════════════════════════════════════════════════════════════════
#  FASE 2 — Página interna (Views + Tags)
# ══════════════════════════════════════════════════════════════════════════════

def enrich_from_inner(record: dict, session) -> dict:
    url = record.get("url", "")
    if not url:
        record["_status"] = "sem_url"
        return record

    try:
        resp = session.get(url, headers=HEADERS, timeout=20)
        record["_status"] = str(resp.status_code)

        if resp.status_code != 200:
            return record

        soup = BeautifulSoup(resp.text, "lxml")

        # ── Views ─────────────────────────────────────────────────────────────
        # <div class="apply-common-tooltip views-r2SckERE">
        #   <span aria-hidden="true" ...><svg>...</svg></span>2 975
        # </div>
        views_div = soup.find("div", class_=re.compile(r"\bviews-\w+"))
        if views_div:
            # Remove o span que contém o ícone SVG
            for icon_span in views_div.find_all("span", attrs={"aria-hidden": "true"}):
                icon_span.decompose()
            # Remove espaços normais, &nbsp;, narrow no-break space, thin space
            views_raw = views_div.get_text(strip=True)
            record["views"] = re.sub(r"[\s\xa0\u202f\u2009\u00a0]", "", views_raw)

        # ── Tags ──────────────────────────────────────────────────────────────
        # <section class="root-lxExxEni tags-aqIxarm1">
        #   <a href="/scripts/t3/">
        #     <span class="tag-text-rVj4hiuX xsmall-rVj4hiuX">T3 Moving Average</span>
        #   </a>
        # </section>
        tag_section = soup.find("section", class_=re.compile(r"\btags-\w+"))
        if tag_section:
            tag_spans = tag_section.find_all("span", class_=re.compile(r"\btag-text-\w+"))
            tags = [s.get_text(strip=True) for s in tag_spans if s.get_text(strip=True)]
            record["tags"] = " | ".join(tags)

    except requests.exceptions.Timeout:
        record["_status"] = "timeout"
    except requests.exceptions.ConnectionError:
        record["_status"] = "conn_error"
    except Exception as e:
        record["_status"] = f"erro: {str(e)[:60]}"

    return record


# ══════════════════════════════════════════════════════════════════════════════
#  Checkpoint
# ══════════════════════════════════════════════════════════════════════════════

def save_checkpoint(records: list, done: int):
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump({"done": done, "records": records}, f, ensure_ascii=False)


def load_checkpoint(expected_len: int):
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if len(data.get("records", [])) == expected_len:
            print(f"[CHECKPOINT] Retomando do item {data['done'] + 1}...\n")
            return data["records"], data["done"]
    return [], 0


# ══════════════════════════════════════════════════════════════════════════════
#  Output
# ══════════════════════════════════════════════════════════════════════════════

def save_csv(records: list, path: str):
    if not records:
        return
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(records[0].keys()),
                           quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(records)
    print(f"[SALVO] {path}  ({len(records)} linhas)")


def save_json(records: list, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"[SALVO] {path}")


# ══════════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    # Permite sobrescrever a lista de HTMLs via argumentos
    html_paths = sys.argv[1:] if len(sys.argv) > 1 else HTML_FILES

    # FASE 1 — lê todos os HTMLs e deduplica
    records = parse_all_listings(html_paths)

    if MAX_SCRIPTS:
        records = records[:MAX_SCRIPTS]
    total = len(records)

    if total == 0:
        print("Nenhum card encontrado. Verifique os arquivos HTML.")
        sys.exit(1)

    # FASE 2
    if not FETCH_INNER:
        print("[FASE 2] Pulada (FETCH_INNER=False).")
    elif not HAS_REQUESTS:
        print("[FASE 2] Instale requests: pip install requests")
    else:
        saved, done = load_checkpoint(total)
        if saved:
            records = saved
        else:
            done = 0

        session = requests.Session()
        session.headers.update(HEADERS)

        est_min = total * (DELAY_MIN + DELAY_MAX) / 2 / 60
        est_max = total * DELAY_MAX / 60
        print(f"[FASE 2] {total} páginas | delay {DELAY_MIN}–{DELAY_MAX}s")
        print(f"         Estimativa: {est_min:.0f}–{est_max:.0f} min\n")

        for i in range(done, total):
            rec = records[i]
            print(f"  [{i+1:4}/{total}] {rec.get('titulo', '?')[:60]}")
            records[i] = enrich_from_inner(rec, session)
            r = records[i]
            print(f"           status={r['_status']}  "
                  f"views={r['views'] or '—'}  "
                  f"tags={r['tags'][:45] if r['tags'] else '—'}")

            # Salva checkpoint e CSV parcial a cada 25 itens
            if (i + 1) % 25 == 0:
                save_checkpoint(records, i + 1)
                save_csv(records, OUTPUT_CSV)
                print(f"  ── checkpoint {i+1}/{total} ──\n")

            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

        # Remove checkpoint ao terminar com sucesso
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)

    # ── Arquivo final único ───────────────────────────────────────────────────
    save_csv(records, OUTPUT_CSV)
    save_json(records, OUTPUT_JSON)

    # ── Estatísticas de cobertura ─────────────────────────────────────────────
    print("\n── Cobertura dos campos ──")
    for field in ["views", "tags", "boosts", "comentarios", "data_atualizacao"]:
        filled = sum(1 for r in records if r.get(field))
        pct    = filled / total * 100 if total else 0
        print(f"  {field:20}: {filled:4}/{total}  ({pct:.0f}%)")


if __name__ == "__main__":
    main()