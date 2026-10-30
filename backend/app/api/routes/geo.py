from fastapi import APIRouter
from pydantic import BaseModel
from app.domain.geo import REGION_TO_DISTRICT

router = APIRouter(prefix="/geo", tags=["geo"])

class RegionRead(BaseModel):
    name: str
    federal_district: str

@router.get("/regions", response_model=list[RegionRead])
async def list_regions() -> list[RegionRead]:
    """Справочник регионов для выпадающего списка на фронте."""
    return [
        RegionRead(name=name, federal_district=district)
        for name, district in sorted(REGION_TO_DISTRICT.items())
    ]
