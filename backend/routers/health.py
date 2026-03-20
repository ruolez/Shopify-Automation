"""Health check endpoints"""
from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/")
async def root():
    return {"message": "Shopify Multi-Store Order Management API", "status": "running"}


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "api"}
