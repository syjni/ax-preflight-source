"""Cross-platform reproduction of the Windows path order used by frozen data.

The existing immutable manifests were created on Windows.  Sorting ``Path``
objects directly is platform-dependent, so verifiers normalize relative paths
to Windows separators and lowercase them before ordering.
"""

from __future__ import annotations

from pathlib import Path


def frozen_windows_path_key(root: Path, item: Path) -> str:
    """Return the stable key used by existing Windows-created manifests."""
    return item.relative_to(root).as_posix().replace("/", "\\").lower()


def frozen_sorted_files(root: Path) -> list[Path]:
    """List files recursively in the existing frozen Windows order."""
    return sorted(
        (item for item in root.rglob("*") if item.is_file()),
        key=lambda item: frozen_windows_path_key(root, item),
    )
