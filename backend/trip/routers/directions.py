"""Google Maps directions – build multi-stop URLs from trip-day items.

Adapted from PR #240 (`7010833` + place-names form `1339de7`). Two changes
per the plan (R2): (1) stop selection keys on place *names* — every item
whose place has a non-empty name is included regardless of coordinates, so
the PR's "skip items without coords" clause is dropped; (2) an optional
`order` query param (comma-separated item ids) builds the URL from exactly
those items in the given order, bypassing the time-sort, so an optimized
stop order can drive the directions link.
"""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import selectinload
from sqlmodel import select

from ..deps import SessionDep, get_current_username
from ..models.models import Trip, TripDay, TripItem
from ._helpers import verify_trip_ownership

router = APIRouter(prefix="/api/trips", tags=["directions"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class DirectionStop(BaseModel):
    name: str
    lat: float | None = None
    lng: float | None = None
    time: str | None = None


class DayDirectionsResponse(BaseModel):
    google_maps_url: str
    stops: list[DirectionStop]
    stop_count: int


class TripDayDirectionsSummary(BaseModel):
    day_id: int
    label: str
    date: str | None
    google_maps_url: str
    stop_count: int


class TripDirectionsResponse(BaseModel):
    days: list[TripDayDirectionsSummary]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_order(order: str | None) -> list[int] | None:
    """Parse a comma-separated item-id list. Invalid tokens are skipped."""
    if not order:
        return None
    ids: list[int] = []
    for token in order.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            ids.append(int(token))
        except ValueError:
            continue
    return ids or None


def _ordered_items(items: list[TripItem], order: list[int] | None) -> list[TripItem]:
    """Select and order items.

    With ``order`` set, keep only items whose id is in the list and sort by
    the list position (bypassing ``item.time``). Otherwise sort by ``item.time``.
    """
    if order is not None:
        position = {item_id: idx for idx, item_id in enumerate(order)}
        selected = [i for i in items if i.id in position]
        selected.sort(key=lambda i: position[i.id])
        return selected
    return sorted(items, key=lambda i: (i.time is None, i.time))


def _build_stops(items: list[TripItem], order: list[int] | None = None) -> list[DirectionStop]:
    """Return stops for items whose place has a non-empty name (R2: keyed on names)."""
    stops: list[DirectionStop] = []
    for item in _ordered_items(items, order):
        place = item.place
        if not place or not place.name:
            continue
        stops.append(
            DirectionStop(
                name=place.name,
                lat=place.lat,
                lng=place.lng,
                time=item.time,
            )
        )
    return stops


def _build_url(stops: list[DirectionStop]) -> str:
    if not stops:
        return ""
    parts = "/".join(quote(s.name, safe="") for s in stops)
    return f"https://www.google.com/maps/dir/{parts}"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{trip_id}/days/{day_id}/directions", response_model=DayDirectionsResponse)
def get_day_directions(
    trip_id: int,
    day_id: int,
    session: SessionDep,
    current_user: Annotated[str, Depends(get_current_username)],
    order: Annotated[str | None, Query(description="Comma-separated item ids;")] = None,
) -> DayDirectionsResponse:
    verify_trip_ownership(session, trip_id, current_user)

    day = session.exec(
        select(TripDay)
        .where(TripDay.id == day_id, TripDay.trip_id == trip_id)
        .options(selectinload(TripDay.items).selectinload(TripItem.place))  # type: ignore[arg-type]
    ).first()
    if not day:
        raise HTTPException(status_code=404, detail="Not found")

    stops = _build_stops(day.items, _parse_order(order))
    return DayDirectionsResponse(
        google_maps_url=_build_url(stops),
        stops=stops,
        stop_count=len(stops),
    )


@router.get("/{trip_id}/directions", response_model=TripDirectionsResponse)
def get_trip_directions(
    trip_id: int,
    session: SessionDep,
    current_user: Annotated[str, Depends(get_current_username)],
    order: Annotated[str | None, Query(description="Comma-separated item ids;")] = None,
) -> TripDirectionsResponse:
    verify_trip_ownership(session, trip_id, current_user)

    parsed_order = _parse_order(order)

    # Eagerly load days -> items -> place
    trip = session.exec(
        select(Trip)
        .where(Trip.id == trip_id)
        .options(
            selectinload(Trip.days)  # type: ignore[arg-type]
            .selectinload(TripDay.items)  # type: ignore[arg-type]
            .selectinload(TripItem.place)  # type: ignore[arg-type]
        )
    ).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Not found")

    summaries: list[TripDayDirectionsSummary] = []
    for day in trip.days:
        stops = _build_stops(day.items, parsed_order)
        summaries.append(
            TripDayDirectionsSummary(
                day_id=day.id,
                label=day.label,
                date=str(day.dt) if day.dt else None,
                google_maps_url=_build_url(stops),
                stop_count=len(stops),
            )
        )

    return TripDirectionsResponse(days=summaries)
