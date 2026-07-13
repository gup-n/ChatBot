from langchain_core.documents import Document

from backend.rag.lexical import search, tokenize


def test_lexical_search_prioritizes_exact_chinese_facts():
    documents = [
        Document(page_content="本科生每人限借图书20册，借期为30天。", metadata={"source": "图书馆.txt"}),
        Document(page_content="校园卡补办工本费为20元每张。", metadata={"source": "校园卡.txt"}),
    ]

    matches = search(documents, "本科生在图书馆最多能借多少册书？", limit=2)

    assert matches[0][0].metadata["source"] == "图书馆.txt"
    assert tokenize("本科生20册")
