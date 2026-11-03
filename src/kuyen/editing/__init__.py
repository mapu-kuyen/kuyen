"""Antü graph editing: a second, independent way of evolving a KÜYEN (§2, §6, §7).

The document path materialises knowledge through OpenViking; this package edits the graph
that already exists, through a model that only *proposes*. KÜYEN validates, applies and
versions. Nothing here calls OpenViking, reads a MAPU or invents evidence.
"""
from .applier import ApplicationResult, GraphEditApplier
from .context import EditContext, build_context, keywords
from .diff import current_objects, diff_documents, summarize
from .editors import (EditorConfig, EditorConfigurationError, EditorError, EditorUsage,
                      GraphEditorPort, OpenAICompatibleGraphEditor, RecordedGraphEditor,
                      editor_prompt_key)
from .operations import (ADD_ASSERTION, ADD_ENTITY, ADD_RELATION, CLARIFICATION_REQUIRED,
                         CONFLICT, EDIT_CONTRACT_ID, NO_CHANGES, OPERATION_TYPES, PROPOSED,
                         RETRACT_ASSERTION, RETRACT_RELATION, UPDATE_ASSERTION, UPDATE_ATTRIBUTE,
                         UPDATE_ENTITY, UPDATE_RELATION, GraphEditOperation, GraphEditProposal,
                         parse_proposal)
from .prompt import SYSTEM_PROMPT, GraphEditRequest, build_request, constraint_summary
from .service import (STATUS_CLARIFICATION, STATUS_CONFLICT, STATUS_INTERPRETATION_FAILED,
                      STATUS_NO_CHANGES, STATUS_REJECTED, STATUS_VALIDATED, EditRun,
                      derive_antu_id, edit_provenance_record, run_edit)
from .validator import EditValidator, OperationRejection, ValidationOutcome

__all__ = [
    "GraphEditApplier", "ApplicationResult", "EditContext", "build_context", "keywords",
    "diff_documents", "summarize", "current_objects",
    "EditorConfig", "EditorConfigurationError", "EditorError", "EditorUsage", "GraphEditorPort",
    "OpenAICompatibleGraphEditor", "RecordedGraphEditor", "editor_prompt_key",
    "EDIT_CONTRACT_ID", "OPERATION_TYPES", "PROPOSED", "CLARIFICATION_REQUIRED", "CONFLICT",
    "NO_CHANGES", "ADD_ENTITY", "UPDATE_ENTITY", "ADD_ASSERTION", "UPDATE_ASSERTION",
    "RETRACT_ASSERTION", "ADD_RELATION", "UPDATE_RELATION", "RETRACT_RELATION",
    "UPDATE_ATTRIBUTE", "GraphEditOperation", "GraphEditProposal", "parse_proposal",
    "SYSTEM_PROMPT", "GraphEditRequest", "build_request", "constraint_summary",
    "EditRun", "run_edit", "derive_antu_id", "edit_provenance_record",
    "STATUS_VALIDATED", "STATUS_NO_CHANGES", "STATUS_CLARIFICATION", "STATUS_CONFLICT",
    "STATUS_REJECTED", "STATUS_INTERPRETATION_FAILED",
    "EditValidator", "ValidationOutcome", "OperationRejection",
]