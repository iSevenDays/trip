"""Route optimization: reorder a day's geo-located stops by nearest-neighbor.

Only the optimization section is extracted from upstream PR #240 `603ac53`
(which bundled it into a misleading exports.py alongside iCal export and
cost settlement). Those other sections are intentionally not ported.
"""

from math import atan2, cos, radians, sin, sqrt
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import selectinload
from sqlmodel import select

from ..deps import SessionDep, get_current_username
from ..models.models import TripItem
from ._helpers import verify_day_in_trip, verify_trip_ownership

router = APIRouter(prefix="/api/trips", tags=["optimization"])


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return distance in km between two lat/lng points."""
    R = 6371  # Earth radius in km
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def _total_distance(points: list[dict]) -> float:
    """Sum of haversine distances along a sequence of points."""
    total = 0.0
    for i in range(len(points) - 1):
        total += haversine(
            points[i]["lat"],
            points[i]["lng"],
            points[i + 1]["lat"],
            points[i + 1]["lng"],
        )
    return round(total, 2)


class OptimizePointRead(BaseModel):
    id: int
    name: str
    lat: float
    lng: float


class OptimizeResponse(BaseModel):
    original_order: list[OptimizePointRead]
    optimized_order: list[OptimizePointRead]
    original_distance_km: float
    optimized_distance_km: float
    savings_km: float


@router.post("/{trip_id}/days/{day_id}/optimize", response_model=OptimizeResponse)
def optimize_route(
    trip_id: int,
    day_id: int,
    session: SessionDep,
    current_user: Annotated[str, Depends(get_current_username)],
):
    verify_trip_ownership(session, trip_id, current_user)
    verify_day_in_trip(session, day_id, trip_id)

    items = session.exec(
        select(TripItem)
        .where(TripItem.day_id == day_id)
        .order_by(TripItem.time)
        .options(selectinload(TripItem.place))  # type: ignore[arg-type]
    ).all()

    # Build list of geolocated points
    points: list[dict] = []
    for item in items:
        lat = item.lat
        lng = item.lng
        if (lat is None or lng is None) and item.place:
            lat = item.place.lat
            lng = item.place.lng
        if lat is not None and lng is not None:
            points.append({"id": item.id, "name": item.text, "lat": lat, "lng": lng})

    if len(points) < 2:
        return OptimizeResponse(
            original_order=[OptimizePointRead(**p) for p in points],
            optimized_order=[OptimizePointRead(**p) for p in points],
            original_distance_km=0.0,
            optimized_distance_km=0.0,
            savings_km=0.0,
        )

    # Nearest-neighbor algorithm starting from the first point
    optimized: list[dict] = [points[0]]
    remaining = list(points[1:])
    while remaining:
        current = optimized[-1]
        nearest = min(
            remaining,
            key=lambda p: haversine(current["lat"], current["lng"], p["lat"], p["lng"]),
        )
        optimized.append(nearest)
        remaining.remove(nearest)

    original_dist = _total_distance(points)
    optimized_dist = _total_distance(optimized)

    return OptimizeResponse(
        original_order=[OptimizePointRead(**p) for p in points],
        optimized_order=[OptimizePointRead(**p) for p in optimized],
        original_distance_km=original_dist,
        optimized_distance_km=optimized_dist,
        savings_km=round(original_dist - optimized_dist, 2),
    )
