from __future__ import annotations

import math
from collections import Counter

from ax_scanner.models import FileRecord, ParseStatus, TableProfile

from .models import SearchHit, SearchTableReference
from .normalization import char_ngram_tokens, normalize_text


class DocumentIndex:
    """Small in-memory char 2-3 gram BM25 index over masked scanner text."""

    def __init__(self, files: list[FileRecord], tables: list[TableProfile] | None = None):
        self.documents = [
            record for record in files if record.parse_status == ParseStatus.PARSED and record.text.strip()
        ]
        self.tables_by_file: dict[str, list[SearchTableReference]] = {}
        for table in tables or []:
            self.tables_by_file.setdefault(table.file_id, []).append(SearchTableReference(
                table_id=table.table_id,
                sheet_name=table.sheet_name,
                column_names=table.column_names,
            ))
        for references in self.tables_by_file.values():
            references.sort(key=lambda reference: (reference.sheet_name, reference.table_id))
        self.tokens = [char_ngram_tokens(f"{record.filename} {record.text}") for record in self.documents]
        self.document_frequency: Counter[str] = Counter()
        for tokens in self.tokens:
            self.document_frequency.update(set(tokens))
        self.average_length = sum(len(tokens) for tokens in self.tokens) / max(1, len(self.tokens))

    def search(self, query: str, top_k: int) -> list[SearchHit]:
        query_tokens = char_ngram_tokens(query)
        if not query_tokens:
            return []
        scored: list[tuple[float, int, FileRecord]] = []
        document_count = len(self.documents)
        for index, (record, tokens) in enumerate(zip(self.documents, self.tokens)):
            frequencies = Counter(tokens)
            score = 0.0
            for token in query_tokens:
                document_frequency = self.document_frequency.get(token, 0)
                if document_frequency == 0:
                    continue
                inverse_frequency = math.log(
                    1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                frequency = frequencies[token]
                denominator = frequency + 1.5 * (
                    1 - 0.75 + 0.75 * len(tokens) / max(1, self.average_length)
                )
                score += inverse_frequency * frequency * 2.5 / denominator
            if score > 0:
                scored.append((score, index, record))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [self._hit(record, score, query) for score, _, record in scored[:top_k]]

    def _hit(self, record: FileRecord, score: float, query: str) -> SearchHit:
        content = record.text.strip()
        normalized_query = normalize_text(query)
        normalized_content = normalize_text(content)
        position = normalized_content.find(normalized_query)
        start = max(0, position - 80) if position >= 0 else 0
        tables = self.tables_by_file.get(record.file_id, [])
        return SearchHit(
            document_id=record.file_id,
            title=record.filename,
            document_type="tabular" if tables else "document",
            tables=tables,
            metadata={
                "relative_path": record.relative_path,
                "extension": record.extension,
                "modified_at": record.modified_at.isoformat(),
            },
            snippet=content[start : start + 400],
            score=round(score, 6),
        )
