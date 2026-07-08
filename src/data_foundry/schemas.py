"""Pydantic schemas for the two final datasets.

Used as the data-quality gate at assembly time: any record that doesn't
conform is reported (not silently dropped) in the run manifest.
"""

from pydantic import BaseModel, field_validator


class LocalizedTitle(BaseModel):
    pt: str
    en: str | None = None
    es: str | None = None
    fr: str | None = None


class LocalizedDescription(BaseModel):
    pt: str | None = None
    en: str | None = None
    es: str | None = None
    fr: str | None = None


class LocalizedCatalogEntry(BaseModel):
    id: str
    title: LocalizedTitle
    description: LocalizedDescription
    author: str | None = None
    source: str | None = None

    @field_validator("id")
    @classmethod
    def id_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("id must not be empty")
        return v


class UniversalMetadataEntry(BaseModel):
    id: str
    document_hash: str | None = None
    cover_path: str | None = None
    cover_hash: str | None = None
    accesses: int | None = None
    size_bytes: int | None = None
    category: str | None = None
    year: str | None = None

    @field_validator("id")
    @classmethod
    def id_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("id must not be empty")
        return v
