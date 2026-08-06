# -*- coding: utf-8 -*-
"""
main.py
=======
beerinfo-create.html から呼ばれるメイン処理(FastAPI)。
以下の順番で各モジュールを呼び出す。

    beerinfo-create.html
            ↓ POST /execute
         main.py
            ├─ step0_fetch_and_clean.py … ③ Webサイト取得・本文クリーニング
            ├─ step1_info_extraction.py … ④-1 情報整理(Claude API / Web検索なし)
            ├─ step2_intro_creation.py  … ④-2 紹介文作成(Claude API / Web検索あり)
            ├─ result_storage.py        … ログ・結果ファイル保存
            └─ step3_excel_writer.py    … ⑤ Excel書き込み(全件処理後にまとめて実行)

/execute はNDJSON(1行1JSON)でストリーミング応答する。各ステップが完了するたびに
1行ずつ進捗をレスポンスに書き出すため、beerinfo-create.html側で途中経過を
リアルタイムに表示できる。

■重要: ブロッキングI/Oのスレッド分離について
extract_main_text()(requests)・step1_info_extraction()(anthropic SDK)・
step2_intro_creation()(anthropic SDK)・write_to_excel()(openpyxl)は、いずれも
同期(ブロッキング)処理。async defの中で同期I/Oを直接呼ぶと、uvicornの
イベントループ全体がブロックされ、他のリクエストは一切さばけなくなる
(応答が届いていても後処理に進めず、見かけ上ハングしたようになる)。
これを避けるため、すべて asyncio.to_thread() で別スレッドに逃がして実行する。
"""

import asyncio
import json

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from step0_fetch_and_clean import load_csv, extract_main_text
from step1_info_extraction import step1_info_extraction
from step2_intro_creation import step2_intro_creation
from result_storage import save_step_log, save_consolidated_result
from step3_excel_writer import write_to_excel

app = FastAPI()

# ②step1_info_extraction()が返す11項目のうち、空欄(未取得)が
# この件数以上ある場合は情報が乏しいと判断し、④-2以降の処理を中止する
STEP1_REQUIRED_FIELDS = [
    "開催期間", "営業時間", "定休日", "雨天営業", "ビアタイプ", "概要",
    "システム", "開催場所(収容人数)", "料金(税込)", "料理内容", "ドリンク内容",
]
STEP1_ABORT_THRESHOLD = 5


def _count_missing_fields(step1_result: dict) -> int:
    """step1_result のうち、STEP1_REQUIRED_FIELDS で空欄(未取得)の項目数を返す"""
    return sum(1 for key in STEP1_REQUIRED_FIELDS if not (step1_result.get(key) or "").strip())


def _line(payload: dict) -> str:
    """NDJSONの1行分を生成する"""
    return json.dumps(payload, ensure_ascii=False) + "\n"


@app.post("/execute")
async def execute(payload: dict):
    ids = payload.get("ids", [])
    # beerinfo-create.html の「手動追加」枠から送られてくる、CSVに存在しない
    # 一時レコード（id・name・url1・url2）。存在すればcsv_dataへマージし、
    # 以降はCSV由来のレコードと同じ扱いで処理する。
    manual_items = payload.get("manual_items", [])

    async def stream():
        csv_data = load_csv()
        for m in manual_items:
            mid = m.get("id") or f"manual-{len(csv_data) + 1}"
            csv_data[mid] = {
                "id": mid,
                "name": m.get("name", ""),
                "url1": m.get("url1", ""),
                "url2": m.get("url2", ""),
            }
        consolidated_results = []

        for id in ids:
            item = csv_data.get(id)
            if not item:
                yield _line({"id": id, "step": "error", "status": "error", "message": "CSVに該当データがありません"})
                continue

            # 1件の処理中に予期しない例外(ネットワーク瞬断・SDK内部エラー等)が
            # 発生しても、そのIDだけ失敗として次のIDへ進めるようにする。
            # ここで捕捉しないと、stream()ジェネレータ全体が停止し、
            # 以降のIDが一切処理されなくなってしまうため。
            try:
                yield _line({"id": id, "step": "start", "status": "progress", "message": f"{item['name']} の処理を開始します"})

                # ③ Webサイト情報取得・クリーニング
                yield _line({"id": id, "step": "fetch", "status": "progress", "message": "Webサイト情報を取得中..."})
                # URL1は必須情報のため、取得失敗時はこのtry節を抜けて
                # 外側のexcept(このIDの処理全体を失敗扱い)に委ねる
                text1 = await asyncio.to_thread(extract_main_text, item["url1"])

                # URL2は任意項目のため、取得に失敗してもID全体は失敗にせず、
                # 空文字として扱って処理を続行する(警告ログのみ出す)
                text2 = ""
                if item["url2"]:
                    try:
                        text2 = await asyncio.to_thread(extract_main_text, item["url2"])
                    except Exception as e:
                        yield _line({"id": id, "step": "fetch", "status": "progress", "message": f"URL2の取得に失敗したためスキップします: {e}"})

                sections = []
                if text1:
                    sections.append(f"【URL1本文】\n{text1}")
                if text2:
                    sections.append(f"【URL2本文】\n{text2}")

                ai_text = f"【名称】{item['name']}\n" + "\n\n".join(sections)
                await asyncio.to_thread(save_step_log, id, "step0_ai_text", ai_text)
                yield _line({"id": id, "step": "fetch", "status": "done", "message": "Webサイト情報の取得が完了しました", "ai_text": ai_text})

                # ④-1 情報整理(Claude API / Web検索なし)
                yield _line({"id": id, "step": "step1", "status": "progress", "message": "Claude APIで情報整理中..."})
                step1_result = await asyncio.to_thread(step1_info_extraction, ai_text)
                await asyncio.to_thread(save_step_log, id, "step1_info", step1_result)
                yield _line({"id": id, "step": "step1", "status": "done", "message": "情報整理が完了しました", "result": step1_result})

                # ④-1が失敗している場合、そのまま④-2に渡すと誤ったデータで紹介文が
                # 生成されてしまうため、ここで処理を打ち切ってエラーとして扱う
                if isinstance(step1_result, dict) and step1_result.get("error"):
                    yield _line({
                        "id": id, "step": "step2", "status": "skipped",
                        "message": f"④-1でエラーが発生したため④-2をスキップしました: {step1_result.get('message', step1_result.get('error'))}"
                    })
                    yield _line({"id": id, "step": "complete", "status": "error", "message": f"{item['name']} の処理に失敗しました"})
                    continue

                # ②抽出11項目のうち一定数(STEP1_ABORT_THRESHOLD)以上が空欄の場合、
                # 情報が乏しすぎると判断し④-2以降をスキップする
                missing_count = _count_missing_fields(step1_result) if isinstance(step1_result, dict) else len(STEP1_REQUIRED_FIELDS)
                if missing_count >= STEP1_ABORT_THRESHOLD:
                    yield _line({
                        "id": id, "step": "step2", "status": "skipped",
                        "message": f"抽出項目{len(STEP1_REQUIRED_FIELDS)}件中{missing_count}件が空欄のため④-2をスキップしました"
                    })
                    yield _line({"id": id, "step": "complete", "status": "error", "message": f"{item['name']} は情報が不足しているため処理を中止しました"})
                    continue

                # ④-2 紹介文・ポイント作成(Claude API / Web検索あり)
                yield _line({"id": id, "step": "step2", "status": "progress", "message": "Claude APIで紹介文を作成中..."})
                step2_result = await asyncio.to_thread(step2_intro_creation, step1_result)
                await asyncio.to_thread(save_step_log, id, "step2_intro", step2_result)
                yield _line({"id": id, "step": "step2", "status": "done", "message": "紹介文の作成が完了しました", "result": step2_result})

                # ④-2が失敗している場合、空欄だらけのExcelシートができてしまうため、
                # ④-1と同様にここで処理を打ち切ってエラーとして扱う
                if isinstance(step2_result, dict) and step2_result.get("error"):
                    yield _line({
                        "id": id, "step": "complete", "status": "error",
                        "message": f"④-2でエラーが発生したため{item['name']} の処理に失敗しました: {step2_result.get('message', step2_result.get('error'))}"
                    })
                    continue

                # 管理番号別の最終結果ファイル(Excel転記用)。統合済みdictも受け取っておく
                consolidated = await asyncio.to_thread(
                    save_consolidated_result, id, item["name"], item["url1"], step1_result, step2_result
                )
                consolidated_results.append(consolidated)

                yield _line({"id": id, "step": "complete", "status": "ok", "message": f"{item['name']} の処理が完了しました"})

            except Exception as e:
                yield _line({"id": id, "step": "error", "status": "error", "message": f"予期しないエラーが発生したため{item['name']} の処理をスキップしました: {e}"})
                continue

        # ⑤ Excel書き込み(全件処理が終わった後にまとめて1回書き込む)
        if consolidated_results:
            yield _line({"step": "excel", "status": "progress", "message": "Excelファイルを作成中..."})
            try:
                excel_result = await asyncio.to_thread(write_to_excel, consolidated_results)
                message = "Excelファイルの作成が完了しました"
                if excel_result.get("onedrive_error"):
                    message += f"(OneDriveへのコピーに失敗: {excel_result['onedrive_error']})"
                elif excel_result.get("onedrive_path"):
                    message += "(OneDriveへコピー済み)"
                yield _line({
                    "step": "excel", "status": "done", "message": message,
                    "excel_path": excel_result.get("excel_path"),
                    "onedrive_path": excel_result.get("onedrive_path"),
                })
            except Exception as e:
                yield _line({"step": "excel", "status": "error", "message": f"Excelファイルの作成に失敗しました: {e}"})
        else:
            yield _line({"step": "excel", "status": "skipped", "message": "対象データが無いためExcel書き込みはスキップされました"})

    return StreamingResponse(stream(), media_type="application/x-ndjson")
