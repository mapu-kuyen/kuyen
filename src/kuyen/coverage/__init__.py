"""Deterministic document-section inventory and coverage accounting."""
from .sections import SectionUnit, inventory_sections
from .metrics import coverage_metrics

__all__ = ["SectionUnit", "inventory_sections", "coverage_metrics"]
