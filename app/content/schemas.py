from __future__ import annotations

from datetime import date
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class ContentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentCreate(ContentRequest):
    doc_key: str = Field(min_length=1, max_length=200)
    doc_type: Literal[
        "course",
        "category",
        "programme",
        "page",
        "service",
        "faq",
        "contact",
        "fact",
    ]
    title: str = Field(min_length=1, max_length=300)
    url_path: str | None = Field(default=None, max_length=500)
    aliases: list[str] = Field(default_factory=list, max_length=50)


class DocumentPatch(ContentRequest):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    url_path: str | None = Field(default=None, max_length=500)
    aliases: list[str] | None = Field(default=None, max_length=50)


class ChunkCreate(ContentRequest):
    chunk_key: str = Field(min_length=1, max_length=250)
    doc_key: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=20, max_length=8192)
    embed_text: str | None = Field(default=None, max_length=8192)
    metadata: dict[str, Any] = Field(default_factory=dict)
    change_note: str | None = Field(default=None, max_length=500)


class ChunkPatch(ContentRequest):
    text: str | None = Field(default=None, min_length=20, max_length=8192)
    embed_text: str | None = Field(default=None, max_length=8192)
    metadata: dict[str, Any] | None = None
    change_note: str = Field(min_length=1, max_length=500)
    trace_id: UUID | None = None


class LinkCreate(ContentRequest):
    link_key: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=200)
    url: HttpUrl
    description: str = Field(default="", max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    doc_key: str | None = Field(default=None, max_length=200)
    priority: int = Field(default=50, ge=0, le=1000)
    active: bool = True


class LinkPatch(ContentRequest):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    url: HttpUrl | None = None
    description: str | None = Field(default=None, max_length=200)
    aliases: list[str] | None = Field(default=None, max_length=50)
    doc_key: str | None = Field(default=None, max_length=200)
    priority: int | None = Field(default=None, ge=0, le=1000)
    active: bool | None = None


class FAQCreate(ContentRequest):
    question: str = Field(min_length=5, max_length=500)
    answer: str = Field(min_length=1, max_length=6000)
    variants: list[str] = Field(default_factory=list, max_length=20)
    link_keys: list[str] = Field(default_factory=list, max_length=10)
    tags: list[str] = Field(default_factory=list, max_length=20)
    direct: bool = True
    review_after: date | None = None
    watch: list[Literal["course_count", "category_count", "programme_count"]] = Field(
        default_factory=list,
        max_length=3,
    )
    publish: bool = False

    @field_validator("question", "answer")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Text cannot be blank")
        return normalized


class FAQPatch(ContentRequest):
    question: str | None = Field(default=None, min_length=5, max_length=500)
    answer: str | None = Field(default=None, min_length=1, max_length=6000)
    variants: list[str] | None = Field(default=None, max_length=20)
    link_keys: list[str] | None = Field(default=None, max_length=10)
    tags: list[str] | None = Field(default=None, max_length=20)
    direct: bool | None = None
    review_after: date | None = None
    watch: list[Literal["course_count", "category_count", "programme_count"]] | None = None


class FAQBulkRequest(ContentRequest):
    items: list[FAQCreate] = Field(min_length=1, max_length=200)
    partial: bool = False
