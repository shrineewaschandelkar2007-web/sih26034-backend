from fastapi import APIRouter, Query

from app.core.errors import NotFoundError
from app.schemas.product import ReferenceProduct
from app.services import reference_service

router = APIRouter(prefix="/api/v1", tags=["products"])


@router.get("/products/search", response_model=list[ReferenceProduct])
def search_products(q: str = Query(min_length=1)):
    query = q.strip().lower()
    return [p for p in reference_service.list_reference_products() if query in p.brand.lower() or query in p.product_name.lower()]


@router.get("/products/{reference_product_id}", response_model=ReferenceProduct)
def get_product(reference_product_id: str):
    for p in reference_service.list_reference_products():
        if p.reference_product_id == reference_product_id:
            return p
    raise NotFoundError(f"Product {reference_product_id} not found.")
