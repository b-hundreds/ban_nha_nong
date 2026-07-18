"""Typed HTTP facade for the deterministic registry database tools."""
from fastapi import APIRouter

from app.backend import registry_service
from app.backend.schemas import (
    ProductRegistrantRequest,
    ProductRegistrantResponse,
    ProductRegistrationRequest,
    ProductRegistrationResponse,
    ProductStatusRequest,
    ProductStatusResponse,
    RegistrySearchRequest,
    RegistrySearchResponse,
)

router = APIRouter(prefix="/api/registry", tags=["registry-tools"])


@router.post("/products/search", response_model=RegistrySearchResponse)
def search_products(request: RegistrySearchRequest) -> RegistrySearchResponse:
    return registry_service.list_registered_products(request)


@router.post("/products/check-registration", response_model=ProductRegistrationResponse)
def check_registration(request: ProductRegistrationRequest) -> ProductRegistrationResponse:
    return registry_service.check_product_registration(request)


@router.post("/products/legal-status", response_model=ProductStatusResponse)
def legal_status(request: ProductStatusRequest) -> ProductStatusResponse:
    return registry_service.get_product_legal_status(request)


@router.post("/products/registrant", response_model=ProductRegistrantResponse)
def registrant(request: ProductRegistrantRequest) -> ProductRegistrantResponse:
    return registry_service.get_product_registrant(request)
