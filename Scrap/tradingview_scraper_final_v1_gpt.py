"""
TradingView Scraper FINAL
=========================
Mantém o que já funcionava na v3 e adiciona melhorias sem quebrar o fluxo antigo.

Principais melhorias:
    - MODE = "local", "online" ou "both"
    - URLs absolutas e script_id para deduplicação mais segura
    - Coluna nova: Script = open_source | protected | invite_only | unknown
    - Busca online por keywords + paginação tradicional
    - query_source para rastrear qual keyword encontrou cada script
    - Execução autônoma por tiers: Tier 1 → pausa → Tier 2 → pausa → Tier 3
    - Continuidade por tiers: carrega saída existente, mescla por script_id e cria backup
    - Cache HTML opcional para reduzir requests repetidos

Uso local, compatível com v3:
    pip install beautifulsoup4 lxml requests
    python tradingview_scraper_final.py

Uso online por keywords:
    MODE já vem como "both" e RUN_TIERS_SEQUENTIALLY=True no bloco de configuração.

Observação:
    Este scraper usa requests + BeautifulSoup. Se o TradingView carregar algum bloco
    somente via JavaScript/infinite scroll, essa parte exigirá Playwright/Selenium
    em uma versão futura.
"""

import csv
import hashlib
import json
import glob
import os
import random
import re
import sys
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote

from bs4 import BeautifulSoup

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURAÇÃO PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

BASE_URL = "https://www.tradingview.com"

# "local"  = mantém fluxo antigo: lê HTML_FILES locais.
# "online" = busca por KEYWORDS no TradingView.
# "both"   = soma HTML local + busca online e deduplica.
MODE = "both"

HTML_FILES = [
    "base_de_extensão.htm",
    "Base de indicadores v2.htm",
    "base de indicadores  editor choice v2.htm",
]

# True = além dos HTML_FILES acima, procura automaticamente todos os arquivos .htm/.html
# na pasta onde o script está sendo executado. Isso evita esquecer bases locais como
# "Base de indicadores RSI-V1.htm", "Base de indicadores MACD-V1.htm", etc.
AUTO_DISCOVER_LOCAL_HTML = True

# Se quiser ignorar algum HTML local, coloque um trecho do nome aqui.
HTML_IGNORE_PATTERNS = [
    "~$",
    "tv_cache",
]

OUTPUT_CSV      = "tradingview_completo.csv"
OUTPUT_JSON     = "tradingview_completo.json"
CHECKPOINT_FILE = "checkpoint_inner.json"
SEARCH_PARTIAL_JSON = "tradingview_search_partial.json"

# Página interna: views, tags e Script.
# True = após descobrir todos os scripts dos tiers, já abre as páginas internas automaticamente.
FETCH_INNER = True

# Segurança/tempo.
MAX_SCRIPTS = None                  # None = todos; ex: 10 para teste rápido
MAX_PAGES_PER_KEYWORD = None        # None = respeita somente a paginação encontrada no rodapé do HTML
MAX_SEARCH_REQUESTS_PER_RUN = None  # None = sem limite por rodada para páginas de busca online
MAX_INNER_REQUESTS_PER_RUN = None   # None = sem limite por rodada para páginas internas

# Execução autônoma por tiers.
# True = roda Tier 1, pausa, Tier 2, pausa, Tier 3, e só depois faz a FASE INTERNA.
RUN_TIERS_SEQUENTIALLY = True
TIERS_SEQUENCE = [1, 2, 3, 4]
PAUSE_BETWEEN_TIERS_SECONDS = 30   # 30 seg

# Continuidade entre rodadas: carrega CSV/JSON existente, mescla por script_id e não perde o que já foi salvo.
LOAD_EXISTING_OUTPUT = True
SKIP_ALREADY_ENRICHED = True
BACKUP_EXISTING_OUTPUT = True

# Parada inteligente por baixo rendimento. Em coleta completa, deixe False para ir até a última página detectada.
STOP_ON_LOW_YIELD = False
MIN_NEW_PER_PAGE = 3
STOP_AFTER_LOW_YIELD_PAGES = 2

# Delays separados. Busca online usa delay maior; página interna mantém ritmo leve.
DELAY_SEARCH_MIN = 1.5
DELAY_SEARCH_MAX = 6.0
DELAY_INNER_MIN  = 1.0
DELAY_INNER_MAX  = 3.0


# Parar imediatamente nestes status.
STOP_ON_STATUS = {403, 429}

# Baixa HTML uma vez e reutiliza em execuções futuras.
CACHE_HTML = True
CACHE_DIR = "tv_cache_html"

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


# ══════════════════════════════════════════════════════════════════════════════
#  KEYWORDS POR TIERS
# ══════════════════════════════════════════════════════════════════════════════
# Se RUN_TIERS_SEQUENTIALLY=True, o script usa TIERS_SEQUENCE.
# Se RUN_TIERS_SEQUENTIALLY=False, usa ACTIVE_TIERS manualmente.

ACTIVE_TIERS = [1]

KEYWORDS_TIER_1 = [
    # Essenciais / alta precisão
    "rsi", "rsx", "qqe", "connors rsi", "stochastic rsi",
    "macd", "macd-v", "zero lag macd", "ppo",
    "stochastic", "stoch", "smi", "stochastic momentum index", "schaff", "stc",
    "supertrend", "vwap", "anchored vwap", "volume profile", "vpvr",
    "atr", "adx", "dmi", "bollinger", "keltner", "squeeze",
    "crypto", "bitcoin", "ethereum",
    "funding rate", "open interest", "liquidation",
]

KEYWORDS_TIER_2 = [
    # Boa cobertura / ruído moderado
    "scalping", "day trade", "daytrade", "swing trade", "swing trading",
    "position trade", "position trading",
    "cci", "williams", "awesome oscillator", "chande",
    "ichimoku", "kumo", "parabolic sar", "psar", "aroon", "vortex", "trix",
    "hull", "hma", "vwma", "alma", "frama", "kama", "ema", "sma", "wma",
    "tema", "dema", "zlema", "jurik", "jma", "vidya", "lsma",
    "donchian", "obv", "mfi", "cmf", "chaikin", "force index",
    "accumulation distribution", "adl", "cumulative delta", "volume delta",
    "footprint", "order flow", "support resistance", "pivot point", "fibonacci",
    "candlestick", "harmonic", "elliott", "zigzag",
]

KEYWORDS_TIER_3 = [
    # ==========================================
    # PREMIUM / ACESSO / QUALIDADE PERCEBIDA
    # Termos curtos, mas ainda úteis para achar scripts premium/protegidos.
    # ==========================================
    "premium",
    "paid",
    "invite only",
    "invite-only",
    "protected",
    "exclusive",
    "vip",
    "elite",
    "pro",
    "alpha",
    "ultimate",

    # ==========================================
    # APRIMORAMENTO TÉCNICO REAL
    # Termos-raiz, sem repetir "indicator".
    # ==========================================
    "optimized",
    "tuned",
    "enhanced",
    "advanced",
    "adaptive",
    "dynamic",
    "predictive",
    "smoothed",
    "filtered",
    "zerolag",
    "zero lag",
    "low lag",
    "no lag",
    "early signal",
    "leading",

    # ==========================================
    # QUANT / ESTATÍSTICA / FILTROS RECONHECIDOS
    # Mantidos apenas termos com boa chance de relevância técnica.
    # ==========================================
    "kalman",
    "kernel regression",
    "nadaraya watson",
    "rational quadratic",
    "bayesian",
    "probability",
    "probabilistic",
    "z-score",
    "z score",
    "mean reversion",

    # ==========================================
    # A.I. / MACHINE LEARNING
    # Termos compostos para reduzir ruído.
    # ==========================================
    "machine learning",
    "artificial intelligence",
    "neural network",
    "deep learning",
    "ai indicator",
    "ml indicator",
    "classifier",
    "prediction",
    "predictor",

    # ==========================================
    # CONFLUÊNCIA / SISTEMAS COMPOSTOS
    # Termos ligados a produtos mais completos.
    # ==========================================
    "confluence",
    "signal engine",
    "trend filter",
    "momentum filter",
    "confirmation",
    "multi timeframe",
    "mtf",
    "dashboard",
    "screener",
    "backtest",
]


KEYWORDS_TIER_4 = [
    # ==========================================
    # PROVEDORES / MARCAS PREMIUM
    # Busca direta por ecossistemas conhecidos.
    # ==========================================
    "luxalgo",
    "algoalpha",
    "simplealgo",
    "gainzalgo",
    "chartprime",
    "fluxcharts",
    "tradingcanyon",
    "algoz",
    "zeiierman",
    "indicator vault",
    "market cipher",
    "ezalgo",
    "infinity algo",
    "algopro",
    "trusted signals",
    "elite signals",
    "phantom flow",
    "quantzee",

    # ==========================================
    # AUTORES / GRUPOS FORTES
    # Nem todos são pagos, mas ajudam no garimpo de qualidade.
    # ==========================================
    "bigbeluga",
    "chartcandle",
    "quantnomad",
    "thetradingparrot",
    "lonesometheblue",
    "trendoscope",

    # ==========================================
    # ECOSSISTEMA PREMIUM
    # Termos compostos para reduzir ruído.
    # ==========================================
    "suite",
    "signal suite",
    "premium signals",
    "signal provider",
]


def get_keywords_for_tiers(tiers: list) -> list:
    """Retorna keywords dos tiers informados, removendo duplicatas e preservando ordem."""
    groups = []
    if 1 in tiers:
        groups.extend(KEYWORDS_TIER_1)
    if 2 in tiers:
        groups.extend(KEYWORDS_TIER_2)
    if 3 in tiers:
        groups.extend(KEYWORDS_TIER_3)
    if 4 in tiers:
        groups.extend(KEYWORDS_TIER_4)
    seen = set()
    out = []
    for kw in groups:
        k = kw.strip()
        if k and k.lower() not in seen:
            seen.add(k.lower())
            out.append(k)
    return out


def get_active_keywords() -> list:
    """Retorna keywords ativas no modo manual."""
    return get_keywords_for_tiers(ACTIVE_TIERS)


# ══════════════════════════════════════════════════════════════════════════════
#  UTILITÁRIOS
# ══════════════════════════════════════════════════════════════════════════════

def normalize_url(url: str) -> str:
    """Converte URLs relativas do TradingView para absolutas."""
    if not url:
        return ""
    url = url.strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/"):
        return BASE_URL + url
    return BASE_URL + "/" + url


def extract_script_id(url: str) -> str:
    """Extrai o ID/slug depois de /script/."""
    if not url:
        return ""
    m = re.search(r"/script/([^/?#]+)/?", url)
    return m.group(1) if m else url.strip().rstrip("/")


def clean_number(raw: str) -> str:
    """Remove espaços, vírgulas e caracteres não numéricos comuns."""
    if not raw:
        return ""
    raw = raw.replace(",", "")
    return re.sub(r"[^0-9]", "", raw)


def clean_title(raw: str) -> str:
    """Limpa título para CSV/Excel e evita palavras coladas quando possível."""
    if not raw:
        return ""

    title = str(raw).strip()

    # Vírgulas podem atrapalhar abertura manual do CSV no Excel.
    title = title.replace(",", " /")

    # Remove quebras de linha/tabs e normaliza espaços.
    title = re.sub(r"[\r\n\t]+", " ", title)
    title = re.sub(r"\s{2,}", " ", title)

    return title.strip()


def sanitize_records(records: list) -> list:
    """Aplica limpeza final nos registros antes de salvar CSV/JSON."""
    for r in records:
        if isinstance(r, dict) and "titulo" in r:
            r["titulo"] = clean_title(r.get("titulo", ""))
    return records


def _fmt_date(raw: str) -> str:
    """Converte qualquer string de data para dd/mm/aaaa. Retorna '' se falhar."""
    if not raw:
        return ""
    fmts = [
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
        "%d %b %Y",
        "%d/%m/%Y",
    ]
    cleaned = raw.strip()
    for fmt in fmts:
        try:
            return datetime.strptime(cleaned, fmt).strftime("%d/%m/%Y")
        except ValueError:
            pass
    try:
        return parsedate_to_datetime(cleaned).strftime("%d/%m/%Y")
    except Exception:
        return raw


def sleep_random(min_s: float, max_s: float):
    time.sleep(random.uniform(min_s, max_s))



def cache_path_for_url(url: str, prefix: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, f"{prefix}_{h}.html")


def fetch_html(session, url: str, *, prefix: str, timeout: int = 25):
    """
    Retorna (status_code, html, from_cache).
    Usa cache para evitar requests repetidos.
    """
    path = cache_path_for_url(url, prefix)
    if CACHE_HTML and os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return 200, f.read(), True

    resp = session.get(url, headers=HEADERS, timeout=timeout)
    status = resp.status_code
    html = resp.text if status == 200 else ""

    if CACHE_HTML and status == 200 and html:
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)

    return status, html, False


# ══════════════════════════════════════════════════════════════════════════════
#  PARSE DE LISTAGEM: LOCAL OU ONLINE
# ══════════════════════════════════════════════════════════════════════════════

def parse_listing_html(html: str, *, query_source: str = "", html_source: str = "") -> list:
    soup = BeautifulSoup(html, "lxml")
    cards = soup.find_all("article", class_=re.compile(r"card-exterior"))

    # Fallback caso o layout mude: links de scripts dentro de cards/áreas similares.
    if not cards:
        cards = []
        for a in soup.find_all("a", href=re.compile(r"/script/[^/]+/?")):
            parent = a.find_parent("article") or a.find_parent("div")
            if parent and parent not in cards:
                cards.append(parent)

    records = []
    for card in cards:
        rec = _parse_card(
            card,
            query_source=query_source,
            html_source=html_source,
        )
        if rec.get("url"):
            records.append(rec)
    return records


def get_local_html_files(configured_paths: list) -> list:
    """
    Retorna a lista de HTMLs locais que serão lidos.
    Mantém HTML_FILES e, se AUTO_DISCOVER_LOCAL_HTML=True, adiciona automaticamente
    todos os .htm/.html da pasta atual, sem duplicar.
    """
    candidates = list(configured_paths or [])

    if AUTO_DISCOVER_LOCAL_HTML:
        discovered = []
        for pattern in ["*.htm", "*.html"]:
            discovered.extend(glob.glob(pattern))

        for path in sorted(discovered, key=lambda x: x.lower()):
            name = os.path.basename(path)
            if any(ignore.lower() in name.lower() for ignore in HTML_IGNORE_PATTERNS):
                continue
            candidates.append(path)

    seen = set()
    out = []
    for path in candidates:
        norm = os.path.normcase(os.path.abspath(path))
        if norm not in seen:
            seen.add(norm)
            out.append(path)

    return out


def parse_all_listings(html_paths: list) -> list:
    all_records = []

    for path in html_paths:
        if not os.path.exists(path):
            print(f"[AVISO] Arquivo não encontrado, pulando: {path}")
            continue

        print(f"[LOCAL] Lendo '{path}' ...")
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            html = f.read()

        records = parse_listing_html(html, html_source=path)
        print(f"        {len(records)} cards encontrados.")
        all_records.extend(records)

    merged = merge_records(all_records)
    print(f"\n[LOCAL] Total único: {len(merged)} scripts.\n")
    return merged


def _parse_card(card, *, query_source: str = "", html_source: str = "") -> dict:
    # Título e URL: seletor original + fallback.
    tl = card.find("a", attrs={"data-qa-id": "ui-lib-card-link-title"})
    if not tl:
        tl = card.find("a", href=re.compile(r"/script/[^/]+/?"))

    url = normalize_url(tl.get("href", "")) if tl else ""
    title = clean_title(tl.get_text(" ", strip=True)) if tl else ""
    script_id = extract_script_id(url)

    # Autor
    ae = card.find("address", attrs={"username": True})
    author = ae.get("username", "") if ae else ""
    author_url = ""
    if ae:
        a = ae.find("a")
        if a:
            author_url = normalize_url(a.get("href", ""))

    # Data de atualização
    te = card.find("time")
    date_updated = _fmt_date(te.get("datetime", "") if te else "")

    # Boosts
    boosts = ""
    be = card.find(attrs={"aria-label": re.compile(r"[\d,]+\s+boosts?", re.I)})
    if be:
        m = re.search(r"([\d,]+)\s+boosts?", be.get("aria-label", ""), re.I)
        boosts = clean_number(m.group(1)) if m else ""

    # Comentários
    comments = ""
    ce = card.find("a", attrs={"aria-label": re.compile(r"[\d,]+\s+comments?", re.I)})
    if ce:
        m = re.search(r"([\d,]+)\s+comments?", ce.get("aria-label", ""), re.I)
        comments = clean_number(m.group(1)) if m else ""

    return {
        "script_id":         script_id,
        "titulo":            title,
        "url":               url,
        "autor":             author,
        "url_autor":         author_url,
        "data_atualizacao":  date_updated,
        "boosts":            boosts,
        "comentarios":       comments,
        # auditoria de descoberta
        "query_source":      query_source,
        # preenchidos na página interna
        "views":             "",
        "tags":              "",
        "Script":            "unknown",
        "_status":           "",
    }


def merge_records(records: list) -> list:
    """Deduplica por script_id; junta query_source quando o script aparece em várias buscas."""
    by_id = {}

    for rec in records:
        key = rec.get("script_id") or extract_script_id(rec.get("url", "")) or rec.get("url", "")
        if not key:
            continue

        if key not in by_id:
            by_id[key] = rec
            continue

        existing = by_id[key]

        # Preenche campos vazios do registro existente.
        for k, v in rec.items():
            if not existing.get(k) and v:
                existing[k] = v

        # Une origens de busca sem duplicar.
        for field in ["query_source"]:
            old = existing.get(field, "")
            new = rec.get(field, "")
            if new and new not in old.split(" | "):
                existing[field] = f"{old} | {new}" if old else new

    return list(by_id.values())


# ══════════════════════════════════════════════════════════════════════════════
#  DESCOBERTA ONLINE POR KEYWORDS
# ══════════════════════════════════════════════════════════════════════════════

def build_search_url(keyword: str, page: int) -> str:
    slug = quote(keyword.strip().lower(), safe="")
    if page <= 1:
        return f"{BASE_URL}/scripts/search/{slug}/"
    return f"{BASE_URL}/scripts/search/{slug}/page-{page}/"


def detect_last_page(soup: BeautifulSoup) -> int:
    """Lê a paginação e retorna a maior página encontrada. Se não achar, retorna 1."""
    max_page = 1
    for a in soup.find_all("a", href=re.compile(r"/page-\d+/?")):
        href = a.get("href", "")
        m = re.search(r"/page-(\d+)/?", href)
        if m:
            max_page = max(max_page, int(m.group(1)))
    return max_page


def discover_from_keywords(session, *, keywords: list = None, tier_label: str = None) -> list:
    keywords = keywords if keywords is not None else get_active_keywords()
    max_pages_label = "auto pelo HTML" if MAX_PAGES_PER_KEYWORD is None else str(MAX_PAGES_PER_KEYWORD)
    tier_info = tier_label or f"tiers={ACTIVE_TIERS}"
    print(f"[ONLINE] Keywords ativas: {len(keywords)} | {tier_info}")
    print(f"         Máx. páginas/keyword: {max_pages_label}")
    print(f"         Limite requests busca/rodada: {MAX_SEARCH_REQUESTS_PER_RUN}\n")

    all_records = []
    seen_ids = set()
    search_requests = 0

    for kw_index, keyword in enumerate(keywords, start=1):
        print(f"\n[KEYWORD {kw_index}/{len(keywords)}] {keyword!r}")
        last_page_hint = None
        low_yield_pages = 0
        page = 1

        while True:
            if MAX_SEARCH_REQUESTS_PER_RUN is not None and search_requests >= MAX_SEARCH_REQUESTS_PER_RUN:
                print("[LIMITE] MAX_SEARCH_REQUESTS_PER_RUN atingido. Parando descoberta online.")
                return merge_records(all_records)

            if MAX_PAGES_PER_KEYWORD is not None and page > MAX_PAGES_PER_KEYWORD:
                print(f"         limite manual de páginas atingido: {MAX_PAGES_PER_KEYWORD}")
                break

            if last_page_hint is not None and page > last_page_hint:
                break

            url = build_search_url(keyword, page)
            print(f"  [BUSCA] page={page} url={url}")

            try:
                status, html, from_cache = fetch_html(session, url, prefix="search")
            except Exception as e:
                print(f"         erro={str(e)[:80]}")
                break

            search_requests += 1
            print(f"         status={status} cache={from_cache}")

            if status in STOP_ON_STATUS:
                print(f"[PARADA] Status {status}. Interrompendo para evitar bloqueio/rate limit.")
                return merge_records(all_records)

            if status != 200 or not html:
                break

            soup = BeautifulSoup(html, "lxml")
            detected = detect_last_page(soup)
            if detected:
                if MAX_PAGES_PER_KEYWORD is None:
                    last_page_hint = max(last_page_hint or 1, detected)
                else:
                    last_page_hint = min(MAX_PAGES_PER_KEYWORD, max(last_page_hint or 1, detected))
                if page == 1:
                    print(f"         paginação detectada: até {detected}; usando até {last_page_hint}")

            records = parse_listing_html(html, query_source=keyword)

            if not records:
                print("         0 cards. Encerrando keyword.")
                break

            new_count = 0
            for rec in records:
                sid = rec.get("script_id")
                if sid and sid not in seen_ids:
                    seen_ids.add(sid)
                    all_records.append(rec)
                    new_count += 1

            print(f"         cards={len(records)} novos={new_count} total_unico={len(seen_ids)}")

            if STOP_ON_LOW_YIELD:
                if new_count < MIN_NEW_PER_PAGE:
                    low_yield_pages += 1
                else:
                    low_yield_pages = 0
                if low_yield_pages >= STOP_AFTER_LOW_YIELD_PAGES:
                    print("         baixo rendimento por páginas seguidas. Encerrando keyword.")
                    break

            if search_requests % 25 == 0:
                save_json(merge_records(all_records), SEARCH_PARTIAL_JSON)

            if not from_cache:
                sleep_random(DELAY_SEARCH_MIN, DELAY_SEARCH_MAX)

            page += 1

    merged = merge_records(all_records)
    save_json(merged, SEARCH_PARTIAL_JSON)
    print(f"\n[ONLINE] Total único descoberto: {len(merged)} scripts.\n")
    return merged

# ══════════════════════════════════════════════════════════════════════════════
#  FASE INTERNA: Views + Tags + Script
# ══════════════════════════════════════════════════════════════════════════════

def detect_script_access(soup: BeautifulSoup) -> str:
    """
    Detecta tipo de script pela página interna.
    Retorna: open_source | protected | invite_only | unknown
    """
    text = soup.get_text(" ", strip=True).upper()

    if "OPEN-SOURCE SCRIPT" in text or "OPEN SOURCE SCRIPT" in text:
        return "open_source"
    if "PROTECTED SCRIPT" in text:
        return "protected"
    if "INVITE-ONLY SCRIPT" in text or "INVITE ONLY SCRIPT" in text:
        return "invite_only"

    return "unknown"


def extract_views(soup: BeautifulSoup) -> str:
    views_div = soup.find("div", class_=re.compile(r"\bviews-\w+"))
    if not views_div:
        return ""

    for icon_span in views_div.find_all("span", attrs={"aria-hidden": "true"}):
        icon_span.decompose()

    views_raw = views_div.get_text(strip=True)
    return clean_number(views_raw)


def extract_tags(soup: BeautifulSoup) -> str:
    tag_section = soup.find("section", class_=re.compile(r"\btags-\w+"))
    tags = []

    if tag_section:
        tag_spans = tag_section.find_all("span", class_=re.compile(r"\btag-text-\w+"))
        tags = [s.get_text(strip=True) for s in tag_spans if s.get_text(strip=True)]

    # Fallback: links /scripts/<tag>/ em regiões de tags.
    if not tags:
        for a in soup.find_all("a", href=re.compile(r"/scripts/[^/]+/?")):
            txt = a.get_text(" ", strip=True)
            if txt and len(txt) <= 60 and txt not in tags:
                tags.append(txt)

    return " | ".join(tags)


def enrich_from_inner(record: dict, session) -> dict:
    url = normalize_url(record.get("url", ""))
    record["url"] = url

    if not url:
        record["_status"] = "sem_url"
        return record

    try:
        status, html, from_cache = fetch_html(session, url, prefix="inner", timeout=25)
        record["_status"] = str(status)

        if status in STOP_ON_STATUS:
            record["_status"] = f"stop_{status}"
            return record

        if status != 200 or not html:
            return record

        soup = BeautifulSoup(html, "lxml")

        views = extract_views(soup)
        if views:
            record["views"] = views

        tags = extract_tags(soup)
        if tags:
            record["tags"] = tags

        record["Script"] = detect_script_access(soup)
        record["_cache_inner"] = "1" if from_cache else "0"

    except requests.exceptions.Timeout:
        record["_status"] = "timeout"
    except requests.exceptions.ConnectionError:
        record["_status"] = "conn_error"
    except Exception as e:
        record["_status"] = f"erro: {str(e)[:60]}"

    return record


# ══════════════════════════════════════════════════════════════════════════════
#  CHECKPOINT INTERNO
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


def load_existing_output() -> list:
    """Carrega saída já gerada para dar continuidade sem perder dados anteriores."""
    if not LOAD_EXISTING_OUTPUT:
        return []

    if os.path.exists(OUTPUT_JSON):
        try:
            with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                print(f"[CONTINUIDADE] Carregado {len(data)} registros de {OUTPUT_JSON}")
                return data
        except Exception as e:
            print(f"[AVISO] Não consegui carregar {OUTPUT_JSON}: {str(e)[:80]}")

    if os.path.exists(OUTPUT_CSV):
        try:
            with open(OUTPUT_CSV, "r", encoding="utf-8-sig", newline="") as f:
                data = list(csv.DictReader(f))
            print(f"[CONTINUIDADE] Carregado {len(data)} registros de {OUTPUT_CSV}")
            return data
        except Exception as e:
            print(f"[AVISO] Não consegui carregar {OUTPUT_CSV}: {str(e)[:80]}")

    return []


def backup_existing_outputs_once():
    """Cria backup timestampado dos outputs antes de sobrescrever com a versão mesclada."""
    if not BACKUP_EXISTING_OUTPUT:
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for path in [OUTPUT_CSV, OUTPUT_JSON]:
        if os.path.exists(path):
            base, ext = os.path.splitext(path)
            backup = f"{base}_backup_{stamp}{ext}"
            try:
                with open(path, "rb") as src, open(backup, "wb") as dst:
                    dst.write(src.read())
                print(f"[BACKUP] {backup}")
            except Exception as e:
                print(f"[AVISO] Falha ao criar backup de {path}: {str(e)[:80]}")


def is_record_enriched(record: dict) -> bool:
    """Evita refazer página interna quando já existem dados úteis."""
    if not SKIP_ALREADY_ENRICHED:
        return False
    if record.get("views"):
        return True
    if record.get("tags"):
        return True
    if record.get("Script") and record.get("Script") != "unknown":
        return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

def ordered_fieldnames(records: list) -> list:
    preferred = [
        "script_id", "titulo", "url", "autor", "url_autor", "data_atualizacao",
        "boosts", "comentarios", "views", "tags", "Script",
        "query_source",
        "_status", "_cache_inner",
    ]
    all_keys = []
    for r in records:
        for k in r.keys():
            if k not in all_keys:
                all_keys.append(k)
    return [k for k in preferred if k in all_keys] + [k for k in all_keys if k not in preferred]


def save_csv(records: list, path: str):
    if not records:
        return
    records = sanitize_records(records)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=ordered_fieldnames(records), quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(records)
    print(f"[SALVO] {path}  ({len(records)} linhas)")


def save_json(records: list, path: str):
    records = sanitize_records(records)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"[SALVO] {path}")


def print_coverage(records: list):
    total = len(records)
    print("\n── Cobertura dos campos ──")
    for field in ["views", "tags", "Script", "boosts", "comentarios", "data_atualizacao", "query_source"]:
        filled = sum(1 for r in records if r.get(field) and r.get(field) != "unknown")
        pct = filled / total * 100 if total else 0
        print(f"  {field:20}: {filled:5}/{total}  ({pct:.0f}%)")

    print("\n── Script access ──")
    counts = {}
    for r in records:
        val = r.get("Script") or "unknown"
        counts[val] = counts.get(val, 0) + 1
    for k in ["open_source", "protected", "invite_only", "unknown"]:
        print(f"  {k:20}: {counts.get(k, 0):5}")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    records = []
    records.extend(load_existing_output())
    if records:
        records = merge_records(records)
        backup_existing_outputs_once()

    if MODE not in {"local", "online", "both"}:
        print("MODE inválido. Use: local, online ou both.")
        sys.exit(1)

    # Compatibilidade v3: se passar HTMLs por argumento e MODE for local/both, usa args.
    # Caso contrário, usa HTML_FILES + descoberta automática de .htm/.html na pasta atual.
    if len(sys.argv) > 1 and MODE in {"local", "both"}:
        html_paths = sys.argv[1:]
    else:
        html_paths = get_local_html_files(HTML_FILES)

    if MODE in {"local", "both"}:
        print(f"[LOCAL] Arquivos HTML configurados/encontrados: {len(html_paths)}")
        for hp in html_paths:
            print(f"        - {hp}")
        records.extend(parse_all_listings(html_paths))

    if MODE in {"online", "both"}:
        if not HAS_REQUESTS:
            print("[ONLINE] Instale requests: pip install requests")
        else:
            session = requests.Session()
            session.headers.update(HEADERS)

            if RUN_TIERS_SEQUENTIALLY:
                for idx, tier in enumerate(TIERS_SEQUENCE, start=1):
                    tier_keywords = get_keywords_for_tiers([tier])
                    print(f"\n========== INICIANDO TIER {tier} ({idx}/{len(TIERS_SEQUENCE)}) ==========")
                    discovered = discover_from_keywords(
                        session,
                        keywords=tier_keywords,
                        tier_label=f"tier={tier}",
                    )
                    records.extend(discovered)
                    records = merge_records(records)
                    save_csv(records, OUTPUT_CSV)
                    save_json(records, OUTPUT_JSON)
                    print(f"========== TIER {tier} FINALIZADO | total único acumulado: {len(records)} ==========")

                    if idx < len(TIERS_SEQUENCE):
                        print(f"[PAUSA ENTRE TIERS] {PAUSE_BETWEEN_TIERS_SECONDS/60:.0f} min antes do próximo tier...")
                        time.sleep(PAUSE_BETWEEN_TIERS_SECONDS)
            else:
                records.extend(discover_from_keywords(session))

    records = merge_records(records)

    if MAX_SCRIPTS:
        records = records[:MAX_SCRIPTS]

    total = len(records)
    if total == 0:
        print("Nenhum card encontrado. Verifique arquivos locais, MODE ou keywords.")
        sys.exit(1)

    print(f"\n[TOTAL] {total} scripts únicos antes da FASE interna.\n")

    if not FETCH_INNER:
        print("[FASE INTERNA] Pulada (FETCH_INNER=False).")
    elif not HAS_REQUESTS:
        print("[FASE INTERNA] Instale requests: pip install requests")
    else:
        saved, done = load_checkpoint(total)
        if saved:
            records = saved
        else:
            done = 0

        session = requests.Session()
        session.headers.update(HEADERS)

        remaining = max(0, total - done)
        planned_inner = remaining if MAX_INNER_REQUESTS_PER_RUN is None else min(remaining, MAX_INNER_REQUESTS_PER_RUN)
        est_min = planned_inner * (DELAY_INNER_MIN + DELAY_INNER_MAX) / 2 / 60
        est_max = planned_inner * DELAY_INNER_MAX / 60
        print(f"[FASE INTERNA] {total} páginas | retomando em {done + 1}")
        print(f"               delay {DELAY_INNER_MIN}–{DELAY_INNER_MAX}s")
        print(f"               limite/rodada={MAX_INNER_REQUESTS_PER_RUN}")
        print(f"               estimativa desta rodada: {est_min:.0f}–{est_max:.0f} min\n")

        inner_requests = 0
        for i in range(done, total):
            if MAX_INNER_REQUESTS_PER_RUN is not None and inner_requests >= MAX_INNER_REQUESTS_PER_RUN:
                save_checkpoint(records, i)
                save_csv(records, OUTPUT_CSV)
                save_json(records, OUTPUT_JSON)
                print(f"[LIMITE] MAX_INNER_REQUESTS_PER_RUN atingido. Rode novamente para continuar do item {i + 1}.")
                break

            rec = records[i]
            if is_record_enriched(rec):
                print(f"  [{i+1:5}/{total}] SKIP já enriquecido: {rec.get('titulo', '?')[:60]}")
                continue

            print(f"  [{i+1:5}/{total}] {rec.get('titulo', '?')[:70]}")
            records[i] = enrich_from_inner(rec, session)
            r = records[i]
            inner_requests += 1

            print(
                f"           status={r.get('_status', '')}  "
                f"views={r.get('views') or '—'}  "
                f"Script={r.get('Script') or 'unknown'}  "
                f"tags={r.get('tags', '')[:45] if r.get('tags') else '—'}"
            )

            if str(r.get("_status", "")).replace("stop_", "") in {str(s) for s in STOP_ON_STATUS}:
                save_checkpoint(records, i)
                print("[PARADA] 403/429 detectado. Interrompendo para evitar bloqueio/rate limit.")
                break

            # Salva checkpoint e CSV parcial a cada 25 itens.
            if (i + 1) % 25 == 0:
                save_checkpoint(records, i + 1)
                save_csv(records, OUTPUT_CSV)
                save_json(records, OUTPUT_JSON)
                print(f"  ── checkpoint {i+1}/{total} ──\n")

            if r.get("_cache_inner") != "1":
                
                sleep_random(DELAY_INNER_MIN, DELAY_INNER_MAX)

        else:
            # Terminou tudo com sucesso.
            if os.path.exists(CHECKPOINT_FILE):
                os.remove(CHECKPOINT_FILE)

    save_csv(records, OUTPUT_CSV)
    save_json(records, OUTPUT_JSON)
    print_coverage(records)


if __name__ == "__main__":
    main()
