"""Dictionary management for domain-specific terminology."""

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DictionaryEntry:
    """A single dictionary entry."""

    source_term: str
    target_term: str
    notes: str = ""


class TermDictionary:
    """Dictionary for domain-specific terminology."""

    def __init__(self) -> None:
        self._entries: dict[str, DictionaryEntry] = {}

    def load_csv(self, path: Path | str) -> int:
        """Load dictionary entries from CSV file."""
        path = Path(path)
        count = 0

        with path.open(encoding="utf-8") as f:
            reader = csv.reader(f)

            first_row = next(reader, None)
            header_values = ("source", "source_term", "原語")
            if first_row and first_row[0].lower() not in header_values:
                self._add_row(first_row)
                count += 1

            for row in reader:
                if self._add_row(row):
                    count += 1

        return count

    def _add_row(self, row: list[str]) -> bool:
        if len(row) < 2:
            return False

        source_term = row[0].strip()
        target_term = row[1].strip()
        notes = row[2].strip() if len(row) > 2 else ""

        if not source_term or not target_term:
            return False

        self._entries[source_term.lower()] = DictionaryEntry(
            source_term=source_term,
            target_term=target_term,
            notes=notes,
        )
        return True

    def add_entry(self, source_term: str, target_term: str, notes: str = "") -> None:
        """Add a dictionary entry."""
        self._entries[source_term.lower()] = DictionaryEntry(
            source_term=source_term,
            target_term=target_term,
            notes=notes,
        )

    def get(self, term: str) -> DictionaryEntry | None:
        """Look up a term."""
        return self._entries.get(term.lower())

    def format_for_prompt(self) -> str:
        """Format dictionary for inclusion in LLM prompt."""
        if not self._entries:
            return ""

        lines = ["[Terminology Dictionary - Use these exact translations:]"]
        for entry in self._entries.values():
            line = f"- {entry.source_term} → {entry.target_term}"
            if entry.notes:
                line += f" ({entry.notes})"
            lines.append(line)

        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self._entries)

    def __bool__(self) -> bool:
        return bool(self._entries)
