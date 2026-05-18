"""验证模型 thinking block 是否真的在做推理.

用一道必须分步推理才能算对的题 (鸡兔同笼), 看每个模型的 thinking 长度 / 内容.
真思考的模型会在 thinking 里列方程或试算, 假思考的只会塞最终答案 (跟 text 几乎相同).

跑法:
    python app/tests/test_thinking_quality.py
"""

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from langchain_core.messages import HumanMessage

from app.agent.infra.llm_factory import _load_supported_models, get_chat_model


PROMPT = (
    "鸡兔同笼问题: 笼子里关着鸡和兔, 数头共 35 个, 数脚共 94 只. "
    "请问鸡和兔各有几只? 请仔细思考后再回答."
)


def extract(content) -> tuple[str, str]:
    """从 LangChain response.content 抽出 (thinking, text)."""
    if isinstance(content, str):
        return "", content
    if isinstance(content, list):
        thinking, text = "", ""
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "thinking":
                    thinking = b.get("thinking", "")
                elif b.get("type") == "text":
                    text = b.get("text", "")
        return thinking, text
    return "", str(content)


def main():
    models = _load_supported_models()
    print(f"prompt: {PROMPT}\n")

    rows = []
    for model in models:
        print("=" * 72)
        print(f"模型: {model}")
        print("=" * 72)
        try:
            llm = get_chat_model(model)
            response = llm.invoke([HumanMessage(PROMPT)])
        except Exception as e:
            print(f"  ❌ 失败: {type(e).__name__}: {e}")
            rows.append((model, "FAIL", 0, 0))
            continue

        thinking, text = extract(response.content)
        print(f"thinking ({len(thinking)} 字符):")
        if thinking:
            preview = thinking[:500].replace("\n", " ")
            tail = "…" if len(thinking) > 500 else ""
            print(f"  {preview}{tail}")
        else:
            print("  (无)")
        print(f"\ntext ({len(text)} 字符):")
        print(f"  {text[:300]}")
        print()
        rows.append((model, "OK", len(thinking), len(text)))

    print("\n" + "=" * 72)
    print("汇总: thinking 长度 vs text 长度")
    print("=" * 72)
    print(f"{'模型':38s} {'thinking':>10s} {'text':>10s} {'比值':>8s}  备注")
    print("-" * 72)
    for model, status, t, x in rows:
        if status == "FAIL":
            print(f"{model:38s}  FAIL")
            continue
        ratio = f"{t / x:.1f}x" if x else "n/a"
        if t < 50:
            note = "← 疑似假思考"
        elif t < x:
            note = "← thinking 比 text 还短, 可疑"
        else:
            note = ""
        print(f"{model:38s} {t:>10d} {x:>10d} {ratio:>8s}  {note}")

    print("\n判断标准: 真推理题里 thinking 应该有方程/试算/验证步骤, 长度通常 > text.")


if __name__ == "__main__":
    main()
