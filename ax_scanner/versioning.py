from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from .models import FileRecord, ProbableVersionGroup, VersionCandidate


_SIGNAL_PATTERNS = [
    ("version_number", re.compile(r"(?i)(?<![0-9a-z])v\d+(?:\.\d+)*(?![0-9a-z])")),
    ("year", re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")),
    ("final", re.compile(r"(?i)(?:final|final\d*|최종|최종본|진짜최종|현재본)")),
    ("old", re.compile(r"(?i)(?:old|archive|archived|구버전|이전본)")),
    ("revision", re.compile(r"(?i)(?:rev|revision|수정)\d*")),
]


def filename_version_signature(filename: str) -> tuple[str, list[str]]:
    stem = unicodedata.normalize("NFKC", Path(filename).stem).lower()
    signals = []
    normalized = stem
    for label, pattern in _SIGNAL_PATTERNS:
        if pattern.search(stem):
            signals.append(label)
        normalized = pattern.sub(" ", normalized)
    normalized = re.sub(r"[^0-9a-z가-힣]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized, sorted(set(signals))


def group_probable_versions(files: list[FileRecord]) -> list[ProbableVersionGroup]:
    groups: dict[str, list[VersionCandidate]] = defaultdict(list)
    for file in files:
        normalized, signals = filename_version_signature(file.filename)
        if normalized and signals:
            groups[normalized].append(
                VersionCandidate(file_id=file.file_id, relative_path=file.relative_path, signals=signals)
            )
    output = []
    for normalized, candidates in sorted(groups.items()):
        if len(candidates) < 2:
            continue
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        output.append(
            ProbableVersionGroup(
                version_group_id=f"VERSION_{digest}",
                normalized_name=normalized,
                candidates=sorted(candidates, key=lambda item: item.relative_path),
            )
        )
    return output

