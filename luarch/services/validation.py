from __future__ import annotations

from .. import metadata
from .validation_facts import _collect_validation_facts, _load_validation_state
from .validation_rules import collect_validation_issues, is_export_policy_warning

__all__ = ("validate_root", "validation_requires_regeneration", "export_blocking_validation_issues")


_REGEN_REQUIRED_PREFIXES = (
    "Stored spec",
    "Stored generation summary",
    "Stored generation summary schema mismatch:",
    "Root metadata summary schema mismatch:",
    "Export contract failure:",
    "Sidecar contract failure:",
)


def validation_requires_regeneration(issues: list[str]) -> bool:
    return any(issue.startswith(_REGEN_REQUIRED_PREFIXES) for issue in issues)


def export_blocking_validation_issues(issues: list[str]) -> list[str]:
    return [issue for issue in issues if not is_export_policy_warning(issue)]


def validate_root(root_obj) -> list[str]:
    if root_obj is None:
        return ["No root object selected."]

    if not metadata.is_root_object(root_obj):
        return ["Active object is not a Tactical Building root."]

    loaded = _load_validation_state(root_obj)
    if isinstance(loaded, list):
        return loaded

    facts = _collect_validation_facts(loaded)
    return collect_validation_issues(facts)
