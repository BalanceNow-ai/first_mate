"""Product catalogue router with compatibility filtering."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.middleware.auth import CurrentUserId
from app.models.product import Product, ProductCompatibility
from app.models.vessel import Vessel
from app.schemas.product import (
    CompatibilityCheck,
    ProductCompatibilityCreate,
    ProductCompatibilityResponse,
    ProductCreate,
    ProductResponse,
    ProductUpdate,
)

router = APIRouter(prefix="/products", tags=["Products"])


@router.get("/", response_model=list[ProductResponse])
async def list_products(
    category: str | None = None,
    sub_category: str | None = None,
    brand: str | None = None,
    vessel_id: uuid.UUID | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    in_stock: bool | None = None,
    search: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[Product]:
    """List products with optional filtering by category, brand, and vessel compatibility."""
    query = select(Product).where(Product.is_active.is_(True))

    if category:
        query = query.where(Product.category == category)
    if sub_category:
        query = query.where(Product.sub_category == sub_category)
    if brand:
        query = query.where(Product.brand == brand)
    if min_price is not None:
        query = query.where(Product.price >= min_price)
    if max_price is not None:
        query = query.where(Product.price <= max_price)
    if in_stock:
        query = query.where(Product.stock_quantity > 0)
    if search:
        search_filter = f"%{search}%"
        query = query.where(
            or_(
                Product.name.ilike(search_filter),
                Product.description.ilike(search_filter),
                Product.sku.ilike(search_filter),
                Product.brand.ilike(search_filter),
            )
        )

    # Vessel compatibility filter
    if vessel_id:
        vessel_result = await db.execute(select(Vessel).where(Vessel.id == vessel_id))
        vessel = vessel_result.scalar_one_or_none()
        if vessel:
            query = query.join(ProductCompatibility).where(
                and_(
                    or_(
                        ProductCompatibility.vessel_make.is_(None),
                        ProductCompatibility.vessel_make == vessel.make,
                    ),
                    or_(
                        ProductCompatibility.vessel_model.is_(None),
                        ProductCompatibility.vessel_model == vessel.model,
                    ),
                    or_(
                        ProductCompatibility.year_from.is_(None),
                        ProductCompatibility.year_from <= vessel.year,
                    ),
                    or_(
                        ProductCompatibility.year_to.is_(None),
                        ProductCompatibility.year_to >= vessel.year,
                    ),
                )
            )

    query = query.offset(offset).limit(limit).order_by(Product.name)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Product:
    """Get a single product by ID."""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.get("/{product_id}/compatibility", response_model=list[ProductCompatibilityResponse])
async def get_product_compatibility(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[ProductCompatibility]:
    """Get all compatibility records for a product."""
    result = await db.execute(
        select(ProductCompatibility).where(ProductCompatibility.product_id == product_id)
    )
    return list(result.scalars().all())


@router.get("/{product_id}/check-compatibility", response_model=CompatibilityCheck)
async def check_product_compatibility(
    product_id: uuid.UUID,
    vessel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> CompatibilityCheck:
    """Check if a product is compatible with a specific vessel."""
    # Get the vessel
    vessel_result = await db.execute(select(Vessel).where(Vessel.id == vessel_id))
    vessel = vessel_result.scalar_one_or_none()
    if not vessel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vessel not found")

    # Check compatibility
    compat_result = await db.execute(
        select(ProductCompatibility).where(
            ProductCompatibility.product_id == product_id,
            or_(
                ProductCompatibility.vessel_make.is_(None),
                ProductCompatibility.vessel_make == vessel.make,
            ),
            or_(
                ProductCompatibility.vessel_model.is_(None),
                ProductCompatibility.vessel_model == vessel.model,
            ),
            or_(
                ProductCompatibility.year_from.is_(None),
                ProductCompatibility.year_from <= vessel.year,
            ),
            or_(
                ProductCompatibility.year_to.is_(None),
                ProductCompatibility.year_to >= vessel.year,
            ),
        )
    )
    compatibility = compat_result.scalar_one_or_none()

    if compatibility:
        return CompatibilityCheck(
            is_compatible=True,
            message=f"Fits {vessel.nickname} ({vessel.year} {vessel.make} {vessel.model})",
        )
    return CompatibilityCheck(
        is_compatible=False,
        message=f"Does not fit {vessel.nickname} ({vessel.year} {vessel.make} {vessel.model})",
    )


# --- Admin endpoints ---


@router.post("/", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    product_data: ProductCreate,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> Product:
    """Create a new product (admin only)."""
    product = Product(**product_data.model_dump())
    db.add(product)
    await db.flush()
    return product


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: uuid.UUID,
    updates: ProductUpdate,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> Product:
    """Update a product (admin only)."""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    update_data = updates.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(product, field, value)

    await db.flush()
    return product


@router.post(
    "/{product_id}/compatibility",
    response_model=ProductCompatibilityResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_product_compatibility(
    product_id: uuid.UUID,
    compat_data: ProductCompatibilityCreate,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> ProductCompatibility:
    """Add a compatibility record to a product (admin only)."""
    compatibility = ProductCompatibility(product_id=product_id, **compat_data.model_dump(exclude={"product_id"}))
    db.add(compatibility)
    await db.flush()
    return compatibility
