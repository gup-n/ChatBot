"""RAG 离线评估：检索召回与回答关键事实覆盖率。"""

import json
import re
from collections.abc import Callable
from pathlib import Path


def load_questions(path: str | Path) -> list[dict]:
    """读取 JSON 数组或 JSONL 题集，并做最小字段校验。"""
    file_path = Path(path)
    raw = file_path.read_text(encoding="utf-8")
    if file_path.suffix.lower() == ".jsonl":
        questions = [json.loads(line) for line in raw.splitlines() if line.strip()]
    else:
        questions = json.loads(raw)
    if not isinstance(questions, list):
        raise ValueError("题集必须是 JSON 数组或 JSONL 文件")
    for index, question in enumerate(questions, 1):
        if not isinstance(question, dict) or not question.get("question"):
            raise ValueError(f"第 {index} 题缺少 question")
        if not question.get("expected_sources"):
            raise ValueError(f"第 {index} 题缺少 expected_sources")
        if not question.get("answer_keywords"):
            raise ValueError(f"第 {index} 题缺少 answer_keywords")
    return questions


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def evaluate_dataset(
    questions: list[dict],
    retrieve: Callable[[str, int], list[dict]],
    answer: Callable[[str, list[dict]], str] | None = None,
    top_k: int = 6,
) -> dict:
    """评估题集；answer 为空时仅计算检索指标。"""
    results = []
    for item in questions:
        hits = retrieve(item["question"], top_k)
        sources = [str(hit.get("source", "")) for hit in hits]
        expected_sources = item["expected_sources"]
        recalled = bool(set(sources) & set(expected_sources))
        result = {
            "id": item.get("id", ""),
            "question": item["question"],
            "expected_sources": expected_sources,
            "retrieved_sources": sources,
            "retrieval_hit": recalled,
        }
        if answer is not None:
            response = answer(item["question"], hits)
            keywords = item["answer_keywords"]
            normalized = _normalize(response)
            matched = [keyword for keyword in keywords if _normalize(keyword) in normalized]
            coverage = len(matched) / len(keywords)
            threshold = float(item.get("minimum_keyword_coverage", 1.0))
            result.update({
                "answer": response,
                "answer_keywords": keywords,
                "matched_keywords": matched,
                "answer_keyword_coverage": coverage,
                "answer_pass": coverage >= threshold,
            })
        results.append(result)

    total = len(results)
    summary = {
        "question_count": total,
        "top_k": top_k,
        "retrieval_recall_at_k": sum(item["retrieval_hit"] for item in results) / total if total else 0.0,
    }
    if answer is not None:
        summary["answer_keyword_coverage"] = sum(
            item["answer_keyword_coverage"] for item in results
        ) / total if total else 0.0
        summary["answer_pass_rate"] = sum(item["answer_pass"] for item in results) / total if total else 0.0
    return {"summary": summary, "results": results}


def write_markdown_report(report: dict, path: str | Path) -> None:
    """生成便于人工复核的 Markdown 报告。"""
    summary = report["summary"]
    lines = [
        "# RAG 评估报告", "",
        f"- 题目数：{summary['question_count']}",
        f"- 检索召回率@{summary['top_k']}：{summary['retrieval_recall_at_k']:.1%}",
    ]
    if "answer_keyword_coverage" in summary:
        lines.extend([
            f"- 回答关键事实覆盖率：{summary['answer_keyword_coverage']:.1%}",
            f"- 回答通过率：{summary['answer_pass_rate']:.1%}",
        ])
    lines.extend(["", "## 未通过或需人工复核", ""])
    for item in report["results"]:
        if not item["retrieval_hit"] or ("answer_pass" in item and not item["answer_pass"]):
            lines.extend([
                f"### {item.get('id', '')} {item['question']}",
                f"- 期望来源：{', '.join(item['expected_sources'])}",
                f"- 实际来源：{', '.join(item['retrieved_sources']) or '无'}",
            ])
            if "answer" in item:
                lines.extend([
                    f"- 关键事实：{', '.join(item['answer_keywords'])}",
                    f"- 命中事实：{', '.join(item['matched_keywords']) or '无'}",
                    f"- 系统回答：{item['answer']}",
                ])
            lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")
