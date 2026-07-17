"""Pydantic schemas cho API contract — xem .superpowers/sdd/app-skeleton-brief.md."""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

Region = Literal["an_giang", "dak_lak"]


class AskRequest(BaseModel):
    text: str
    region: Region
    session_id: str | None = None


class TextSegment(BaseModel):
    type: Literal["text"] = "text"
    content: str


class DoseBlockSegment(BaseModel):
    type: Literal["dose_block"] = "dose_block"
    product: str
    ai: str
    dose_text: str
    phi_days: int | None = None
    note: str
    source_url: str | None = None


class CitationSegment(BaseModel):
    type: Literal["citation"] = "citation"
    source: str
    url: str


class AbstainSegment(BaseModel):
    type: Literal["abstain"] = "abstain"
    reason: str
    handoff: bool = True


AnswerSegment = Annotated[
    Union[TextSegment, DoseBlockSegment, CitationSegment, AbstainSegment],
    Field(discriminator="type"),
]


class Slots(BaseModel):
    crop: str | None = None
    pest: str | None = None
    region: Region


class ProductOut(BaseModel):
    trade_name: str
    formulation: str | None = None
    active_ingredient: str
    cite: str


class AskResponse(BaseModel):
    risk_class: Literal["A", "B", "C"]
    answer_segments: list[AnswerSegment]
    slots: Slots
    products: list[ProductOut] = Field(default_factory=list)


class TranscribeResponse(BaseModel):
    text: str


class HandoffRequest(BaseModel):
    session_id: str | None = None
    transcript: str
    slots: Slots


class HandoffResponse(BaseModel):
    ticket_id: int
