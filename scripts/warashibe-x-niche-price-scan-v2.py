#!/usr/bin/env python3
"""わらしべ穴場価格スキャン: Yahoo!オークション公開検索のみ (no login, no purchase).

Read-only scraper. No credentials, no cart, no listing.
同期先: ~/.hermes/scripts/warashibe-x-niche-price-scan-v2.py (両者を同一内容で保つ)
"""
from __future__ import annotations

import json
import re
import statistics
import subprocess
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
LIMIT = 8
TIMEOUT = 45
OUT_DIR = Path.home() / ".hermes" / "warashibe" / "price-scans"

# Xで話題になりやすい穴場カテゴリ
CATEGORY_POOL: dict[str, list[str]] = {
    "gpu": ["RTX 5060 グラボ", "RTX 4060 単体", "RTX 4070 グラボ",
            "RX 7600 グラボ", "RTX 3060 グラボ", "RTX 5070 グラボ"],
    "gunpla": ["MG エピオン", "プレバン ガンプラ", "ブラックナイトスコード ガンプラ",
               "RG サザビー", "MGEX ユニコーン", "ガンプラ 完成品"],
    "pokeka": ["ポケカ SAR", "ニンフィアex SAR", "ブラッキーex SAR",
               "ポケカ スタートデッキ", "レックウザVMAX", "ポケカ 未開封 ボックス"],
    "lefty_iron": ["左利き アイアン ゴルフ", "レフティ アイアン XXIO",
                   "左利き ゴルフ クラブ セット", "レフティ ゼクシオ", "左利き用 はさみ"],
    "niche": ["カグラバチ カード", "メタキラカード", "左利き マウス",
              "左利き 包丁", "ベイブレード 限定", "プレバン 限定"],
}
CATEGORY_ORDER = ["gpu", "gunpla", "pokeka", "lefty_iron", "niche"]
CAT_LABEL = {"gpu": "GPU/グラボ", "gunpla": "ガンプラ", "pokeka": "ポケカ",
             "lefty_iron": "左利き/レフティ", "niche": "穴場その他"}


def pick_keywords(now: datetime) -> list[tuple[str, str]]:
    """既存スクリプトと同じ日次回転ロジックを維持。"""
    day_index = int(now.strftime("%Y%m%d"))
    hour_bucket = now.hour // 12
    seed = day_index * 2 + hour_bucket
    picks: list[tuple[str, str]] = []
    for offset, cat in enumerate(CATEGORY_ORDER):
        pool = CATEGORY_POOL[cat]
        picks.append((cat, pool[(seed + offset) % len(pool)]))
    return picks[:5]  # 全5カテゴリを毎回カバー（穴場 sparingly が出る穴を埋める）


def fetch(url: str) -> str:
    try:
        proc = subprocess.run(
            ["curl", "-s", "-A", UA, url, "--max-time", str(TIMEOUT)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        return proc.stdout or ""
    except Exception:
        return ""


# Yahoo!公開検索は1商品=1 <a> に data-auction-title / data-auction-price を
# 同一タグ内に持つ。Vision/DOM構造ではなくこの属性ペアで確実にペアリングする。
ITEM_RE = re.compile(
    r'data-auction-title="(?P<title>[^"]*)"[^>]*?data-auction-price="(?P<price>\d+)"',
    re.S,
)
ITEM_RE_REV = re.compile(
    r'data-auction-price="(?P<price>\d+)"[^>]*?data-auction-title="(?P<title>[^"]*)"',
    re.S,
)
TAG_RE = re.compile(r"<[^>]+>")


def clean(s: str) -> str:
    s = TAG_RE.sub("", s)
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"\s+", " ", s).strip()


def _unescape(s: str) -> str:
    return (
        s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        .replace("&quot;", '"').replace("&#39;", "'")
    )


def parse_yahoo(html: str) -> list[tuple[str, int]]:
    """(タイトル, 現在値) ペアを抽出。属性ペアなのでずれゼロ。"""
    pairs: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for rx in (ITEM_RE, ITEM_RE_REV):
        for m in rx.finditer(html):
            title = _unescape(m.group("title")).strip()
            price = int(m.group("price"))
            if not title or price <= 0:
                continue
            key = (title, price)
            if key in seen:
                continue
            seen.add(key)
            pairs.append((title, price))
    return pairs[:LIMIT]


def summarize(items: list[tuple[str, int]]) -> dict:
    # 端数的に小さい値は「本体失利せりではなく出品枠/\tstart1円」の可能性。
    # メイン商品の相場 判断には使わず集計から除外する。
    real = [(t, p) for t, p in items if p >= 300]
    prices = [p for _, p in real if p > 0]
    return {
        "count": len(prices),
        "min": min(prices) if prices else None,
        "median": int(statistics.median(prices)) if prices else None,
        "max": max(prices) if prices else None,
        "samples": [f"{t} / ¥{p:,}" for t, p in real[:3]],
    }


def yen(v) -> str:
    return f"¥{v:,}" if isinstance(v, int) else "—"


def main() -> int:
    now = datetime.now(JST)
    picks = pick_keywords(now)
    results = []

    for cat, kw in picks:
        from urllib.parse import quote_plus
        url = ("https://auctions.yahoo.co.jp/search/search?p="
               + quote_plus(kw) + "&va=" + quote_plus(kw)
               + "&b=1&n=50&s1=new&o1=d")
        html = fetch(url)
        items = parse_yahoo(html) if html else []
        entry = {"category": cat, "label": CAT_LABEL[cat], "keyword": kw,
                 "url": url, "bytes": len(html)}
        entry.update(summarize(items))
        results.append(entry)
        time.sleep(1.5)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    raw = OUT_DIR / f"scan-{stamp}.json"
    raw.write_text(json.dumps(
        {"retrieved_at": now.isoformat(), "source": "yahoo_auction_public_search",
         "picks": [{"category": c, "keyword": k} for c, k in picks],
         "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"🛒 わらしべ穴場価格スキャン {now:%Y-%m-%d %H:%M} JST",
        "公開相場のみ / 購入・ログイン・出品なし",
        f"保存: {raw}",
        "",
        "対象: GPU・ガンプラ・ポケカ・左利きアイアン/用品・その他穴場",
        "",
    ]
    any_hit = False
    for r in results:
        if r["count"]:
            any_hit = True
        lines.append(f"### {r['label']}: `{r['keyword']}`")
        lines.append(f"- 件数 {r['count']} / 最安 {yen(r['min'])} / "
                     f"中央 {yen(r['median'])} / 最高 {yen(r['max'])}")
        for s in r["samples"]:
            lines.append(f"  - {s}")
        if not r["count"]:
            lines.append("  - (0件: セレクタ/JS描画・在庫薄の可能性)")
        lines.append("")

    lines += [
        "はくあメモ:",
        "- ポケカ/ガンプラは相場透明化→価値誤認出品と箱傷限定が穴場",
        "- GPU中古は1万円超で故障リスク大。型番+動作確認を必須に",
        "- 左利きアイアン(XXIO/ゼクシオZF)は供給薄・競合少なめ、回転は遅め",
        "- 仕入れ判断は古物商ルール・規約順守",
        "",
        "出典: ヤフオク!公開検索(現在値の「円」表現から抽出)",
    ]
    print("\n".join(lines))
    return 0 if any_hit else 1


if __name__ == "__main__":
    sys.exit(main())