from typing import List, Optional
from pydantic import BaseModel, Field


class ExtractedTask(BaseModel):
    task_id: str = Field(..., description="Unique hierarchical ID like M1-DB-01")
    parent_id: Optional[str] = Field(None, description="Parent MILESTONE or MODULE task_id")
    level: str = Field(..., description="One of: MILESTONE, MODULE, TASK")
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
