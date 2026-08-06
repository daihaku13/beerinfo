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
    ④-1の抽出結果(step1_result)をもとに、紹介文3本・おすすめポイント3点・
    紹介URLをClaude API(Web検索あり)で生成する。

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
    prompt = f"""あなたは飲食・レジャー業界に精通したプロのコピーライターです
以下のビアガーデン情報と、必要に応じて実施するWeb検索結果をもとに、事実に基づいた自然で読みやすい紹介文（3段落）とおすすめポイント3つを作成する
■目的
読者が「行ってみたい」と感じるように、情報は正確に、文章はやわらかく自然にまとめる
SNSや紹介記事にそのまま使えるよう、読みやすさと臨場感の両立を意識する
■紹介文作成ルール
・3段落構成・全体で350～450文字
・文体は、誇張なし・事実ベース・自然な日本語。ただし施設の魅力を伝える形容表現は積極的に使い、単なる箇条書きの言い換えにしない
・施設の特徴・立地・景観などは事実に基づき丁寧に記述する
・固有名詞は正確に記述し、施設名・イベント名は必ず正式名称を使用
・開催期間・曜日・特定日などは 事実に基づき正確に記述
・情報が不足している場合は、Web検索で公式情報を補完
・過度な宣伝表現は使わず、情報を積み上げるように構成
・情報が不足している場合は Web検索で公式情報を補完
・Web検索でも情報が得られない場合は、与えられた情報のみで構成（不足の断り書きは不要）
■段落構成（固定テンプレート）
・1段落目(開催概要)
　冒頭で立地・アクセス・建屋の特徴を具体的に描写し、次の形式に沿って締める：
　[立地・アクセス・建屋の特徴（例：JR博多駅から徒歩5分と抜群のアクセスを誇る）]「[施設名]」 の (屋上エリア/テラス席/庭園エリア) で行われる[ビアガーデン/ビアホール]イベント 「[ビアガーデン名称]」 は、[開催期間（記入例：2026年08月18日(火)から09月30日(水)）]までの[期間限定で開催されます。/特定日に開催されます。/年間を通して利用可能です。]
　※開催期間は入力情報に応じて変動
　※前置き句はアクセス情報に限らず、景観・雰囲気・建物の由来などを表す形容表現も使う
　※文末は開催形態に応じて言い回しを変える。特定日開催で開催回数がわかる場合は「の特定日に開催されます。（全〇回開催）」、終了時期が未確定な場合は「から夏季限定で開催されます。（終了時期は確認中！）」のように文末に括弧書きで補足する
・2段落目（特徴･魅力）
　-景観、料理、設備、スタイルなど 事実ベースの特徴を2～3点記述
　-主観表現は禁止（例：最高・魅力的・贅沢など）
　-「～が特徴ポイントです」「～が楽しめます」「～が格別」などの説明調で統一
・3段落目（利用シーン・補足）
　-利用シーン（友人・家族・カップルなど）を事実に基づき簡潔に記述
　-予約方法・通年営業・曜日限定などの補足情報を追加
　-締めの文は必ず以下のいずれかで終える：「いかがでしょうか。」「してみませんか。」「～が楽しめます。」「魅力的です。」「ポイントです。」
・おすすめポイント（1～3）：
　45〜55文字のアピール文を3つ作成する。このビアガーデンならではの特徴を事実ベースで記述。誇張表現は禁止（例：最高・圧倒的・極上など）
■条件
・整理された情報に不足があれば、Web検索で公式サイト等から補完する
・検索しても情報が見つからない場合は、整理情報のみで作成（断り書き不要）
・出力はJSON形式のみ。前置き・説明文・謝罪文は禁止
・1文字目から必ず「{{」で開始する
・「以下、JSON形式で出力します」などの付随テキストは一切禁止

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
