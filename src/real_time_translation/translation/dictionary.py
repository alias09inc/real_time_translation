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
    """Dictionary for domain-specific terminology.

    Manages terminology mappings loaded from CSV files.
    CSV format: source_term,target_term,notes (optional)
    """

    def __init__(self) -> None:
        """Initialize empty dictionary."""
        self._entries: dict[str, DictionaryEntry] = {}

    def load_csv(self, path: Path | str) -> int:
        """Load dictionary entries from CSV file.

        Args:
            path: Path to CSV file

        Returns:
            Number of entries loaded
        """
        path = Path(path)
        count = 0

        with path.open(encoding="utf-8") as f:
            reader = csv.reader(f)

            # Skip header if present
            first_row = next(reader, None)
            header_values = ("source", "source_term", "原語")
            if first_row and first_row[0].lower() not in header_values:
                # Not a header, process as data
                self._add_row(first_row)
                count += 1

            for row in reader:
                if self._add_row(row):
                    count += 1

        return count

    def _add_row(self, row: list[str]) -> bool:
        """Add a row from CSV.

        Args:
            row: CSV row data

        Returns:
            True if entry was added
        """
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
        """Add a dictionary entry.

        Args:
            source_term: Term in source language
            target_term: Term in target language
            notes: Optional notes about the term
        """
        self._entries[source_term.lower()] = DictionaryEntry(
            source_term=source_term,
            target_term=target_term,
            notes=notes,
        )

    def get(self, term: str) -> DictionaryEntry | None:
        """Look up a term.

        Args:
            term: Term to look up

        Returns:
            Dictionary entry or None if not found
        """
        return self._entries.get(term.lower())

    def format_for_prompt(self) -> str:
        """Format dictionary for inclusion in LLM prompt.

        Returns:
            Formatted dictionary string
        """
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
        """Return number of entries."""
        return len(self._entries)

    def __bool__(self) -> bool:
        """Return True if dictionary has entries."""
        return bool(self._entries)
