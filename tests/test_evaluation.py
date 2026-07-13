from pathlib import Path

from backend.evaluation import evaluate_dataset, load_questions


def test_evaluation_calculates_retrieval_and_answer_metrics():
    questions = [{
        "id": "q1", "question": "测试问题", "expected_sources": ["source.txt"],
        "answer_keywords": ["答案A", "答案B"], "minimum_keyword_coverage": 0.5,
    }]

    report = evaluate_dataset(
        questions,
        retrieve=lambda _query, _top_k: [{"source": "source.txt", "content": "上下文"}],
        answer=lambda _question, _hits: "答案A",
    )

    assert report["summary"]["retrieval_recall_at_k"] == 1.0
    assert report["summary"]["answer_keyword_coverage"] == 0.5
    assert report["summary"]["answer_pass_rate"] == 1.0


def test_baseline_question_set_has_a_maintainable_number_of_grounded_questions():
    dataset = Path(__file__).resolve().parents[1] / "evaluation" / "questions.json"
    questions = load_questions(dataset)

    assert 50 <= len(questions) <= 100
    assert all(item["reference_answer"] for item in questions)
