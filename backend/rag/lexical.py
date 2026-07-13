"""轻量 BM25 关键词检索，补足中文事实型问答的精确召回。"""

import math
import re

from langchain_core.documents import Document


def tokenize(text: str) -> list[str]:
    """中文按单字与双字片段、英文和数字按词切分。"""
    tokens: list[str] = []
    for part in re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+", text.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", part):
            tokens.extend(part)
            tokens.extend(part[index:index + 2] for index in range(len(part) - 1))
        else:
            tokens.append(part)
    return tokens


def search(documents: list[Document], query: str, limit: int) -> list[tuple[Document, float]]:
    """对已入库的文本块计算 BM25 分数并返回前 N 项。"""
    terms = tokenize(query)
    if not documents or not terms or limit < 1:
        return []

    tokenized = [tokenize(document.page_content) for document in documents]
    doc_count = len(documents)
    avg_length = sum(len(tokens) for tokens in tokenized) / doc_count or 1
    document_frequency: dict[str, int] = {}
    for tokens in tokenized:
        for term in set(tokens):
            document_frequency[term] = document_frequency.get(term, 0) + 1

    scores: list[tuple[Document, float]] = []
    for document, tokens in zip(documents, tokenized):
        frequencies: dict[str, int] = {}
        for term in tokens:
            frequencies[term] = frequencies.get(term, 0) + 1
        score = 0.0
        for term in set(terms):
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            idf = math.log(1 + (doc_count - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
            score += idf * frequency * 2.2 / (frequency + 1.2 * (1 - 0.75 + 0.75 * len(tokens) / avg_length))
        if score > 0:
            scores.append((document, score))
    return sorted(scores, key=lambda item: item[1], reverse=True)[:limit]
