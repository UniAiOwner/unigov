from typing import List, Optional
from pydantic import BaseModel, Field


class ExtractedTask(BaseModel):
    task_id: str = Field(..., description="Unique hierarchical ID like M1-DB-01")
    parent_id: Optional[str] = Field(None, description="Parent MILESTONE or MODULE task_id")
    level: str = Field(..., description="One of: MILESTONE, MODULE, TASK")
    layer: str = Field(default="LAYER_1_DOMAIN", description="One of: LAYER_1_DOMAIN, LAYER_2_DATA, LAYER_3_SURFACES, LAYER_4_SECURITY, LAYER_5_INTELLIGENCE")
    title: str
    description: str
    depends_on: List[str] = Field(default_factory=list)
    target_files: List[str] = Field(default_factory=list)
    verify_cmd: Optional[str] = None


class DocConflict(BaseModel):
    topic: str
    doc_a: str
    claim_a: str
    doc_b: str
    claim_b: str
    recommended_resolution: str


class MultiDocAnalysis(BaseModel):
    merged_objective: str
    hard_constraints: List[str]
    conflicts: List[DocConflict] = Field(default_factory=list)
    tasks: List[ExtractedTask]


class DriftReport(BaseModel):
    drift_detected: bool
    violated_constraints: List[str] = Field(default_factory=list)
    explanation: str


class SearchReplaceBlock(BaseModel):
    search: str = Field(..., description="Exact verbatim multi-line snippet to locate in existing file")
    replace: str = Field(..., description="Exact replacement code snippet")


class FilePatch(BaseModel):
    file_path: str
    is_new_file: bool = Field(False, description="True only when creating a brand-new file")
    new_file_content: Optional[str] = Field(None, description="Full content ONLY if is_new_file=True")
    edits: List[SearchReplaceBlock] = Field(default_factory=list, description="Surgical edits for existing files")
    explanation: str


class AgentExecutionPlan(BaseModel):
    reasoning: str
    patches: List[FilePatch]


class TaskReconciliationResult(BaseModel):
    task_id: str
    status: str = Field(..., description="COMPLETED, PARTIAL, or MISSING")
    matched_files: List[str] = Field(default_factory=list)
    evidence: str = Field(..., description="Explanation of why it's completed, partial, or missing")
    missing_items: List[str] = Field(default_factory=list)


class ReconciliationSummary(BaseModel):
    total_tasks: int
    completed_tasks: int
    partial_tasks: int
    missing_tasks: int
    results: List[TaskReconciliationResult]


class ArchitecturalInvariant(BaseModel):
    invariant_id: str = Field(..., description="e.g. INV-FIN-001")
    layer: str = Field(..., description="e.g. LAYER_1_DOMAIN")
    title: str
    rule_type: str = Field(..., description="FORBIDDEN_TOKENS, REQUIRED_COLUMNS, MANDATORY_UI_STATES, FSM_STATES, LATENCY_BUDGET")
    file_patterns: List[str] = Field(default_factory=list)
    params: dict = Field(default_factory=dict)
    enforcement: str = Field("BLOCK_BUILD", description="BLOCK_BUILD or WARN")
    source_doc: str = Field("", description="Document file path where invariant was defined")


class DimensionCoverage(BaseModel):
    dimension_index: int
    dimension_name: str
    layer: str
    present: bool
    file_path: Optional[str] = None
    invariants_count: int = 0


class SpecVerificationReport(BaseModel):
    total_dimensions: int = 15
    covered_dimensions: int
    readiness_score: float
    dimensions: List[DimensionCoverage]
    invariants_extracted: int
    conflicts: List[DocConflict] = Field(default_factory=list)


class ADRSynthesis(BaseModel):
    adr_id: str = Field(description="Unique ADR ID e.g. ADR-005-ROOM-MIGRATION")
    module_tag: str = Field(description="Module or subsystem affected e.g. core:data:db")
    title: str = Field(description="Title of decision")
    decision: str = Field(description="Architectural decision made")
    rationale: str = Field(description="Rationale and business/technical justification")
    rejected_alternatives: str = Field(description="Alternatives considered and rejected")

