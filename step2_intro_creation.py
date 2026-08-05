# -*- coding: utf-8 -*-
"""
step2_intro_creation.py
========================
④-2 紹介文・ポイント作成(OpenAI API / Web検索あり)
step1_info_extraction() の抽出結果をもとに、紹介文とおすすめポイントを生成する。

main.py からは以下のように呼び出す:

    from step2_intro_creation import step2_intro_creation
    result = step2_intro_creation(step1_result)
"""

import json
import os

from openai import OpenAI

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

OPENAI_MODEL = "gpt-4.1"

openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


# ---------------------------------------------------------------------------
# ④-2 紹介文・ポイント作成(OpenAI API / Web検索あり)
# ---------------------------------------------------------------------------

def step2_intro_creation(step1_result: dict) -> dict:
    """
    ④-1の抽出結果(step1_result)をもとに、紹介文3本・おすすめポイント3点・
    紹介URLをOpenAI API(Web検索あり)で生成する。

    Parameters
    ----------
    step1_result : dict
        step1_info_extraction() の抽出結果

    Returns
    -------
    dict
        生成結果。JSON解析に失敗した場合は
        {"error": "JSON解析失敗", "raw": "<レスポンス原文>"} を返す。
    """
    prompt = f"""あなたは飲食・レジャー業界に精通したプロのコピーライターです。
以下は、あるビアガーデンについて整理された情報です。この内容と、必要に応じたWeb検索の結果をもとに、紹介文とおすすめポイントを作成してください。

■作成項目
・紹介文1、紹介文2、紹介文3：このビアガーデンの魅力を伝える紹介文を3つ作成してください。それぞれ1〜2文程度、来場を後押しするような親しみやすい文体で。
・おすすめポイント1、おすすめポイント2、おすすめポイント3：このビアガーデンならではの特徴・強みを、簡潔な見出し風の一言(15〜20文字程度)で3つ作成してください。
・ビア紹介URL：このビアガーデンの紹介ページとして最適なURLがWeb検索で見つかれば記載してください。

■条件
・整理された情報に記載がない、紹介文作成に必要な情報がある場合は、Web検索で公式サイト等から補完してください
・検索しても情報が見つからない場合は、整理された情報のみで作成してください（情報が少ない旨の断り書きは不要です。分かる範囲で必ずJSONを埋めてください）
・出力はJSON形式のみ。前置き・謝罪文・説明文・「以下、JSON形式で出力します」等の一切の付随テキストを含めないこと。1文字目から必ず「{{」で始めてください

{{
  "紹介文1": "",
  "紹介文2": "",
  "紹介文3": "",
  "おすすめポイント1": "",
  "おすすめポイント2": "",
  "おすすめポイント3": "",
  "ビア紹介URL": ""
}}

#整理された情報
{json.dumps(step1_result, ensure_ascii=False, indent=2)}
"""

    response = openai_client.responses.create(
        model=OPENAI_MODEL,
        tools=[{"type": "web_search"}],
        input=prompt
    )

    response_text = response.output_text.strip()

    if response_text.startswith("```"):
        response_text = response_text.split("```")[1]
        if response_text.startswith("json"):
            response_text = response_text[4:]
        response_text = response_text.strip()

    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    # 前置き文章("申し訳ありません…"等)が付いてJSON部分だけを直接パースできない場合、
    # 文中の最初の "{" から最後の "}" までを抽出して再度パースを試みる
    start = response_text.find("{")
    end = response_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = response_text[start:end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    return {"error": "JSON解析失敗", "raw": response_text}
