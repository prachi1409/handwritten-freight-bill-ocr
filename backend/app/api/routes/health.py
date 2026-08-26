"""Health check endpoint router."""

from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health")
def health_check():
    """Health check endpoint.

    Returns:
        JSON object indicating API operational status.
    """
    return {"status": "ok"}

