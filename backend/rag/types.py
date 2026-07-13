"""RAG 管道共用的数据格式。"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RetrievalHit:
    """一次向量检索的标准结果。"""

    content: str
    source: str
    distance: float
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "source": self.source,
            "distance": round(self.distance, 4),
            "metadata": self.metadata,
        }
