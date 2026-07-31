"""Discovery of curated domain-specific terminology packs.

A pack is a CSV file at `<domain_packs_dir>/<name>.csv`, same format as any
other dictionary (source_term,target_term,notes). Selected packs are loaded
before the session `dictionary_path`, so session-specific entries always
take precedence over the pack (see `LLMTranslator`).
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_DOMAIN_PACKS_DIR = Path("dictionaries/domains")


def list_domain_packs(base_dir: Path | str = DEFAULT_DOMAIN_PACKS_DIR) -> list[str]:
    """Names of available domain packs (CSV stem names) in `base_dir`."""
    base_dir = Path(base_dir)
    if not base_dir.exists():
        return []
    return sorted(p.stem for p in base_dir.glob("*.csv"))


def resolve_domain_pack(
    name: str, base_dir: Path | str = DEFAULT_DOMAIN_PACKS_DIR
) -> Path:
    """Resolve a pack name to its CSV path.

    Raises:
        FileNotFoundError: If no pack named `name` exists in `base_dir`,
            listing the packs that do exist to make the typo obvious.
    """
    base_dir = Path(base_dir)
    path = base_dir / f"{name}.csv"
    if not path.exists():
        available = list_domain_packs(base_dir)
        raise FileNotFoundError(
            f"Unknown domain pack {name!r} (looked in {base_dir}). "
            f"Available packs: {available or '(none found)'}"
        )
    return path
