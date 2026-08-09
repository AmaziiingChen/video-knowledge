"""Pure structural Markdown chunking for the V2 knowledge index."""
from __future__ import annotations

import re
from dataclasses import dataclass

CHILD_TARGET_TOKENS = 380
CHILD_MAX_TOKENS = 450
PARENT_MAX_TOKENS = 1_500

_FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)
_GENERATED_RE = re.compile(r"^##\s*(?:AI\s*摘要|追问记录)\s*$", re.IGNORECASE | re.MULTILINE)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_LIST_RE = re.compile(r"^\s*(?:[-*+] |\d+[.)] )")
_TABLE_DIVIDER_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_TOKEN_RE = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9_]+|[^\s]")
_SENTENCE_RE = re.compile(r"(?<=[。！？；.!?;])\s*")


@dataclass(frozen=True)
class SourceBlock:
    text: str
    heading_path: str
    atomic: bool = False


@dataclass(frozen=True)
class ParentChunk:
    ordinal: int
    heading_path: str
    text: str
    token_count: int


@dataclass(frozen=True)
class ChildChunk:
    parent_ordinal: int
    ordinal: int
    heading_path: str
    text: str
    token_count: int


def estimate_tokens(value: str) -> int:
    """A stable local estimate used only for chunk boundaries and previews."""
    return len(_TOKEN_RE.findall(str(value or "")))


def clean_source_markdown(markdown: str) -> str:
    """Remove generated answer sections without flattening source structure."""
    value = _FRONTMATTER_RE.sub("", str(markdown or "")).replace("\r\n", "\n")
    generated = _GENERATED_RE.search(value)
    if generated:
        value = value[: generated.start()]
    value = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", value)
    value = re.sub(r"\[/?图片文字\s*\d+\]\s*", "", value)
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def structural_chunks(markdown: str) -> tuple[list[ParentChunk], list[ChildChunk]]:
    """Create parent/child chunks without splitting headings, lists or tables."""
    blocks = _source_blocks(clean_source_markdown(markdown))
    if not blocks:
        return [], []
    parents = _make_parents(blocks)
    return parents, _make_children(parents)


def _source_blocks(markdown: str) -> list[SourceBlock]:
    lines = markdown.splitlines()
    blocks: list[SourceBlock] = []
    heading_stack: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            level, title = len(heading.group(1)), heading.group(2).strip()
            heading_stack = heading_stack[: level - 1]
            heading_stack.append(title)
            blocks.append(SourceBlock(text=line.strip(), heading_path=" / ".join(heading_stack), atomic=True))
            index += 1
            continue
        path = " / ".join(heading_stack) or "正文"
        if line.lstrip().lower().startswith("<table"):
            table_lines = [line]
            index += 1
            while index < len(lines):
                table_lines.append(lines[index])
                if "</table>" in lines[index].lower():
                    index += 1
                    break
                index += 1
            blocks.append(SourceBlock("\n".join(table_lines).strip(), path, atomic=True))
            continue
        if _is_markdown_table(lines, index):
            table_lines = [lines[index], lines[index + 1]]
            index += 2
            while index < len(lines) and lines[index].strip() and "|" in lines[index]:
                table_lines.append(lines[index])
                index += 1
            blocks.append(SourceBlock("\n".join(table_lines).strip(), path, atomic=True))
            continue
        if line.lstrip().startswith("```"):
            code_lines = [line]
            index += 1
            while index < len(lines):
                code_lines.append(lines[index])
                if lines[index].lstrip().startswith("```"):
                    index += 1
                    break
                index += 1
            blocks.append(SourceBlock("\n".join(code_lines).strip(), path, atomic=True))
            continue
        if _LIST_RE.match(line):
            list_lines = [line]
            index += 1
            while index < len(lines):
                candidate = lines[index]
                if not candidate.strip():
                    break
                if _LIST_RE.match(candidate) or candidate.startswith((" ", "\t")):
                    list_lines.append(candidate)
                    index += 1
                    continue
                break
            blocks.append(SourceBlock("\n".join(list_lines).strip(), path, atomic=True))
            continue
        paragraph = [line]
        index += 1
        while index < len(lines):
            candidate = lines[index]
            if not candidate.strip() or _HEADING_RE.match(candidate) or _LIST_RE.match(candidate):
                break
            if candidate.lstrip().lower().startswith("<table") or candidate.lstrip().startswith("```") or _is_markdown_table(lines, index):
                break
            paragraph.append(candidate)
            index += 1
        blocks.extend(SourceBlock(piece, path) for piece in _split_prose("\n".join(paragraph).strip(), CHILD_MAX_TOKENS))
    return [block for block in blocks if block.text]


def _is_markdown_table(lines: list[str], index: int) -> bool:
    return index + 1 < len(lines) and "|" in lines[index] and bool(_TABLE_DIVIDER_RE.match(lines[index + 1]))


def _split_prose(text: str, max_tokens: int) -> list[str]:
    if estimate_tokens(text) <= max_tokens:
        return [text]
    sentences = [part.strip() for part in _SENTENCE_RE.split(text) if part.strip()]
    if len(sentences) < 2:
        return [text]
    pieces: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for sentence in sentences:
        size = estimate_tokens(sentence)
        if current and current_tokens + size > max_tokens:
            pieces.append(" ".join(current).strip())
            current, current_tokens = [], 0
        current.append(sentence)
        current_tokens += size
    if current:
        pieces.append(" ".join(current).strip())
    return pieces


def _make_parents(blocks: list[SourceBlock]) -> list[ParentChunk]:
    output: list[ParentChunk] = []
    current: list[SourceBlock] = []
    current_tokens = 0
    for block in blocks:
        size = estimate_tokens(block.text)
        if current and current_tokens + size > PARENT_MAX_TOKENS:
            output.append(_parent_from_blocks(len(output), current))
            current, current_tokens = [], 0
        current.append(block)
        current_tokens += size
    if current:
        output.append(_parent_from_blocks(len(output), current))
    return output


def _parent_from_blocks(ordinal: int, blocks: list[SourceBlock]) -> ParentChunk:
    text = "\n\n".join(block.text for block in blocks).strip()
    return ParentChunk(ordinal, blocks[0].heading_path, text, estimate_tokens(text))


def _make_children(parents: list[ParentChunk]) -> list[ChildChunk]:
    children: list[ChildChunk] = []
    for parent in parents:
        blocks = _source_blocks(parent.text)
        current: list[SourceBlock] = []
        current_tokens = 0
        for block in blocks:
            size = estimate_tokens(block.text)
            if current and current_tokens + size > CHILD_MAX_TOKENS:
                children.append(_child_from_blocks(parent.ordinal, len(children), current))
                current, current_tokens = [], 0
            current.append(block)
            current_tokens += size
        if current:
            children.append(_child_from_blocks(parent.ordinal, len(children), current))
    return children


def _child_from_blocks(parent_ordinal: int, ordinal: int, blocks: list[SourceBlock]) -> ChildChunk:
    text = "\n\n".join(block.text for block in blocks).strip()
    return ChildChunk(parent_ordinal, ordinal, blocks[0].heading_path, text, estimate_tokens(text))
