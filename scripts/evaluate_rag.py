"""运行 RAG 离线评估。

示例：
  uv run python scripts/evaluate_rag.py --retrieval-only
  uv run python scripts/evaluate_rag.py --output-dir reports/eval
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import Config
from backend.evaluation import evaluate_dataset, load_questions, write_markdown_report
from backend.rag.retrieval import search


def generate_answer(question: str, hits: list[dict]) -> str:
    """使用当前 LLM 针对已检索上下文回答，用于回答准确率评估。"""
    from langchain_core.messages import HumanMessage, SystemMessage
    from backend.models.llm import create_chat_model

    context = "\n\n".join(f"[来源: {item['source']}]\n{item['content']}" for item in hits)
    messages = [
        SystemMessage(content="根据给定知识库内容简洁回答。内容不足时明确说明未知，不要编造。"),
        HumanMessage(content=f"知识库内容：\n{context}\n\n问题：{question}"),
    ]
    response = create_chat_model().invoke(messages)
    return str(response.content)


def main() -> None:
    parser = argparse.ArgumentParser(description="评估 RAG 检索召回率与回答关键事实覆盖率")
    parser.add_argument("--dataset", default=str(PROJECT_ROOT / "evaluation" / "questions.json"))
    parser.add_argument("--top-k", type=int, default=Config.RETRIEVAL_TOP_K)
    parser.add_argument("--retrieval-only", action="store_true", help="仅评估检索，不调用 LLM")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "reports" / "evaluation"))
    args = parser.parse_args()

    questions = load_questions(args.dataset)
    report = evaluate_dataset(
        questions, retrieve=lambda query, top_k: search(query, top_k),
        answer=None if args.retrieval_only else generate_answer, top_k=args.top_k,
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown_report(report, output_dir / "report.md")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"报告已写入: {output_dir}")


if __name__ == "__main__":
    main()
