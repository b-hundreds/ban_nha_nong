"""Deterministic database service shared by FastAPI and the LLM tool executor.

The LLM never sends SQL and never supplies entity arguments.  It may select a
tool name; this module receives canonical arguments injected by the backend and
performs parameterized, exact database queries.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator

from app.backend import db as db_module
from app.backend import product_guard
from app.backend.schemas import (
    ProductRegistrantRequest,
    ProductRegistrantResponse,
    ProductRegistrationRequest,
    ProductRegistrationResponse,
    ProductStatusRequest,
    ProductStatusResponse,
    RegistryDose,
    RegistryProduct,
    RegistrySearchRequest,
    RegistrySearchResponse,
    RegistryUse,
)

LABELS_DB_PATH = Path("data/labels.db")


@contextmanager
def _connection(existing: sqlite3.Connection | None = None) -> Iterator[sqlite3.Connection]:
    conn = existing or db_module.connect()
    try:
        yield conn
    finally:
        if existing is None:
            conn.close()


def _clean(value: str | None) -> str | None:
    return " ".join(value.split()) if value else None


def _product(hit: db_module.ProductHit | None) -> RegistryProduct | None:
    if hit is None:
        return None
    return RegistryProduct(
        product_id=hit.product_id,
        trade_name=hit.trade_name,
        formulation=hit.formulation,
        active_ingredient=hit.active_ingredient,
        registrant=_clean(hit.registrant),
        status=hit.status,
        cite=hit.cite,
        source_url=hit.source_url,
    )


def _resolve_exact_identity(
    conn: sqlite3.Connection,
    trade_name: str,
    formulation: str | None,
    on_date: str,
) -> tuple[str, db_module.ProductHit | None]:
    hits = db_module.lookup_exact_products(conn, trade_name, formulation, on_date)
    if not hits:
        return "not_found", None

    identities = {
        (hit.trade_name.casefold(), (hit.formulation or "").casefold(), hit.active_ingredient.casefold())
        for hit in hits
    }
    formulations = {(hit.formulation or "").casefold() for hit in hits}
    if len(identities) != 1 or (formulation is None and len(formulations) != 1):
        return "ambiguous", None
    return "found", hits[0]


def list_registered_products(
    request: RegistrySearchRequest,
    *,
    conn: sqlite3.Connection | None = None,
) -> RegistrySearchResponse:
    on_date = request.on_date.isoformat()
    with _connection(conn) as active:
        hits = db_module.lookup_products(active, request.crop, request.pest, on_date)
    return RegistrySearchResponse(
        crop=request.crop,
        pest=request.pest,
        on_date=request.on_date,
        total=len(hits),
        products=[_product(hit) for hit in hits[: request.limit] if hit is not None],
    )


def check_product_registration(
    request: ProductRegistrationRequest,
    *,
    conn: sqlite3.Connection | None = None,
) -> ProductRegistrationResponse:
    on_date = request.on_date.isoformat()
    with _connection(conn) as active:
        resolution, hit = _resolve_exact_identity(
            active, request.trade_name, request.formulation, on_date
        )
        if resolution != "found" or hit is None:
            return ProductRegistrationResponse(
                trade_name=request.trade_name,
                formulation=request.formulation,
                crop=request.crop,
                pest=request.pest,
                on_date=request.on_date,
                resolution=resolution,
                legal_status="unknown",
                reason_code=f"exact_product_{resolution}",
            )

        status = product_guard.evaluate_product(
            active, hit.trade_name, hit.formulation, on_date, request.crop
        )
        current_id = status.current_row["product_id"] if status.current_row is not None else hit.product_id
        current_hit = db_module.get_product_hit(active, current_id) or hit
        uses = [RegistryUse(crop=crop, pest=pest) for crop, pest in db_module.list_product_uses(active, current_id)]

        legal_status = {
            "ok": "allowed",
            "wrong_crop": "allowed",
            "transitional": "transitional",
            "removed": "removed",
            "banned": "banned",
            "unknown": "unknown",
        }.get(status.kind, "unknown")

        if status.kind not in {"ok", "wrong_crop"}:
            current = status.current_row
            future = status.future_row
            return ProductRegistrationResponse(
                trade_name=current_hit.trade_name,
                formulation=current_hit.formulation,
                crop=request.crop,
                pest=request.pest,
                on_date=request.on_date,
                resolution="unavailable",
                legal_status=legal_status,
                product=_product(current_hit),
                registered_uses=uses,
                effective_from=(
                    date.fromisoformat(current["effective_from"])
                    if current is not None else None
                ),
                effective_to=(
                    date.fromisoformat(current["effective_to"])
                    if current is not None and current["effective_to"] else None
                ),
                future_effective_from=(
                    date.fromisoformat(future["effective_from"])
                    if future is not None else None
                ),
                future_cite=(
                    f"Phụ lục Thông tư {future['so_hieu']} (hiệu lực từ {future['effective_from']})"
                    if future is not None else None
                ),
                future_source_url=future["source_url"] if future is not None else None,
                reason_code=f"product_{status.kind}",
            )

        registered = db_module.product_has_registered_use(
            active, current_id, request.crop, request.pest
        )

        dose_model = None
        if registered and LABELS_DB_PATH.exists():
            try:
                labels = db_module.connect_labels(str(LABELS_DB_PATH))
                try:
                    dose = db_module.get_dose(
                        labels,
                        current_hit.trade_name,
                        request.crop,
                        request.pest,
                        formulation=current_hit.formulation,
                    )
                finally:
                    labels.close()
            except sqlite3.Error:
                dose = None
            if dose is not None:
                dose_model = RegistryDose(
                    dose_text=dose.dose_text,
                    water_text=dose.water_text,
                    phi_days=dose.phi_days,
                    method=dose.method,
                    source_url=dose.source_url,
                )

        return ProductRegistrationResponse(
            trade_name=current_hit.trade_name,
            formulation=current_hit.formulation,
            crop=request.crop,
            pest=request.pest,
            on_date=request.on_date,
            resolution="registered" if registered else "not_registered",
            legal_status=legal_status,
            product=_product(current_hit),
            registered_uses=uses,
            dose=dose_model,
            reason_code="exact_use_registered" if registered else "exact_use_not_registered",
        )


def get_product_legal_status(
    request: ProductStatusRequest,
    *,
    conn: sqlite3.Connection | None = None,
) -> ProductStatusResponse:
    on_date = request.on_date.isoformat()
    with _connection(conn) as active:
        resolution, hit = _resolve_exact_identity(
            active, request.trade_name, request.formulation, on_date
        )
        if resolution != "found" or hit is None:
            return ProductStatusResponse(
                trade_name=request.trade_name,
                formulation=request.formulation,
                on_date=request.on_date,
                resolution=resolution,
                legal_status="unknown",
                reason_code=f"exact_product_{resolution}",
            )

        result = product_guard.evaluate_product(active, hit.trade_name, hit.formulation, on_date, None)
        current_id = result.current_row["product_id"] if result.current_row is not None else hit.product_id
        current_hit = db_module.get_product_hit(active, current_id) or hit
        legal_status = {
            "ok": "allowed",
            "transitional": "transitional",
            "removed": "removed",
            "banned": "banned",
        }.get(result.kind, "unknown")
        current = result.current_row
        future = result.future_row
        return ProductStatusResponse(
            trade_name=current_hit.trade_name,
            formulation=current_hit.formulation,
            on_date=request.on_date,
            resolution="found",
            legal_status=legal_status,
            product=_product(current_hit),
            effective_from=date.fromisoformat(current["effective_from"]) if current else None,
            effective_to=date.fromisoformat(current["effective_to"]) if current and current["effective_to"] else None,
            future_effective_from=(
                date.fromisoformat(future["effective_from"]) if future is not None else None
            ),
            future_cite=(
                f"Phụ lục Thông tư {future['so_hieu']} (hiệu lực từ {future['effective_from']})"
                if future is not None else None
            ),
            future_source_url=future["source_url"] if future is not None else None,
            reason_code=f"product_{result.kind}",
        )


def get_product_registrant(
    request: ProductRegistrantRequest,
    *,
    conn: sqlite3.Connection | None = None,
) -> ProductRegistrantResponse:
    on_date = request.on_date.isoformat()
    with _connection(conn) as active:
        resolution, hit = _resolve_exact_identity(
            active, request.trade_name, request.formulation, on_date
        )
    if resolution != "found" or hit is None:
        return ProductRegistrantResponse(
            trade_name=request.trade_name,
            formulation=request.formulation,
            on_date=request.on_date,
            resolution=resolution,
            reason_code=f"exact_product_{resolution}",
        )
    return ProductRegistrantResponse(
        trade_name=hit.trade_name,
        formulation=hit.formulation,
        on_date=request.on_date,
        resolution="found",
        product=_product(hit),
        registrant=_clean(hit.registrant),
        reason_code="registrant_found" if hit.registrant else "registrant_missing",
    )
