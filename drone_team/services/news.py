# drone_team/services/news.py
from pathlib import Path
import csv, re, requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Any

HEADERS = ["id","url","title","summary","image_url","added_by","added_at"]

def _data_dir(app) -> Path:
    base = Path(app.config.get("DATA_DIR", app.instance_path)) / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base

def articles_csv(app) -> Path:
    p = _data_dir(app) / "news_articles.csv"
    if not p.exists():
        with p.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(HEADERS)
    return p

def list_articles(app) -> List[Dict[str, Any]]:
    p = articles_csv(app)
    out: List[Dict[str, Any]] = []
    with p.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            out.append(row)
    # newest first
    out.sort(key=lambda x: x.get("added_at",""), reverse=True)
    return out

def _clean_text(s: str) -> str:
    if not s: return ""
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _pick_meta(soup: BeautifulSoup, names) -> str:
    # names can be ["og:title", "twitter:title", "title", ...]
    for name in names:
        if name.startswith("og:") or name.startswith("twitter:"):
            el = soup.find("meta", property=name) or soup.find("meta", attrs={"name":name})
            if el and el.get("content"):
                return el["content"]
        elif name == "title":
            if soup.title and soup.title.string:
                return soup.title.string
        else:
            el = soup.find("meta", attrs={"name":name})
            if el and el.get("content"):
                return el["content"]
    return ""

def _absolutize(url: str) -> str:
    return url  # keep as-is; we store the absolute URL the admin provides

def _fetch_metadata(url: str) -> Dict[str, str]:
    # very small, robust fetcher: GET with UA + timeout
    resp = requests.get(url, timeout=8, headers={
        "User-Agent": "Mozilla/5.0 (compatible; drone_teamNewsBot/1.0)"
    }, allow_redirects=True)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    title = _pick_meta(soup, ["og:title","twitter:title","title"])
    desc  = _pick_meta(soup, ["og:description","twitter:description","description"])
    img   = _pick_meta(soup, ["og:image","twitter:image"])
    return {
        "title": _clean_text(title) or url,
        "summary": _clean_text(desc),
        "image_url": img or "",
    }

def add_article_by_url(app, url: str, added_by: str) -> Dict[str, Any]:
    # basic allowlist for scheme
    if not re.match(r"^https?://", url, flags=re.I):
        raise ValueError("URL must start with http:// or https://")

    meta = _fetch_metadata(url)
    row = {
        "id": datetime.utcnow().strftime("%Y%m%d%H%M%S%f"),
        "url": _absolutize(url),
        "title": meta["title"],
        "summary": meta["summary"],
        "image_url": meta["image_url"],
        "added_by": added_by or "admin",
        "added_at": datetime.utcnow().isoformat(timespec="seconds"),
    }
    p = articles_csv(app)
    with p.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADERS)
        w.writerow(row)
    return row

def delete_article(app, article_id: str) -> bool:
    """Remove a row with id=article_id from the CSV. Returns True if deleted."""
    p = articles_csv(app)
    rows: List[Dict[str, Any]] = []
    deleted = False
    with p.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            if row.get("id") == article_id:
                deleted = True
                continue
            rows.append(row)
    if deleted:
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=HEADERS)
            w.writeheader()
            for row in rows:
                w.writerow(row)
    return deleted
