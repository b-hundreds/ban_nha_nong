"""Pydantic schemas cho API contract — xem .superpowers/sdd/app-skeleton-brief.md."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

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
    registrant: str | None = None


class AskResponse(BaseModel):
    risk_class: Literal["A", "B", "C"]
    answer_segments: list[AnswerSegment]
    slots: Slots
    products: list[ProductOut] = Field(default_factory=list)


class TranscribeResponse(BaseModel):
    text: str


class TtsRequest(BaseModel):
    text: str = Field(min_length=1)


class HandoffRequest(BaseModel):
    session_id: str | None = None
    transcript: str
    slots: Slots


class HandoffResponse(BaseModel):
    ticket_id: int


# Registry tool/API contracts. These are intentionally narrow: callers cannot
# submit SQL and the LLM planner is never allowed to populate these arguments.
class _RegistryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegistryProduct(BaseModel):
    product_id: int
    trade_name: str
    formulation: str | None = None
    active_ingredient: str
    registrant: str | None = None
    status: str
    cite: str
    source_url: str


class RegistryUse(BaseModel):
    crop: str
    pest: str


class RegistryDose(BaseModel):
    dose_text: str
    water_text: str | None = None
    phi_days: int | None = None
    method: str | None = None
    source_url: str


class RegistrySearchRequest(_RegistryRequest):
    crop: str = Field(min_length=1, max_length=100)
    pest: str = Field(min_length=1, max_length=160)
    on_date: date
    limit: int = Field(default=5, ge=1, le=20)


class RegistrySearchResponse(BaseModel):
    tool_name: Literal["list_registered_products"] = "list_registered_products"
    crop: str
    pest: str
    on_date: date
    total: int
    products: list[RegistryProduct]


class ProductRegistrationRequest(_RegistryRequest):
    trade_name: str = Field(min_length=1, max_length=160)
    formulation: str | None = Field(default=None, max_length=50)
    crop: str = Field(min_length=1, max_length=100)
    pest: str = Field(min_length=1, max_length=160)
    on_date: date


class ProductRegistrationResponse(BaseModel):
    tool_name: Literal["check_product_registration"] = "check_product_registration"
    trade_name: str
    formulation: str | None = None
    crop: str
    pest: str
    on_date: date
    resolution: Literal["registered", "not_registered", "not_found", "ambiguous", "unavailable"]
    legal_status: Literal["allowed", "transitional", "removed", "banned", "unknown"]
    product: RegistryProduct | None = None
    registered_uses: list[RegistryUse] = Field(default_factory=list)
    dose: RegistryDose | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    future_effective_from: date | None = None
    future_cite: str | None = None
    future_source_url: str | None = None
    reason_code: str


class ProductStatusRequest(_RegistryRequest):
    trade_name: str = Field(min_length=1, max_length=160)
    formulation: str | None = Field(default=None, max_length=50)
    on_date: date


class ProductStatusResponse(BaseModel):
    tool_name: Literal["get_product_legal_status"] = "get_product_legal_status"
    trade_name: str
    formulation: str | None = None
    on_date: date
    resolution: Literal["found", "not_found", "ambiguous"]
    legal_status: Literal["allowed", "transitional", "removed", "banned", "unknown"]
    product: RegistryProduct | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    future_effective_from: date | None = None
    future_cite: str | None = None
    future_source_url: str | None = None
    reason_code: str


class ProductRegistrantRequest(_RegistryRequest):
    trade_name: str = Field(min_length=1, max_length=160)
    formulation: str | None = Field(default=None, max_length=50)
    on_date: date


class ProductRegistrantResponse(BaseModel):
    tool_name: Literal["get_product_registrant"] = "get_product_registrant"
    trade_name: str
    formulation: str | None = None
    on_date: date
    resolution: Literal["found", "not_found", "ambiguous"]
    product: RegistryProduct | None = None
    registrant: str | None = None
    reason_code: str
