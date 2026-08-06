# -*- coding: utf-8 -*-
"""
step2_intro_creation.py
========================
④-2 紹介文・ポイント作成(Claude API / Web検索あり)
step1_info_extraction() の抽出結果をもとに、紹介文とおすすめポイントを生成する。

main.py からは以下のように呼び出す:

    from step2_intro_creation import step2_intro_creation
    result = step2_intro_creation(step1_result)
"""

import json
import os

import anthropic

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

CLAUDE_MODEL = "claude-sonnet-4-6"

# API呼び出しが長時間ハングしないよう明示的にタイムアウトを設定(秒)
# (Web検索ツールを使う分、step1より応答が長引きやすいため少し余裕を持たせる)
REQUEST_TIMEOUT = 90

# SDKのデフォルト自動リトライが積み重なると「90秒のはずが数分かかる」原因に
# なるため、リトライ回数を明示的に絞る(step1_info_extraction.pyと同じ方針)
MAX_RETRIES = 1

MAX_TOKENS = 4096

claude_client = anthropic.Anthropic(
    api_key=os.environ.get("ANTHROPIC_API_KEY"),
    timeout=REQUEST_TIMEOUT,
    max_retries=MAX_RETRIES,
)


# ---------------------------------------------------------------------------
# ④-2 紹介文・ポイント作成(Claude API / Web検索あり)
# ---------------------------------------------------------------------------

def step2_intro_creation(step1_result: dict) -> dict:
    """
    ④-1の抽出結果(step1_result)をもとに、紹介文3本・おすすめポイント3点を
    Claude API(Web検索あり)で生成する。

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
  "おすすめポイント3": ""
}}

#整理された情報
{json.dumps(step1_result, ensure_ascii=False, indent=2)}
"""

    try:
        response = claude_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
            timeout=REQUEST_TIMEOUT,  # クライアント初期化時の設定に加え、呼び出し単位でも明示
        )
    except anthropic.APITimeoutError:
        return {"error": "タイムアウト", "message": f"Claude APIの応答が{REQUEST_TIMEOUT}秒以内に得られませんでした"}
    except anthropic.APIConnectionError as e:
        return {"error": "接続エラー", "message": str(e)}
    except anthropic.APIStatusError as e:
        return {"error": "APIエラー", "message": f"status={e.status_code}: {e.message}"}
    except Exception as e:
        # 上記3種以外の予期しない例外(SDK内部エラー等)もここで確実に捕捉し、
        # main.py側のstream()ジェネレータ全体が停止するのを防ぐ
        return {"error": "予期しないエラー", "message": str(e)}

    # response.content は text ブロックと server_tool_use / web_search_tool_result
    # ブロックが混在しうるため、text ブロックのみを連結する
    response_text = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()

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
