from fastapi import APIRouter

router = APIRouter(prefix="", tags=["health"])


@router.get("/health")
async def health():
    return {"status": "ok", "service": "adelia-api"}
