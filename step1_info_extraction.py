# -*- coding: utf-8 -*-
"""
④-1 情報整理(Claude API / Web検索なし)
=========================================
ビアガーデン／BBQ等イベント情報の本文(ai_text)から、指定項目のみを
Claude APIで抽出・整理するモジュール。

beeringo-api.py からは以下のように呼び出す:

    from step1_info_extraction import step1_info_extraction
    result = step1_info_extraction(ai_text)
"""

import json
import os

import anthropic

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

# 単純なJSON構造化抽出タスクのため、高速なHaikuモデルを使用(Sonnetより高速・低コスト)
CLAUDE_MODEL = "claude-haiku-4-5-20251001"

# ai_textが長すぎると処理時間が伸びるため上限を設ける(超過分は末尾を切り詰め)
MAX_AI_TEXT_CHARS = 12000

# API呼び出しが長時間ハングしないよう明示的にタイムアウトを設定(秒)
REQUEST_TIMEOUT = 60

# SDKのデフォルト自動リトライ(失敗のたびに最大60秒待ち直す)が積み重なると
# 「60秒のはずが数分かかる」原因になるため、リトライ回数を明示的に絞る
MAX_RETRIES = 1

claude_client = anthropic.Anthropic(
    api_key=os.environ.get("ANTHROPIC_API_KEY"),
    timeout=REQUEST_TIMEOUT,
    max_retries=MAX_RETRIES,
)


# ---------------------------------------------------------------------------
# ④-1 情報整理(Claude API / Web検索なし)
# ---------------------------------------------------------------------------

def step1_info_extraction(ai_text: str) -> dict:
    """
    ai_text(本文テキスト)を指定ルールに従って解析し、抽出結果をdictで返す。

    Parameters
    ----------
    ai_text : str
        解析対象の本文テキスト

    Returns
    -------
    dict
        抽出結果。JSON解析に失敗した場合は
        {"error": "JSON解析失敗", "raw": "<レスポンス原文>"} を返す。
    """
    if len(ai_text) > MAX_AI_TEXT_CHARS:
        ai_text = ai_text[:MAX_AI_TEXT_CHARS] + "\n（※文字数上限のため以降省略）"

    prompt = f"""あなたは情報整理と調査を得意とするビジネスアナリストです。
提供情報のみを使用して、指定項目を正確に抽出･整理してください。

■抽出する項目
抽出した情報を基に、以下の項目を正確に整理して一覧表にしてください。
・開催期間
・営業時間
・定休日
・雨天営業
・ビアタイプ
・概要
・システム
・開催場所(収容人数)
・料金
・料理内容
・ドリンク内容

■出力項目とフォーマット
以下の項目を表形式で提示してください
・開催期間：（記載例：2025年06月15日(日)～09月30日(火)）
・営業時間：（記載例：17:30～21:00(受付終了20:00/L.O.19:30)）
・定休日：（記載例：毎週火曜日(祝日および8/12は除く)、明記が無い場合は「記載なし」）
・雨天営業：（記載例：雨天中止/雨天時は屋内にて開催/記載なしなど原文に従う）
・概要：（記載例：[飲み放題]◎ [食べ放題]× [単品追加]〇)
　[飲み放題]すべてが飲み放題の場合◎、選択可能であれば〇(選択可)、[食べ放題]すべてのコースが食べ放題であれば◎、一部コースの場合は〇(一部コースのみ/一部料理のみ)
・システム：（記載例：食べ放題＆飲み放題(120分制、三種類のBBQセット(120分飲み放題付き))、ビュッフェ料理＋フリーフロー(90分)など概要レベル）
・開催場所(収容人数)：（屋上ビアガーデン(最大100名)、庭園ビアガーデン(80名収容)、リバーサイドビアガーデン、ビアテラス、ビアホール、BBQテラス）
・料金(税込)：税込価格を1人単位で記載。複数プランがある場合は「【プラン名】」で区切って記載。
・料理内容：（料理名を「、」で区切って列挙。複数プランがある場合は「【プラン名】」で明記。公式語句・掲載順を厳守)
・ドリンク内容：（ドリンク名称を「、」で区切って列挙。複数プランがある場合は「【プラン名】」で明記。公式語句・掲載順を厳守)

■記載ルール
・日付表記：「2025年06月15日(日)～09月30日(火)」形式に統一（月日共にゼロ埋め/曜日必須）
・時間表記：「L.O.」を明示（例：L.O.21:00）。受付終了時間が明記されていれば併記（例：受付終了19:00）
・カッコ表記：すべて半角()に統一
・料金表記：
　・税込の1人単位価格を記載（大人、中高生、小学生、幼児 等）
　・プラン名は「【プラン名/コース名】」、複数ある場合は「 / 」区切り
　・チャージ料・入場料などがあれば併記すること
・料理/ドリンク項目
　・公式サイトの語句・掲載順に従って忠実に記載
　・要約・意訳・箇条書きは禁止
　・料理・ドリンク名は「、」で区切る
　・複数プラン/コースが存在する場合は、プラン名/コース名は「【プラン名/コース名】」で表記し、プラン/コースは「 / 」区切って記載
　・大項目がある場合は「()」で囲み、「･」で区切ってください（記載例：お肉(牛肉･豚肉･鶏肉)、焼酎(芋･麦)、ワイン(赤･白)）
　・「日替わり」や「仕入れ状況」によって料理が変更になる場合はその旨を明記してください。

■注意点
・該当情報が確認できない場合は推測せず記載しないこと（該当項目は空文字""とすること）
・提供された本文に記載されている情報のみを使用する
・Web検索は行わない

■出力形式
・JSON形式のみで出力（前置き・説明文・コードブロック記号は不要）

{{
  "開催期間": "",
  "営業時間": "",
  "定休日": "",
  "雨天営業": "",
  "ビアタイプ": "",
  "概要": "",
  "システム": "",
  "開催場所(収容人数)": "",
  "料金(税込)": "",
  "料理内容": "",
  "ドリンク内容": ""
}}

#提供情報
{ai_text}
"""

    try:
        message = claude_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
            timeout=REQUEST_TIMEOUT,  # クライアント初期化時の設定に加え、呼び出し単位でも明示
        )
    except anthropic.APITimeoutError:
        return {"error": "タイムアウト", "message": f"Claude APIの応答が{REQUEST_TIMEOUT}秒以内に得られませんでした"}
    except anthropic.APIConnectionError as e:
        return {"error": "接続エラー", "message": str(e)}
    except anthropic.APIStatusError as e:
        return {"error": "APIエラー", "message": f"status={e.status_code}: {e.message}"}

    response_text = "".join(
        block.text for block in message.content if block.type == "text"
    ).strip()

    if response_text.startswith("```"):
        response_text = response_text.split("```")[1]
        if response_text.startswith("json"):
            response_text = response_text[4:]
        response_text = response_text.strip()

    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        return {"error": "JSON解析失敗", "raw": response_text}
