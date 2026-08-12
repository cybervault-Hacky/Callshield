"""Screen stack and pagination helpers.

The stack guarantees the user can always leave: popping the last screen exits
cleanly rather than dead-ending, and a screen can never push itself into an
unbounded loop because the depth is capped.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

MAX_DEPTH = 12


class ScreenStack:
    """LIFO stack of (screen, title) frames."""

    def __init__(self, root: Any = None, title: str = "") -> None:
        self._frames: List[Tuple[Any, str]] = []
        if root is not None:
            self._frames.append((root, title))

    def __len__(self) -> int:
        return len(self._frames)

    @property
    def empty(self) -> bool:
        return not self._frames

    @property
    def current(self) -> Optional[Any]:
        return self._frames[-1][0] if self._frames else None

    @property
    def depth(self) -> int:
        return len(self._frames)

    def trail(self) -> List[str]:
        return [title for _, title in self._frames if title]

    def push(self, screen: Any, title: str = "") -> Any:
        if len(self._frames) >= MAX_DEPTH:
            # Refuse to nest further rather than growing without bound.
            self._frames.pop()
        self._frames.append((screen, title))
        return screen

    def pop(self) -> Optional[Any]:
        if not self._frames:
            return None
        self._frames.pop()
        return self.current

    def replace(self, screen: Any, title: str = "") -> Any:
        if self._frames:
            self._frames.pop()
        return self.push(screen, title)

    def reset(self, screen: Any = None, title: str = "") -> None:
        self._frames = []
        if screen is not None:
            self.push(screen, title)


class Pager:
    """Offset/limit bookkeeping for bounded history queries."""

    def __init__(self, page_size: int = 10, total: int = 0) -> None:
        self.page_size = max(1, int(page_size))
        self.total = max(0, int(total))
        self.offset = 0

    @property
    def page(self) -> int:
        return (self.offset // self.page_size) + 1

    @property
    def pages(self) -> int:
        if self.total <= 0:
            return 1
        return max(1, (self.total + self.page_size - 1) // self.page_size)

    def set_total(self, total: int) -> None:
        self.total = max(0, int(total))
        self.clamp()

    def resize(self, page_size: int) -> None:
        self.page_size = max(1, int(page_size))
        self.clamp()

    def clamp(self) -> None:
        highest = max(0, (self.pages - 1) * self.page_size)
        self.offset = max(0, min(self.offset, highest))

    def next_page(self) -> bool:
        if self.offset + self.page_size >= self.total:
            return False
        self.offset += self.page_size
        return True

    def previous_page(self) -> bool:
        if self.offset <= 0:
            return False
        self.offset = max(0, self.offset - self.page_size)
        return True

    def first_page(self) -> None:
        self.offset = 0

    def last_page(self) -> None:
        self.offset = max(0, (self.pages - 1) * self.page_size)

    def slice(self, rows: Sequence[Any]) -> List[Any]:
        return list(rows[self.offset:self.offset + self.page_size])

    def label(self) -> str:
        return "Page {0}/{1}".format(self.page, self.pages)


__all__ = ["MAX_DEPTH", "Pager", "ScreenStack"]
