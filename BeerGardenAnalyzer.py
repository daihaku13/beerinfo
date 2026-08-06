import csv
import sys
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# OCR機能(現状未使用・呼び出し箇所はコメントアウト中)は
# pytesseract/PIL が未インストールでも本体が起動できるようガードする
try:
    import pytesseract
    from PIL import Image
    from io import BytesIO
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False


# ============================================================
# キーワード定義（他スクリプトからも import して使えるようモジュールレベルに配置）
# ============================================================
# カテゴリキーワード(日本語+英語表記)。全カテゴリ共通でサブキーワードは同一のため、
# カテゴリごとの表記バリエーションのみをここで管理する。
#
# 判定の考え方(すべて年号(2026等)確認が前提。年号が無ければ問答無用で×):
#   △ … 年号 + カテゴリキーワード(サブキーワード不問)
#   〇 … 年号 + カテゴリキーワード + サブキーワード1個以上
#         ※カテゴリを問わない汎用キーワード"BEER"単体の場合は、
#           サブキーワード1個以上とのセットで〇とする(単体では×)
#   ◎ … 年号 + カテゴリキーワード + サブキーワード2個以上
CATEGORIES = {
    "ビアガーデン": ["ビアガーデン", "BEERGARDEN", "BEER GARDEN"],
    "ビアホール": ["ビアホール", "BEERHALL", "BEER HALL"],
    # 「BEER TRERRACE」はタイプミスのため「BEER TERRACE」に修正済み
    "ビアテラス": ["ビアテラス", "BEER TERRACE"],
    "バーベキュー": ["バーベキュー", "BBQ"],
}

# 全カテゴリ共通のサブキーワード(◎/〇判定の補強語)
SUB_KEYWORDS = [
    "飲み放題", "フリードリンク", "フリーフロー", "食べ放題", "食べ飲み放題",
    "開催期間", "料金", "コース", "プラン", "屋上", "テラス", "オープン",
    "生ビール", "夏の風物詩", "今年も開催", "期間限定", "ご予約",
]

# 〇判定でのみ使う、カテゴリ名を伴わない汎用キーワード("BEER"単体)
GENERIC_WEAK_KEYWORD = "BEER"

# リンク抽出等、キーワード全体を使う処理向け(全カテゴリのキーワードをまとめたもの)
KEYWORDS = list(dict.fromkeys(
    kw for kws in CATEGORIES.values() for kw in kws
))

YEAR_KEYWORDS = [
    "2026",
    "令和8",
    "2026年",
    "2026年開催",
    "2026ビアガーデン",
]


# ============================================================
# CSVLoader
# ============================================================
def load_csv(file_path):
    items = []
    print("[LOG] CSV読み込み開始:", file_path)

    try:
        with open(file_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row.get("ID") or not row.get("URL"):
                    print("[LOG] CSV行スキップ（ID/URL欠損）:", row)
                    continue
                items.append({
                    "id": row["ID"],
                    "name": row.get("ビアガーデン名称", ""),
                    "url": row["URL"]
                })
    except Exception as e:
        print("[ERROR] CSV読み込み失敗:", e)
        return []

    print(f"[LOG] CSV読み込み完了: {len(items)}件")
    return items


# ============================================================
# URLFetcher
# ============================================================
def fetch_html(url):
    print("[LOG] HTML取得:", url)
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            print("[LOG] HTML取得失敗（ステータス）:", resp.status_code)
            return None
        print("[LOG] HTML取得成功")
        return resp.text
    except Exception as e:
        print("[ERROR] HTML取得例外:", e)
        return None


# ============================================================
# HTMLParser
# ============================================================
def extract_text(html):
    print("[LOG] HTML解析開始")
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join([line for line in lines if line])

    print("[LOG] HTML解析完了（テキスト抽出）")
    return text


# ============================================================
# KeywordDetector（テキスト）
# ============================================================
def contains_keywords(text, keywords):
    print("[LOG] テキストキーワード判定開始")
    lower_text = text.lower()
    for kw in keywords:
        if kw.lower() in lower_text:
            print("[LOG] テキストキーワードヒット:", kw)
            return True
    print("[LOG] テキストキーワード非ヒット")
    return False


# ============================================================
# LinkExtractor
# ============================================================
def extract_links(html, base_url, keywords):
    print("[LOG] リンク抽出開始")
    soup = BeautifulSoup(html, "html.parser")
    links = []

    for a in soup.find_all("a"):
        text = (a.get_text() or "").strip()
        href = a.get("href")
        if not href:
            continue

        if any(kw.lower() in text.lower() for kw in keywords):
            full_url = urljoin(base_url, href)
            print("[LOG] リンクキーワードヒット:", full_url)
            links.append(full_url)

    print("[LOG] リンク抽出完了:", len(links), "件")
    return links


# ============================================================
# ImageExtractor
# ============================================================
def extract_image_urls(html, base_url):
    print("[LOG] 画像URL抽出開始")
    soup = BeautifulSoup(html, "html.parser")
    urls = []

    for img in soup.find_all("img"):
        src = img.get("src")
        if not src:
            continue
        full_url = urljoin(base_url, src)
        if full_url.lower().endswith((".png", ".jpg", ".jpeg")):
            urls.append(full_url)

    print("[LOG] 画像抽出完了:", len(urls), "枚")
    return urls


# ============================================================
# ImageOCR（Linux向け本実装／pytesseract・PIL未インストール時は無効化）
# ============================================================
def ocr_image(image_url, keywords):
    if not OCR_AVAILABLE:
        print("[WARN] OCR機能は無効です（pytesseract/PIL未インストール）:", image_url)
        return False

    print("[LOG] OCR解析開始:", image_url)
    try:
        resp = requests.get(image_url, timeout=10)
        if resp.status_code != 200:
            print("[LOG] OCR画像取得失敗:", resp.status_code)
            return False

        img = Image.open(BytesIO(resp.content))
        text = pytesseract.image_to_string(img, lang="jpn+eng")

        lower_text = text.lower()
        for kw in keywords:
            if kw.lower() in lower_text:
                print("[LOG] OCRキーワードヒット:", kw)
                return True

        print("[LOG] OCRキーワード非ヒット")
        return False

    except Exception as e:
        print("[ERROR] OCR例外:", e)
        return False


# ============================================================
# YearValidator
# ============================================================
def is_this_year(text, year_keywords):
    print("[LOG] 今年度判定開始")
    lower_text = text.lower()
    for kw in year_keywords:
        if kw.lower() in lower_text:
            print("[LOG] 今年度キーワードヒット:", kw)
            return True
    print("[LOG] 今年度キーワード非ヒット")
    return False


# ============================================================
# 確度判定ロジック
# ============================================================
def _count_hits(lower_text, words):
    return sum(1 for w in words if w.lower() in lower_text)


def keyword_hit_score(text):
    """カテゴリキーワード・サブキーワード・汎用キーワード("BEER")のヒット数の
    合計を返す。同一id・同一名称に複数URLが存在する場合、このスコアが高い順に
    URL1・URL2として採用するための指標として使う。"""
    lower_text = text.lower()
    all_category_keywords = [kw for kws in CATEGORIES.values() for kw in kws]
    score = _count_hits(lower_text, all_category_keywords)
    score += _count_hits(lower_text, SUB_KEYWORDS)
    if GENERIC_WEAK_KEYWORD.lower() in lower_text:
        score += 1
    return score


def judge_rank(text, year_confirmed):
    """
    text: 判定対象テキスト(本文)。年号自体の確認は年号がサブページのみに
          存在するケースがあるため、呼び出し元(analyze_url)で本文＋サブページを
          踏まえて判定した year_confirmed を外部から受け取る。

    判定順序(年号未確認の場合は問答無用で×):
      ◎ … カテゴリキーワード + サブキーワード2個以上
      〇 … カテゴリキーワード + サブキーワード1個以上
           または 汎用キーワード"BEER"単体 + サブキーワード1個以上
      △ … カテゴリキーワードのみ(サブキーワード不問)
      × … 上記いずれにも該当しない(年号未確認の場合も含む)
    """
    print("[LOG] 確度判定開始")

    if not year_confirmed:
        print("[LOG] 確度: × （年号未確認）")
        return "×"

    lower_text = text.lower()
    all_category_keywords = [kw for kws in CATEGORIES.values() for kw in kws]
    cat_hit = _count_hits(lower_text, all_category_keywords) > 0
    generic_hit = GENERIC_WEAK_KEYWORD.lower() in lower_text
    sub_hit_count = _count_hits(lower_text, SUB_KEYWORDS)

    if cat_hit:
        if sub_hit_count >= 2:
            print(f"[LOG] 確度: ◎ （サブキーワード{sub_hit_count}個ヒット）")
            return "◎"
        if sub_hit_count >= 1:
            print(f"[LOG] 確度: 〇 （サブキーワード{sub_hit_count}個ヒット）")
            return "〇"
        print("[LOG] 確度: △ （カテゴリキーワードのみ）")
        return "△"

    if generic_hit and sub_hit_count >= 1:
        print(f"[LOG] 確度: 〇 （汎用キーワード: BEER + サブキーワード{sub_hit_count}個）")
        return "〇"

    print("[LOG] 確度: ×")
    return "×"


# ============================================================
# メイン処理：単一URL解析
# ============================================================
def analyze_url(url, keywords, year_keywords):
    print("\n==============================")
    print("[LOG] URL解析開始:", url)
    print("==============================")

    html = fetch_html(url)
    if html is None:
        print("[LOG] HTML取得失敗 → ×")
        return [], "×", {}

    text = extract_text(html)
    # 入力URL自体のヒット数スコアも記録しておく(url1候補としての優先順位付けに使う)
    url_scores = {url: keyword_hit_score(text)}

    # 本文自体に年号があるかどうか(サブページとは別に判定)
    year_hit_in_text = is_this_year(text, year_keywords)

    candidate_urls = extract_links(html, url, keywords)

    confirmed_urls = []
    year_hit = False

    for link in candidate_urls:
        sub_html = fetch_html(link)
        if sub_html is None:
            continue

        sub_text = extract_text(sub_html)
        if is_this_year(sub_text, year_keywords):
            confirmed_urls.append(link)
            url_scores[link] = keyword_hit_score(sub_text)
            year_hit = True

    # 年号は「本文自体」か「サブページ」のどちらかで確認できればOK
    year_confirmed = year_hit or year_hit_in_text

    # カテゴリキーワード・サブキーワードの判定は本文(text)に対して行う
    rank = judge_rank(text, year_confirmed)

    print("[LOG] URL解析完了:", url)
    print("[LOG] 確定URL:", confirmed_urls)
    print("[LOG] URL別ヒット数スコア:", url_scores)
    print("[LOG] 確度:", rank)

    return confirmed_urls, rank, url_scores


# ============================================================
# 複数URL処理（CSV対応）
# ============================================================
def analyze_items(items, keywords, year_keywords, log_path="/home/junzi/beer_log.txt"):
    print("[LOG] 全URL解析開始")

    log = open(log_path, "w", encoding="utf-8")

    results = []

    for item in items:
        confirmed, rank, url_scores = analyze_url(item["url"], keywords, year_keywords)

        # --- ×以外を1行でログに書く ---
        if rank != "×":
            # confirmed_urls が複数ある場合は最初の1件だけ使う
            first_confirm = confirmed[0] if confirmed else ""
            log.write(f"{rank} {item['id']} {item['name']} {item['url']} {first_confirm}\n")

        # 結果をリストにも保存
        results.append({
            "id": item["id"],
            "name": item["name"],
            "input_url": item["url"],
            "confirmed_urls": confirmed,
            "rank": rank,
            "url_scores": url_scores,
        })

    log.close()
    print("[LOG] 全URL解析完了（ログ書き込み済）")

    return results


# ============================================================
# ResultExporter（先頭に確度マーク）
# ============================================================
def export_results(results, mode="list", csv_path="beer_result.csv", log_path="/home/xymon/server/www/beer_result.log"):
    print("[LOG] 結果出力開始")

    log = open(log_path, "w", encoding="utf-8")

    if mode == "list":
        for r in results:

            if r["rank"] != "×":
                log.write(f"{r['rank']} ID:{r['id']} 名称:{r['name']} URL:{r['input_url']}\n")
                for u in r["confirmed_urls"]:
                    log.write(f"  - {u}\n")
                log.write("-" * 40 + "\n")

            print(f"{r['rank']} ID: {r['id']}")
            print("名称:", r["name"])
            print("入力URL:", r["input_url"])
            print("確度:", r["rank"])
            print("確定URL一覧:")
            for u in r["confirmed_urls"]:
                print("  -", u)
            print("-" * 40)

    elif mode == "csv":
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["確度", "ID", "名称", "入力URL", "確定URL"])
            for r in results:
                if r["confirmed_urls"]:
                    for u in r["confirmed_urls"]:
                        writer.writerow([r["rank"], r["id"], r["name"], r["input_url"], u])
                else:
                    writer.writerow([r["rank"], r["id"], r["name"], r["input_url"], ""])

                if r["rank"] != "×":
                    log.write(f"{r['rank']} ID:{r['id']} 名称:{r['name']} URL:{r['input_url']}\n")
                    for u in r["confirmed_urls"]:
                        log.write(f"  - {u}\n")
                    log.write("-" * 40 + "\n")

    log.close()
    print("[LOG] 結果出力完了（ログ書き込み済）")


# ============================================================
# 実行例
# ============================================================
if __name__ == "__main__":

    if len(sys.argv) < 2:
        print("[ERROR] 使い方: python3 BeerGardenAnalyzer.py <CHKURL.txtのパス>")
        sys.exit(1)

    input_csv_path = sys.argv[1]

    items = load_csv(input_csv_path)

    if not items:
        print("[ERROR] 有効なデータが0件のため処理を中断します:", input_csv_path)
        sys.exit(1)

    results = analyze_items(items, KEYWORDS, YEAR_KEYWORDS)

    export_results(results, mode="list")
