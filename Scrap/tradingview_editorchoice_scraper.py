"""
TradingView Scraper — Editor's Picks (Indicators) EXCLUSIVO
=============================================================
Gera uma tabela própria (trading_view_editorchoice.csv/.json), SEM misturar
com as outras bases do projeto, referente apenas a:

    https://www.tradingview.com/scripts/editors-picks/?script_type=indicators

Essa listagem é PAGINADA (page-1 .. page-N, N ~29 hoje), então o scraper
percorre TODAS as páginas detectadas no rodapé da página 1 antes de parar.

Fluxo:
  1) Baixa a página 1 ao vivo, detecta a última página pela paginação e baixa
     todas as páginas seguintes (page-2, page-3, ... até a última).
  2) Salva tudo como um novo snapshot local (vira a "v3", futura base de
     comparação da próxima rodada).
  3) Compara com o snapshot/baseline anterior para descobrir quais scripts
     são NOVOS desde a última atualização.
  4) Acessa a página interna de cada script para completar Views e Tags
     (mesma lógica do tradingview_scraper_final.py).
  5) Salva CSV/JSON exclusivos desta lista, com os mesmos campos das outras
     tabelas + 3 campos extras: posicao, descricao, origem, e o campo novo
     "novo" (1 = apareceu depois da última atualização).

Uso:
    pip install beautifulsoup4 lxml requests
    python tradingview_editorchoice_scraper.py
"""

import csv
import hashlib
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

# Evita UnicodeEncodeError no console do Windows (cp1252) ao imprimir acentos/─.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── Configuração ──────────────────────────────────────────────────────────────
LIVE_BASE      = "https://www.tradingview.com/scripts/editors-picks/"
LIVE_QUERY     = "?script_type=indicators"

# Snapshot anterior (baseline) já salvo no projeto — usado só para
# descobrir quais itens são novos. NÃO entra misturado no resultado final.
# Prioridade: JSON de uma rodada anterior COMPLETA (todas as páginas) deste
# próprio script; se não existir, cai pro HTML "v2" (que só tinha a página 1).
BASELINE_JSON = "trading_view_editorchoice.json"
BASELINE_HTML = "base de indicadores  editor choice v2.htm"

SNAPSHOT_DIR = "."  # onde salvar o novo snapshot (v3) baixado agora

OUTPUT_CSV  = "trading_view_editorchoice.csv"
OUTPUT_JSON = "trading_view_editorchoice.json"
CHECKPOINT_FILE = "checkpoint_editorchoice.json"

ORIGEM = "editors_pick_indicators"

FETCH_INNER = True    # False = só lista, sem entrar em cada página (views/tags)
DELAY_MIN   = 2.5
DELAY_MAX   = 5.0
MAX_SCRIPTS = None

MAX_LIST_PAGES  = None   # None = segue até a última página detectada na paginação
DELAY_PAGE_MIN  = 1.5    # delay entre páginas da LISTAGEM (mais leve que a FASE 2)
DELAY_PAGE_MAX  = 3.0

DESCRICAO_MAX_CHARS = 300  # trunca a descrição pra caber numa tabela

# Cache compartilhado das páginas internas (views/tags), mesmo esquema do
# tradingview_scraper_final_v1_gpt.py: inner_<sha1(url)>.html
# Aponta pra pasta real onde o cache já existe (fora deste projeto).
CACHE_HTML = True
CACHE_DIR = r"D:\Documentos\Projetos\TradingView-scrap\tv_cache_html"

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
    FMTS = [
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
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
    try:
        return parsedate_to_datetime(cleaned).strftime("%d/%m/%Y")
    except Exception:
        return raw


# ══════════════════════════════════════════════════════════════════════════════
#  Download da página ao vivo (paginado: page-1, page-2, ... até a última)
# ══════════════════════════════════════════════════════════════════════════════

def _page_url(page: int) -> str:
    if page <= 1:
        return f"{LIVE_BASE}{LIVE_QUERY}"
    return f"{LIVE_BASE}page-{page}/{LIVE_QUERY}"


def _detect_last_page(soup: BeautifulSoup) -> int:
    """Lê os links de paginação (href=".../page-N/...") e retorna o maior N."""
    max_page = 1
    for a in soup.find_all("a", href=re.compile(r"/page-\d+/?")):
        m = re.search(r"/page-(\d+)/?", a.get("href", ""))
        if m:
            max_page = max(max_page, int(m.group(1)))
    return max_page


def fetch_live_pages() -> list:
    """Baixa todas as páginas da listagem (paginação real). Retorna lista de HTMLs."""
    if not HAS_REQUESTS:
        print("[ERRO] Instale requests: pip install requests")
        sys.exit(1)

    htmls = []
    page = 1
    last_page = 1

    while True:
        url = _page_url(page)
        print(f"[LIVE] Baixando página {page} ... {url}")
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            print(f"       HTTP {resp.status_code} — parando paginação.")
            break

        html = resp.text
        htmls.append(html)
        print(f"       HTTP {resp.status_code} — {len(html)} bytes")

        if page == 1:
            soup = BeautifulSoup(html, "lxml")
            detected = _detect_last_page(soup)
            last_page = detected if MAX_LIST_PAGES is None else min(detected, MAX_LIST_PAGES)
            print(f"       paginação detectada: última página = {detected} (usando até {last_page})")

        if page >= last_page:
            break

        page += 1
        time.sleep(random.uniform(DELAY_PAGE_MIN, DELAY_PAGE_MAX))

    print(f"[LIVE] Total de páginas baixadas: {len(htmls)}\n")
    return htmls


def save_snapshot(htmls: list) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(SNAPSHOT_DIR, f"base de indicadores editor choice v3_{stamp}.htm")
    with open(path, "w", encoding="utf-8") as f:
        for i, html in enumerate(htmls, start=1):
            f.write(f"<!-- ===== PAGE {i} ===== -->\n")
            f.write(html)
            f.write("\n")
    print(f"[SALVO] Snapshot novo ({len(htmls)} páginas): {path}")
    return path


# ══════════════════════════════════════════════════════════════════════════════
#  Parsing dos cards
# ══════════════════════════════════════════════════════════════════════════════

def parse_urls_only(html: str) -> set:
    """Usado só pro baseline (v2 HTML antigo), pra saber o que já existia."""
    soup = BeautifulSoup(html, "lxml")
    cards = soup.find_all("article", class_=re.compile(r"card-exterior"))
    urls = set()
    for card in cards:
        tl = card.find("a", attrs={"data-qa-id": "ui-lib-card-link-title"})
        if tl and tl.get("href"):
            urls.add(tl.get("href"))
    return urls


def parse_listing_pages(htmls: list) -> list:
    """Recebe o HTML de várias páginas (page-1, page-2, ...) e retorna os
    registros combinados, deduplicados por URL, com posicao contínua."""
    records = []
    seen_urls = set()
    posicao = 0

    for page_idx, html in enumerate(htmls, start=1):
        soup = BeautifulSoup(html, "lxml")
        cards = soup.find_all("article", class_=re.compile(r"card-exterior"))
        print(f"[LISTA] página {page_idx}: {len(cards)} cards encontrados.")

        for card in cards:
            posicao += 1
            rec = _parse_card(card, posicao=posicao)
            url = rec["url"]
            if url and url not in seen_urls:
                seen_urls.add(url)
                records.append(rec)

    print(f"[LISTA] Total único combinado: {len(records)} scripts.\n")
    return records


def _parse_card(card, posicao: int) -> dict:
    # Título e URL
    tl    = card.find("a", attrs={"data-qa-id": "ui-lib-card-link-title"})
    url   = tl.get("href", "") if tl else ""
    title = tl.get_text(strip=True) if tl else ""

    # Descrição (parágrafo do card)
    pe = card.find("a", attrs={"data-qa-id": "ui-lib-card-link-paragraph"})
    descricao = ""
    if pe:
        texto = pe.get_text(" ", strip=True)
        texto = re.sub(r"\s+", " ", texto)
        if len(texto) > DESCRICAO_MAX_CHARS:
            texto = texto[:DESCRICAO_MAX_CHARS].rstrip() + "…"
        descricao = texto

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
        "posicao":          posicao,
        "titulo":           title,
        "url":              url,
        "descricao":        descricao,
        "autor":            author,
        "url_autor":        author_url,
        "data_atualizacao": date_updated,
        "boosts":           boosts,
        "comentarios":      comments,
        "origem":           ORIGEM,
        "novo":             "",  # preenchido depois do diff com o baseline
        # preenchidos na FASE 2
        "views":            "",
        "tags":             "",
        "_status":          "",
        "_cache_inner":     "",
    }


# ══════════════════════════════════════════════════════════════════════════════
#  FASE 2 — Página interna (Views + Tags), igual ao scraper original
# ══════════════════════════════════════════════════════════════════════════════

def _cache_path_for_url(url: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, f"inner_{h}.html")


def enrich_from_inner(record: dict, session) -> dict:
    url = record.get("url", "")
    if not url:
        record["_status"] = "sem_url"
        return record

    cache_path = _cache_path_for_url(url) if CACHE_HTML else None
    from_cache = False

    try:
        if cache_path and os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8", errors="replace") as f:
                html_text = f.read()
            record["_status"] = "200"
            from_cache = True
        else:
            resp = session.get(url, headers=HEADERS, timeout=20)
            record["_status"] = str(resp.status_code)
            if resp.status_code != 200:
                return record
            html_text = resp.text
            if cache_path:
                with open(cache_path, "w", encoding="utf-8") as f:
                    f.write(html_text)

        record["_cache_inner"] = "1" if from_cache else "0"
        soup = BeautifulSoup(html_text, "lxml")

        views_div = soup.find("div", class_=re.compile(r"\bviews-\w+"))
        if views_div:
            for icon_span in views_div.find_all("span", attrs={"aria-hidden": "true"}):
                icon_span.decompose()
            views_raw = views_div.get_text(strip=True)
            record["views"] = re.sub(r"[\s\xa0   ]", "", views_raw)

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
        w = csv.DictWriter(f, fieldnames=list(records[0].keys()), quoting=csv.QUOTE_ALL)
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
    # 1) baseline (rodada anterior) — só pra diff, não entra na tabela final.
    # Prioridade: JSON de uma rodada anterior COMPLETA (todas as páginas) deste
    # script. Só cai pro HTML "v2" (que tinha só a página 1) se não houver JSON.
    old_urls = set()
    if os.path.exists(BASELINE_JSON):
        try:
            with open(BASELINE_JSON, "r", encoding="utf-8") as f:
                prev = json.load(f)
            old_urls = {r.get("url", "") for r in prev if r.get("url")}
            print(f"[BASELINE] '{BASELINE_JSON}' (rodada anterior): {len(old_urls)} scripts.\n")
        except Exception as e:
            print(f"[AVISO] Não consegui ler {BASELINE_JSON}: {str(e)[:80]}")

    if not old_urls and os.path.exists(BASELINE_HTML):
        with open(BASELINE_HTML, "r", encoding="utf-8", errors="replace") as f:
            old_urls = parse_urls_only(f.read())
        print(f"[BASELINE] '{BASELINE_HTML}' (só página 1 — parcial): {len(old_urls)} scripts.\n")

    if not old_urls:
        print("[AVISO] Nenhum baseline encontrado — todos serão marcados como novos.\n")

    # 2) baixa TODAS as páginas ao vivo e salva um snapshot novo (vira a próxima baseline)
    live_htmls = fetch_live_pages()
    save_snapshot(live_htmls)

    # 3) parse da lista atual (todas as páginas combinadas)
    records = parse_listing_pages(live_htmls)
    if MAX_SCRIPTS:
        records = records[:MAX_SCRIPTS]
    total = len(records)

    if total == 0:
        print("Nenhum card encontrado na página ao vivo.")
        sys.exit(1)

    # 4) marca quem é novo desde a última atualização
    novos = []
    for rec in records:
        is_new = rec["url"] not in old_urls
        rec["novo"] = "1" if is_new else "0"
        if is_new:
            novos.append(rec)

    removidos = old_urls - {r["url"] for r in records}

    # 5) FASE 2 — enriquece views/tags
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

        print(f"[FASE 2] {total} páginas | delay {DELAY_MIN}-{DELAY_MAX}s\n")

        for i in range(done, total):
            rec = records[i]
            tag_novo = " [NOVO]" if rec["novo"] == "1" else ""
            print(f"  [{i+1:3}/{total}] {rec.get('titulo', '?')[:55]}{tag_novo}")
            records[i] = enrich_from_inner(rec, session)
            r = records[i]
            cache_tag = " (cache)" if r.get("_cache_inner") == "1" else ""
            print(f"           status={r['_status']}  views={r['views'] or '-'}  tags={r['tags'][:40] if r['tags'] else '-'}{cache_tag}")

            if (i + 1) % 25 == 0:
                save_checkpoint(records, i + 1)
                save_csv(records, OUTPUT_CSV)
                print(f"  -- checkpoint {i+1}/{total} --\n")

            if r.get("_cache_inner") != "1":
                time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)

    # 6) salva tabela exclusiva
    save_csv(records, OUTPUT_CSV)
    save_json(records, OUTPUT_JSON)

    # 7) relatório
    print("\n── Editor's Picks (Indicators) — resumo ──")
    print(f"  Total agora:              {total}")
    print(f"  Novos desde última rodada: {len(novos)}")
    print(f"  Saíram desde última rodada: {len(removidos)}")
    if novos:
        print("\n  Novos scripts:")
        for r in novos:
            print(f"    [{r['posicao']:>2}] {r['titulo']}  -  {r['url']}")
    if removidos:
        print("\n  Scripts que saíram da lista:")
        for u in removidos:
            print(f"    {u}")

    print("\n── Cobertura dos campos ──")
    for field in ["views", "tags", "boosts", "comentarios", "data_atualizacao", "descricao"]:
        filled = sum(1 for r in records if r.get(field))
        pct = filled / total * 100 if total else 0
        print(f"  {field:20}: {filled:4}/{total}  ({pct:.0f}%)")


if __name__ == "__main__":
    main()
