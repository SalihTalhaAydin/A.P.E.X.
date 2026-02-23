#!/usr/bin/env python3
"""
Build docs/bugs.csv from BUG_FIX_PROMPT_* markdown files.
Parses bugs, deduplicates by file+description, outputs CSV.
NOTE: BUG_FIX_PROMPT_*.md files were removed; docs/bugs.csv is now the source of truth.
"""

import csv
import re
from pathlib import Path
from dataclasses import dataclass, field

# Priority order for merging (higher = more severe)
PRIORITY_ORDER = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}

SOURCES = [
    ("P4", "docs/BUG_FIX_PROMPT_4.md"),
    ("P5", "docs/BUG_FIX_PROMPT_5.md"),
    ("P3", "docs/BUG_FIX_PROMPT_3.md"),
    ("P6", "docs/BUG_FIX_PROMPT_6.md"),
    ("P7", "docs/BUG_FIX_PROMPT_7.md"),
    ("P8", "docs/BUG_FIX_PROMPT_8.md"),
    ("P9", "docs/BUG_FIX_PROMPT_9.md"),
]


@dataclass
class Bug:
    source: str
    orig_id: str
    description: str
    priority: str
    file_path: str
    btype: str
    merged_from: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


def desc_word_set(s: str) -> set[str]:
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s]", "", s)
    return set(w for w in s.split() if len(w) > 2)


def normalize_file(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r":\d+(-\d+)?$", "", s)  # strip line numbers for dedup
    s = " ".join(s.split())
    return s


def extract_file(block: str) -> str:
    # **File:** `path` or **File:** path
    m = re.search(r"\*\*File:\*\*\s*[`]?([^\s`\n]+(?::\d+(?:-\d+)?)?)[`]?", block, re.IGNORECASE)
    if m:
        return normalize_file(m.group(1))
    # Table format: | File | `path` |
    m = re.search(r"\|\s*File\s*\|\s*[`]?([^`|\n]+)[`]?\s*\|", block, re.IGNORECASE)
    if m:
        return normalize_file(m.group(1).strip())
    # Inline in header: ### BUG-92: `generic.py:637` —
    m = re.search(r"`([a-zA-Z0-9_/.-]+\.py:\d+(?:-\d+)?)`", block[:400])
    if m:
        path = m.group(1)
        if not path.startswith("apex_brain/"):
            path = f"apex_brain/{path}"
        return path
    return ""


def extract_problem(block: str) -> str:
    m = re.search(r"\*\*Problem:\*\*\s*(.+?)(?=\n\*\*|\n```|\n##|\n###|\n---|\Z)", block, re.DOTALL)
    if m:
        desc = m.group(1).strip()
        desc = re.sub(r"\n+", " ", desc)
        desc = re.sub(r"\s+", " ", desc)
        return desc[:500]
    # Fallback: title from header
    m = re.search(r"###\s*(?:BUG|GAP|TEST)[^\—\-]+[—\-]\s*(.+?)(?:\n|$)", block)
    if m:
        return m.group(1).strip()[:500]
    return block[:200].replace("\n", " ").strip()


def parse_prompt_file(prefix: str, filepath: Path) -> list[Bug]:
    bugs = []
    content = filepath.read_text(encoding="utf-8")

    # Find current priority from last ## CRITICAL/HIGH/MEDIUM/LOW before each bug
    section_priority = "MEDIUM"
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if re.match(r"^## (CRITICAL|HIGH|MEDIUM|LOW)", line):
            section_priority = re.match(r"^## (CRITICAL|HIGH|MEDIUM|LOW)", line).group(1)

        m = re.match(r"^### (BUG-\d+|GAP-\d+|TEST-\d+|TEST-GAP-\d+):?\s*(.+)$", line)
        if m:
            orig_id = m.group(1)
            if "GAP" in orig_id:
                btype = "gap"
            elif "TEST" in orig_id:
                btype = "test"
            else:
                btype = "bug"

            # Collect block until next ### or ---
            block_lines = [line]
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("### ") or (lines[j].strip() == "---" and j > i + 2):
                    break
                block_lines.append(lines[j])
            block = "\n".join(block_lines)

            file_path = extract_file(block)
            if not file_path and m.group(2):
                # Try to get file from header: `file.py:123` or `file.py`
                fm = re.search(r"`([a-zA-Z0-9_/.-]+\.py(?::\d+(?:-\d+)?)?)`", m.group(2))
                if fm:
                    fp = fm.group(1)
                    if not fp.startswith("apex_brain/"):
                        fp = f"apex_brain/{fp}"
                    file_path = fp

            problem = extract_problem(block)
            if not problem and m.group(2):
                problem = m.group(2).split("—")[-1].split("→")[0].strip()[:500]

            bugs.append(
                Bug(
                    source=prefix,
                    orig_id=orig_id,
                    description=problem,
                    priority=section_priority,
                    file_path=file_path or "",
                    btype=btype,
                    merged_from=[f"{prefix}-{orig_id}"],
                    sources=[prefix],
                )
            )

    # Parse GAP table format: | GAP-1 | description | HIGH |
    for m in re.finditer(r"\|\s*(GAP-\d+)\s*\|\s*(.+?)\s*\|\s*(HIGH|MEDIUM|LOW)\s*\|", content):
        orig_id, cell, prio = m.group(1), m.group(2).strip(), m.group(3)
        desc = re.sub(r"`([^`]+)`", r"\1", cell).strip()  # unquote backticks
        file_path = ""
        if "conftest" in cell.lower():
            file_path = "apex_brain/tests/conftest.py"
        elif "test_" in cell and ".py" in cell:
            fm = re.search(r"(tests/[a-z_]+\.py)", cell)
            file_path = f"apex_brain/{fm.group(1)}" if fm else ""
        bugs.append(
            Bug(
                source=prefix,
                orig_id=orig_id,
                description=desc[:500],
                priority=prio,
                file_path=file_path,
                btype="gap",
                merged_from=[f"{prefix}-{orig_id}"],
                sources=[prefix],
            )
        )
    return bugs


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def deduplicate(bugs: list[Bug]) -> list[Bug]:
    # First pass: exact match on (file, desc_word_set)
    by_key: dict[tuple[str, frozenset], Bug] = {}
    for b in bugs:
        fkey = normalize_file(b.file_path) if b.file_path else f"no_file_{b.orig_id}"
        wset = frozenset(desc_word_set(b.description)) if b.description else frozenset()
        key = (fkey, wset)
        if key in by_key:
            existing = by_key[key]
            if PRIORITY_ORDER.get(b.priority, 0) > PRIORITY_ORDER.get(existing.priority, 0):
                existing.priority = b.priority
            existing.merged_from.extend(b.merged_from)
            existing.sources = list(dict.fromkeys(existing.sources + b.sources))
        else:
            by_key[key] = b

    # Second pass: merge by file + high Jaccard similarity
    result = list(by_key.values())

    # Manual merges for known duplicates (same issue, different prompt wording)
    MANUAL_MERGES = [
        ("P4-BUG-59", "P9-BUG-143"),  # shutdown store None guards
        ("P3-BUG-102", "P6-BUG-93"),  # correct_fact race/transaction
    ]
    for a_id, b_id in MANUAL_MERGES:
        a_bug = next((b for b in result if f"{b.source}-{b.orig_id}" == a_id), None)
        b_bug = next((b for b in result if f"{b.source}-{b.orig_id}" == b_id), None)
        if a_bug and b_bug:
            if PRIORITY_ORDER.get(b_bug.priority, 0) > PRIORITY_ORDER.get(a_bug.priority, 0):
                a_bug.priority = b_bug.priority
            a_bug.merged_from.extend(b_bug.merged_from)
            a_bug.sources = list(dict.fromkeys(a_bug.sources + b_bug.sources))
            if len(b_bug.description) > len(a_bug.description):
                a_bug.description = b_bug.description
            result.remove(b_bug)
    merged_any = True
    while merged_any:
        merged_any = False
        for i, a in enumerate(result):
            if not a.file_path or not a.description:
                continue
            fa = normalize_file(a.file_path)
            wa = desc_word_set(a.description)
            for j, b in enumerate(result):
                if i >= j or not b.file_path or not b.description:
                    continue
                fb = normalize_file(b.file_path)
                wb = desc_word_set(b.description)
                if fa == fb and jaccard(wa, wb) >= 0.40:
                    if PRIORITY_ORDER.get(b.priority, 0) > PRIORITY_ORDER.get(a.priority, 0):
                        a.priority = b.priority
                    a.merged_from.extend(b.merged_from)
                    a.sources = list(dict.fromkeys(a.sources + b.sources))
                    if len(a.description) < len(b.description):
                        a.description = b.description
                    result.pop(j)
                    merged_any = True
                    break
    return result


def main():
    root = Path(__file__).resolve().parent.parent
    all_bugs: list[Bug] = []

    for prefix, rel_path in SOURCES:
        filepath = root / rel_path
        if not filepath.exists():
            print(f"Skip (not found): {filepath}")
            continue
        parsed = parse_prompt_file(prefix, filepath)
        all_bugs.extend(parsed)
        print(f"Parsed {len(parsed)} from {rel_path}")

    if not all_bugs:
        print("No BUG_FIX_PROMPT_*.md files found. docs/bugs.csv is the source of truth.")
        return

    merged = deduplicate(all_bugs)
    print(f"After dedup: {len(merged)} unique bugs")

    def sort_key(b: Bug):
        return (-PRIORITY_ORDER.get(b.priority, 0), b.file_path, b.description[:50])

    merged.sort(key=sort_key)

    out_path = root / "docs" / "bugs.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        w.writerow(["id", "description", "status", "priority", "file", "type", "sources", "merged_from", "reopened_count"])
        for i, b in enumerate(merged, 1):
            merged_str = ",".join(sorted(set(b.merged_from))) if b.merged_from else ""
            sources_str = ",".join(sorted(set(b.sources))) if b.sources else ""
            w.writerow([
                i,
                b.description,
                "to-do",
                b.priority,
                b.file_path,
                b.btype,
                sources_str,
                merged_str,
                0,
            ])

    print(f"Wrote {out_path} with {len(merged)} rows")


if __name__ == "__main__":
    main()
