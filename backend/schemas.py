"""Request/response models. Every user-tunable parameter is validated here,
before it ever reaches Google, so bad input fails fast with a clear 422."""
import re
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------- chunking --

DEFAULT_CHUNK_TOKENS = 250
DEFAULT_OVERLAP_TOKENS = 40
CHUNK_TOKENS_RANGE = (20, 2048)
OVERLAP_TOKENS_RANGE = (0, 512)


class ChunkingParams(BaseModel):
    """Maps to google.genai.types.ChunkingConfig.white_space_config."""

    max_tokens_per_chunk: int = Field(
        DEFAULT_CHUNK_TOKENS, ge=CHUNK_TOKENS_RANGE[0], le=CHUNK_TOKENS_RANGE[1]
    )
    max_overlap_tokens: int = Field(
        DEFAULT_OVERLAP_TOKENS, ge=OVERLAP_TOKENS_RANGE[0], le=OVERLAP_TOKENS_RANGE[1]
    )

    @model_validator(mode="after")
    def _overlap_smaller_than_chunk(self):
        if self.max_overlap_tokens >= self.max_tokens_per_chunk:
            raise ValueError("max_overlap_tokens must be smaller than max_tokens_per_chunk")
        return self


_METADATA_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


class MetadataEntry(BaseModel):
    """Maps to google.genai.types.CustomMetadata. Query it later with metadata_filter,
    e.g.  year > 2020 AND subject = "math"."""

    key: str
    value: Union[float, str, list[str]]

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        if not _METADATA_KEY.match(v):
            raise ValueError("metadata key must be letters, digits or _ and start with a letter")
        return v

    @field_validator("value")
    @classmethod
    def _value(cls, v):
        if isinstance(v, str) and len(v) > 256:
            raise ValueError("metadata string values are limited to 256 characters")
        if isinstance(v, list) and (len(v) > 20 or any(len(s) > 256 for s in v)):
            raise ValueError("metadata lists are limited to 20 items of 256 characters")
        return v


class UploadOptions(BaseModel):
    display_name: Optional[str] = Field(None, max_length=512)
    chunking: ChunkingParams = ChunkingParams()
    metadata: list[MetadataEntry] = Field(default_factory=list, max_length=20)


class UploadJob(BaseModel):
    job_id: str
    filename: str
    display_name: str
    status: Literal["processing", "active", "failed"]
    document_name: Optional[str] = None
    error: Optional[str] = None
    max_tokens_per_chunk: int
    max_overlap_tokens: int
    created_at: float


class DocumentOut(BaseModel):
    name: str
    display_name: Optional[str]
    state: Optional[str]
    size_bytes: Optional[int]
    mime_type: Optional[str]
    created_at: Optional[str]
    metadata: dict[str, Union[float, str, list[str], None]] = {}


# -------------------------------------------------------------------- chat --


class HistoryTurn(BaseModel):
    role: Literal["user", "model"]
    text: str = Field(..., max_length=8000)


class GenerationParams(BaseModel):
    """Maps to google.genai.types.GenerateContentConfig. None = model default."""

    model: Optional[str] = Field(None, max_length=100)
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0)
    top_k: Optional[int] = Field(None, ge=1, le=100)
    max_output_tokens: Optional[int] = Field(None, ge=1, le=65536)
    system_instruction: Optional[str] = Field(None, max_length=4000)


class RetrievalParams(BaseModel):
    """Maps to google.genai.types.FileSearch."""

    top_k: Optional[int] = Field(None, ge=1, le=50, description="Chunks to retrieve")
    metadata_filter: Optional[str] = Field(None, max_length=1000)
    include_shared: bool = True
    include_mine: bool = True


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=8000)
    history: list[HistoryTurn] = Field(default_factory=list, max_length=20)
    generation: GenerationParams = GenerationParams()
    retrieval: RetrievalParams = RetrievalParams()


class Citation(BaseModel):
    title: Optional[str]
    text: Optional[str]
    page: Optional[int] = None
    source: Literal["shared", "mine", "unknown"] = "unknown"


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    model: str
    searched_stores: int
