# -*- coding: utf-8 -*-
"""
result_storage.py
==========
各ステップの処理結果をログとして保存する処理と、
最終的な結果(Excel転記用)をJSONで保存する処理をまとめたモジュール。

main.py からは以下のように呼び出す:

    from result_storage import save_step_log, save_consolidated_result
"""

import json
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

LOG_DIR = Path("/var/www/beerinfo/logs")
RESULT_DIR = Path("/var/www/beerinfo/results")
LOG_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# ログ・結果ファイル出力
# ---------------------------------------------------------------------------

def save_step_log(id, step_name, content):
    """各ステップの結果をファイルに出力(デバッグ・確認用)"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = LOG_DIR / f"{id}_{step_name}_{timestamp}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        if isinstance(content, (dict, list)):
            f.write(json.dumps(content, ensure_ascii=False, indent=2))
        else:
            f.write(str(content))
    return str(filename)


def _combine_beer_type_and_venue(step1_result):
    """ビアタイプと開催場所(収容人数)を「ビアタイプ / 開催場所(収容人数)」形式で結合する。
    Excelテンプレート側に開催場所(収容人数)専用のセルが無いため、ビアタイプの
    セル(B22)にまとめて書き込む方針(2026年08月合意)。どちらか一方しか値が
    無い場合は " / " を付けず、単独の値のみを返す。"""
    beer_type = (step1_result.get("ビアタイプ", "") or "").strip()
    venue = (step1_result.get("開催場所(収容人数)", "") or "").strip()

    if beer_type and venue:
        return f"{beer_type} / {venue}"
    return beer_type or venue


def build_consolidated_dict(id, name, url1, step1_result, step2_result):
    """AIが整理・作成した情報を、Excelセルマッピングに沿ったキー名でdict化する"""
    return {
        "管理番号": id,
        "ビア名称": name,
        "公式URL": url1,
        "ビア紹介URL": step2_result.get("ビア紹介URL", ""),
        "紹介１": step2_result.get("紹介文1", ""),
        "紹介２": step2_result.get("紹介文2", ""),
        "紹介３": step2_result.get("紹介文3", ""),
        "開催期間": step1_result.get("開催期間", ""),
        "営業時間": step1_result.get("営業時間", ""),
        "定休日": step1_result.get("定休日", ""),
        "雨天営業": step1_result.get("雨天営業", ""),
        "ビアタイプ": _combine_beer_type_and_venue(step1_result),
        "概要": step1_result.get("概要", ""),
        "システム": step1_result.get("システム", ""),
        "料金(税込)": step1_result.get("料金(税込)", ""),
        "料理情報": step1_result.get("料理内容", ""),
        "ドリンク": step1_result.get("ドリンク内容", ""),
        "ポイント１": step2_result.get("おすすめポイント1", ""),
        "ポイント２": step2_result.get("おすすめポイント2", ""),
        "ポイント３": step2_result.get("おすすめポイント3", ""),
    }


def save_consolidated_result(id, name, url1, step1_result, step2_result):
    """統合済みdictを作成し、管理番号別のJSONファイルとして保存する。
    戻り値は統合済みdict自身(Excel書き込み側でそのまま再利用できるようにするため)。"""
    consolidated = build_consolidated_dict(id, name, url1, step1_result, step2_result)

    filename = RESULT_DIR / f"{id}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(consolidated, f, ensure_ascii=False, indent=2)

    return consolidated
