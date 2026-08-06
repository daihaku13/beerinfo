# -*- coding: utf-8 -*-
"""
step0_fetch_and_clean.py
================
③ Webサイト情報取得・クリーニング処理
CSVからの対象一覧読み込みと、指定URLの本文取得・ノイズ除去を行う。

main.py からは以下のように呼び出す:

    from step0_fetch_and_clean import load_csv, extract_main_text
"""

import csv
import re
from io import BytesIO

import requests
from bs4 import BeautifulSoup

# 画像OCR・PDFテキスト抽出は追加の外部ライブラリに依存するため、
# 未インストール環境でも本体(HTML取得・クリーニング)は動作できるようガードする。
# 必要パッケージ: pip install pytesseract pillow pdfplumber
#                + サーバー側にtesseract-ocr・tesseract-ocr-jpn(aptパッケージ)
try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

CSV_PATH = "/var/www/8888/beer-create.csv"

# 404/500エラーページやBot対策で弾かれるサイトが多いため、汎用的なブラウザの
# UAを明示しておく(デフォルトのpython-requests/x.x UAだと403で弾かれることがある)
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

SKIP_DOMAINS = ('x.com', 'twitter.com', 'facebook.com', 'fb.com', 'instagram.com')

BOILERPLATE_LINES = {
    'お問い合わせはこちら',
    'お問い合わせ',
    '当店でご利用いただける',
    '電子決済のご案内',
    '電子決済',
    '当店でご利用いただける電子決済のご案内',
    '下記よりお選びいただけます。',
    '詳細はこちら',
    '詳細を見る',
    '詳細',
    'SCROLL DOWN',
    '前へ',
    '次へ',
    '写真はイメージです',
    '。',
    '[email protected]',
    '詳しく見る',
    'RESERVE',
    '予約する',
}

INSTAGRAM_FEED_MARKERS = ('さらに読み込む', 'Instagram でフォロー', 'Follow Me')

JSON_KEY_LABELS = {
    'regular_open': '営業時間',
    'regular_closed': '定休日',
    'tel_number': '電話番号',
    'telephone': '電話番号',
    'address': '所在地',
    'base': '料金',
}

# ①本文が短く「情報が少ない」とみなす閾値・スキャン対象の絞り込み設定
LOW_CONTENT_THRESHOLD = 500  # この文字数未満なら画像・PDFスキャンを追加実施
MAX_IMAGES_TO_SCAN = 3        # OCR対象にする画像の最大枚数(上位N枚のみ、負荷対策)
MAX_PDFS_TO_SCAN = 2          # テキスト抽出対象にするPDFの最大件数
OCR_LANG = "jpn+eng"


# ---------------------------------------------------------------------------
# ③ クリーニング処理
# ---------------------------------------------------------------------------

def should_skip_url(url):
    if not url:
        return False
    return any(domain in url for domain in SKIP_DOMAINS)


def remove_hashtags(text):
    """#で始まるハッシュタグの並び行を除去"""
    lines = text.split('\n')
    result = []
    for line in lines:
        if re.fullmatch(r'(#\S+\s*)+', line.strip()):
            continue
        result.append(line)
    return '\n'.join(result)


def remove_boilerplate(text):
    """どのサイトにも出る定型的な案内文・ボタンラベルを除去"""
    lines = text.split('\n')
    return '\n'.join(line for line in lines if line.strip() not in BOILERPLATE_LINES)


def remove_currency_language_menu(text):
    """Language/Currency見出し直後の選択メニュー羅列を除去"""
    lines = text.split('\n')
    result = []
    skip_mode = False
    skip_count = 0
    for line in lines:
        stripped = line.strip()
        if stripped in ('Language', 'Currency'):
            skip_mode = True
            skip_count = 0
            continue
        if skip_mode:
            skip_count += 1
            if len(stripped) <= 20 and skip_count <= 80:
                continue
            else:
                skip_mode = False
        result.append(line)
    return '\n'.join(result)


def remove_html_attr_residue(text):
    """<img alt="...">などのHTML属性の残骸を除去"""
    return re.sub(r'"\s*alt\s*=\s*"[^"]*"\s*>?', '', text)


def remove_instagram_feed(text):
    """Instagram投稿一覧の見出しが見つかったら、そこから末尾までを除去"""
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if line.strip() in INSTAGRAM_FEED_MARKERS:
            return '\n'.join(lines[:i])
    return text


def remove_zero_width_chars(text):
    """幅ゼロ文字(制御文字)を除去"""
    return re.sub(r'[\u200B-\u200F\u202A-\u202E\uFEFF]+', '', text)


def dedupe_exact_blocks(text, block_marker_start='drinks', block_marker_end='set', min_block_lines=3):
    """block_marker_start〜block_marker_end間の完全一致ブロックが複数回出た場合、2回目以降を省略。

    注意: block_marker_start/endは特定サイト(英語UIの飲み放題メニュー等)向けの
    マーカーであり、他サイトの本文中に偶然 "drinks" や "set" が単独行として
    出現した場合、無関係な内容を誤って重複ブロックとみなすリスクがある。
    誤爆を減らすため、ブロック行数がmin_block_lines未満の短いブロックは
    重複除去の対象外とする。
    """
    lines = text.split('\n')
    blocks = []
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == block_marker_start:
            block_lines = [line]
            j = i + 1
            while j < len(lines) and lines[j].strip() != block_marker_end:
                block_lines.append(lines[j])
                j += 1
            block_text = '\n'.join(block_lines)
            if len(block_lines) < min_block_lines:
                result.extend(block_lines)
            elif block_text in blocks:
                result.append('（飲み放題内容は共通のため省略。詳細は初出箇所を参照）')
            else:
                blocks.append(block_text)
                result.extend(block_lines)
            i = j
        else:
            result.append(line)
            i += 1
    return '\n'.join(result)


def remove_emoji(text):
    """絵文字・記号ピクトグラムを除去"""
    emoji_pattern = re.compile(
        "["
        "\U0001F300-\U0001FAFF"
        "\U00002600-\U000027BF"
        "\U0001F1E6-\U0001F1FF"
        "\U0000FE0F"
        "\U0000200D"
        "]+", flags=re.UNICODE
    )
    return emoji_pattern.sub('', text)


def merge_vertical_text(text):
    """1文字だけのアルファベット行が連続している場合は結合する(縦書きテキスト対策)
    数字は対象外(カレンダー日付との誤結合を防ぐため)"""
    lines = text.split('\n')
    result = []
    buffer = []
    for line in lines:
        stripped = line.strip()
        if len(stripped) == 1 and stripped.isalpha():
            buffer.append(stripped)
        else:
            if buffer:
                result.append(''.join(buffer))
                buffer = []
            result.append(line)
    if buffer:
        result.append(''.join(buffer))
    return '\n'.join(result)


def remove_calendar_numbers(text):
    """カレンダーの日付セル(1〜2桁の数字だけの行)を除去"""
    lines = text.split('\n')
    return '\n'.join(line for line in lines if not re.fullmatch(r'\d{1,2}', line.strip()))


def remove_image_paths(text):
    """jpg/png/gif/jpeg/webp画像への参照(URL・相対パス問わず)を除去"""
    pattern = r'(https?:)?//\S+\.(jpg|jpeg|png|gif|webp)(\?\S*)?'
    text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    pattern2 = r'\S*/[\w\-]+\.(jpg|jpeg|png|gif|webp)(\?\S*)?'
    text = re.sub(pattern2, '', text, flags=re.IGNORECASE)
    return text


def remove_urls(text):
    """http(s)://で始まるURLを除去"""
    return re.sub(r'https?://\S+', '', text)


def extract_json_useful_fields(text):
    """JSON内の営業時間・定休日・電話番号・住所・料金などの値を読みやすい形で抜き出す"""
    extracted = []
    for key, label in JSON_KEY_LABELS.items():
        pattern = rf'"{key}"\s*:\s*"([^"]*)"'
        matches = re.findall(pattern, text)
        for m in matches:
            value = m.replace('\\r\\n', ' ').replace('\\n', ' ').strip()
            if value:
                extracted.append(f"【{label}】{value}")
    return extracted


def remove_json_blocks(text):
    """JSON形式の行を検出して除去(1行がJSON構造で始まる場合など)"""
    lines = text.split('\n')
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('{') or stripped.startswith('['):
            colon_count = stripped.count('":')
            if colon_count >= 3:
                continue
        result.append(line)
    return '\n'.join(result)


def remove_english_heavy_lines(text, ratio_threshold=0.5, min_len=20):
    """20文字以上で半角英字比率が高い行を除去(コード片・メールアドレス対策)"""
    lines = text.split('\n')
    result = []
    for line in lines:
        stripped = line.strip()
        if len(stripped) >= min_len:
            ascii_letters = sum(1 for c in stripped if c.isascii() and c.isalpha())
            ratio = ascii_letters / len(stripped)
            if ratio >= ratio_threshold:
                continue
        result.append(line)
    return '\n'.join(result)


# ---------------------------------------------------------------------------
# ①情報が少ない場合の補完: 画像OCR・PDFテキスト抽出
# ---------------------------------------------------------------------------

def extract_image_urls(html, base_url):
    """ページ内の画像URL(jpg/png/gif/webp)を抽出する。並び順は出現順。"""
    from urllib.parse import urljoin
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    for img in soup.find_all("img"):
        src = img.get("src")
        if not src:
            continue
        full_url = urljoin(base_url, src)
        if full_url.lower().split("?")[0].endswith((".png", ".jpg", ".jpeg", ".webp")):
            urls.append(full_url)
    return urls


def extract_pdf_urls(html, base_url):
    """ページ内のPDFリンク(<a href="...pdf">)を抽出する。並び順は出現順。"""
    from urllib.parse import urljoin
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    for a in soup.find_all("a"):
        href = a.get("href")
        if not href:
            continue
        if href.lower().split("?")[0].endswith(".pdf"):
            urls.append(urljoin(base_url, href))
    return urls


def ocr_image_text(image_url):
    """画像URLを取得し、tesseractでOCRしてテキストを返す(失敗時は空文字)。"""
    if not OCR_AVAILABLE:
        print("[WARN] OCR機能は無効です(pytesseract/PIL未インストール):", image_url)
        return ""
    try:
        resp = requests.get(image_url, timeout=10, headers=REQUEST_HEADERS)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content))
        return pytesseract.image_to_string(img, lang=OCR_LANG).strip()
    except Exception as e:
        print("[WARN] 画像OCR失敗:", image_url, e)
        return ""


def extract_pdf_text(pdf_url):
    """PDF URLを取得し、pdfplumberでテキストを抽出して返す(失敗時は空文字)。
    注意: スキャン画像だけのPDF(文字レイヤーが無いもの)からはテキストが
    取れないため、その場合は空文字のままになる(OCR化は今回のスコープ外)。"""
    if not PDF_AVAILABLE:
        print("[WARN] PDF抽出機能は無効です(pdfplumber未インストール):", pdf_url)
        return ""
    try:
        resp = requests.get(pdf_url, timeout=15, headers=REQUEST_HEADERS)
        resp.raise_for_status()
        texts = []
        with pdfplumber.open(BytesIO(resp.content)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    texts.append(page_text)
        return "\n".join(texts).strip()
    except Exception as e:
        print("[WARN] PDFテキスト抽出失敗:", pdf_url, e)
        return ""


def scan_images_and_pdfs(html, base_url):
    """情報が少ない場合の補完用: 上位MAX_IMAGES_TO_SCAN枚の画像OCR結果と
    上位MAX_PDFS_TO_SCAN件のPDFテキストをまとめて返す(見つからなければ空文字)。"""
    sections = []

    image_urls = extract_image_urls(html, base_url)[:MAX_IMAGES_TO_SCAN]
    for image_url in image_urls:
        text = ocr_image_text(image_url)
        if text:
            sections.append(f"【画像OCR: {image_url}】\n{text}")

    pdf_urls = extract_pdf_urls(html, base_url)[:MAX_PDFS_TO_SCAN]
    for pdf_url in pdf_urls:
        text = extract_pdf_text(pdf_url)
        if text:
            sections.append(f"【PDF抽出: {pdf_url}】\n{text}")

    return "\n\n".join(sections)


def load_csv(csv_path: str = CSV_PATH) -> dict:
    """対象ビアガーデン一覧CSVを読み込み、idをキーとしたdictで返す。
    1行目はヘッダー行として読み飛ばす(beerinfo-create.html側の挙動と合わせるため)。"""
    data = {}
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i == 0:
                continue
            if not row:
                continue
            id = row[0]
            name = row[1] if len(row) > 1 else ""
            url1 = row[2] if len(row) > 2 else ""
            url2 = row[3] if len(row) > 3 else ""
            data[id] = {
                "id": id,
                "name": name,
                "url1": url1,
                "url2": url2
            }
    return data


def extract_main_text(url: str) -> str:
    """指定URLのページ本文を取得し、一連のクリーニング処理を適用して返す。

    取得失敗(タイムアウト・接続エラー・4xx/5xx等)時は例外をそのまま送出する。
    以前は例外をここで捕まえて "ERROR: ..." という文字列を返していたが、
    main.py側がこの文字列を正常な本文として扱いClaude APIに渡してしまうため、
    取得失敗が「情報が少ないだけ」に見えてしまう問題があった。
    呼び出し元(main.py)で捕捉し、そのIDの処理を明示的に失敗として扱う。
    """
    if not url:
        return ""

    if should_skip_url(url):
        return ""

    r = requests.get(url, timeout=10, headers=REQUEST_HEADERS)
    r.raise_for_status()

    # Content-Typeにcharset指定が無い日本語サイトで文字化けするのを防ぐため、
    # requestsの自動推定(apparent_encoding)で上書きする
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding

    soup = BeautifulSoup(r.text, "html.parser")

    for tag in soup(["header", "footer", "nav", "aside", "script", "style"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    text = "\n".join(lines)
    text = remove_hashtags(text)
    text = remove_boilerplate(text)
    text = remove_currency_language_menu(text)
    text = remove_html_attr_residue(text)
    text = remove_instagram_feed(text)
    text = remove_zero_width_chars(text)
    text = dedupe_exact_blocks(text)
    text = remove_emoji(text)
    text = merge_vertical_text(text)
    text = remove_calendar_numbers(text)
    text = remove_image_paths(text)
    text = remove_urls(text)

    json_fields = extract_json_useful_fields(text)
    text = remove_json_blocks(text)
    text = remove_english_heavy_lines(text)

    if json_fields:
        text = text + "\n" + "\n".join(json_fields)

    # ①本文が短く「情報が少ない」場合、画像OCR・PDFテキストで補完する
    if len(text) < LOW_CONTENT_THRESHOLD:
        print(f"[LOG] 本文が{LOW_CONTENT_THRESHOLD}文字未満({len(text)}文字)のため画像・PDFスキャンを実施:", url)
        supplement = scan_images_and_pdfs(r.text, url)
        if supplement:
            text = text + "\n\n" + supplement

    return text
