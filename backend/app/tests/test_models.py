"""模型烟测: 遍历 models.json 里所有模型, 调一次, 报告连通性 / content 格式 / thinking 支持.

跑法:
    python backend/app/tests/test_models.py

观察重点:
  1. 每个模型是否能调通 (Novita anthropic 协议)
  2. response.content 是 str 还是 list[block]
  3. 是否含 thinking block (reasoning 模型才有)
"""

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from langchain_core.messages import HumanMessage

from app.agent.infra.llm_factory import _load_supported_models, get_chat_model


PROMPT = "23 乘以 17 等于多少? 直接给答案, 不需要解释."


def describe_content(content) -> dict:
    """把 LangChain response.content 归纳成一份可打印的诊断信息."""
    if isinstance(content, str):
        return {
            "shape": "string",
            "blocks": ["text"],
            "thinking": "",
            "text": content,
        }
    if isinstance(content, list):
        blocks = []
        thinking_text = ""
        text_text = ""
        for b in content:
            if not isinstance(b, dict):
                blocks.append(type(b).__name__)
                continue
            t = b.get("type") or "?"
            blocks.append(t)
            if t == "thinking":
                thinking_text = b.get("thinking", "")
            elif t == "text":
                text_text = b.get("text", "")
        return {
            "shape": f"list[{len(blocks)}]",
            "blocks": blocks,
            "thinking": thinking_text,
            "text": text_text,
        }
    return {"shape": str(type(content)), "blocks": [], "thinking": "", "text": str(content)}


def test_model(model_name: str) -> dict:
    print(f"\n{'=' * 70}")
    print(f"模型: {model_name}")
    print("=" * 70)
    try:
        llm = get_chat_model(model_name)
        response = llm.invoke([HumanMessage(PROMPT)])
    except Exception as e:
        print(f"  ❌ 调用失败: {type(e).__name__}: {e}")
        return {"model": model_name, "ok": False, "error": f"{type(e).__name__}"}

    info = describe_content(response.content)
    print(f"  ✅ 调通")
    print(f"  content shape : {info['shape']}")
    print(f"  blocks        : {info['blocks']}")
    if info["thinking"]:
        print(f"  thinking ({len(info['thinking'])} 字符):")
        preview = info["thinking"][:200].replace("\n", " ")
        print(f"    {preview}{'…' if len(info['thinking']) > 200 else ''}")
    else:
        print("  thinking      : (无)")
    text_preview = info["text"][:200].replace("\n", " ")
    print(f"  text ({len(info['text'])} 字符): {text_preview!r}")
    return {
        "model": model_name,
        "ok": True,
        "shape": info["shape"],
        "blocks": info["blocks"],
        "has_thinking": bool(info["thinking"]),
    }


def main():
    models = _load_supported_models()
    print(f"将测试 {len(models)} 个模型, prompt: {PROMPT!r}")
    results = [test_model(m) for m in models]

    print(f"\n{'=' * 70}")
    print("汇总")
    print("=" * 70)
    print(f"{'模型':38s} {'状态':6s} {'shape':14s} {'thinking':10s} blocks")
    print("-" * 70)
    for r in results:
        if r["ok"]:
            print(
                f"{r['model']:38s} {'OK':6s} {r['shape']:14s} "
                f"{'✅' if r['has_thinking'] else '❌':10s} {r['blocks']}"
            )
        else:
            print(f"{r['model']:38s} {'FAIL':6s} {r['error']}")


if __name__ == "__main__":
    main()
