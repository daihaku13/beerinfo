from pathlib import Path
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
import csv
import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "beer-create.csv"

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CSV読み込み
def load_csv():
    data = {}
    with open(CSV_PATH, encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
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

@app.get("/beergarden")
async def beergarden():
    text = CSV_PATH.read_text(encoding="utf-8")
    return Response(content=text, media_type="text/csv")

# HTML取得＋不要部分除去
def extract_main_text(url):
    if not url:
        return ""

    try:
        r = requests.get(url, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")

        # 不要部分除去（シンプル版）
        for tag in soup(["header", "footer", "nav", "aside", "script", "style"]):
            tag.decompose()

        # 本文抽出
        text = soup.get_text(separator="\n")
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        return "\n".join(lines)

    except Exception as e:
        return f"ERROR: {e}"

@app.options("/execute")
async def execute_options():
    return Response(status_code=204)


@app.post("/execute")
async def execute(payload: dict):
    ids = payload.get("ids", []) if isinstance(payload, dict) else []
    csv_data = load_csv()

    results = []

    for id in ids:
        if id not in csv_data:
            results.append({
                "id": id,
                "status": "error",
                "reason": "ID not found in CSV"
            })
            continue

        item = csv_data[id]

        text1 = extract_main_text(item["url1"])
        text2 = extract_main_text(item["url2"]) if item["url2"] else ""

        ai_text = f"""
【名称】{item['name']}
【URL1本文】
{text1}

【URL2本文】
{text2}
"""

        results.append({
            "id": id,
            "name": item["name"],
            "url1": item["url1"],
            "url2": item["url2"],
            "ai_text": ai_text,
            "status": "ok"
        })

    return {"results": results}
