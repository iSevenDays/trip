"""Routes extension models.

Surgical extraction of the transport-routes slice from upstream PR #240
(`d3b4aab`). Only `ItemRoute` and `RouteOption` are ported — the other
Phase-2 models (restaurants, reservations, budget, flights, weather, etc.)
are intentionally NOT included, so no dormant tables ship. See KTD1.
"""

from sqlmodel import Field, Relationship, SQLModel

from .models import TripDay, TripItem  # noqa: F401 – needed for FK resolution


class ItemRoute(SQLModel, table=True):
    __tablename__ = "item_route"

    id: int | None = Field(default=None, primary_key=True)
    from_item_id: int = Field(
        foreign_key="tripitem.id",
        index=True,
        ondelete="CASCADE",
    )
    to_item_id: int = Field(
        foreign_key="tripitem.id",
        index=True,
        ondelete="CASCADE",
    )
    day_id: int = Field(
        foreign_key="tripday.id",
        index=True,
        ondelete="CASCADE",
    )

    recommended_mode: str | None = None
    notes: str | None = None

    from_item: TripItem | None = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[ItemRoute.from_item_id]"},
    )
    to_item: TripItem | None = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[ItemRoute.to_item_id]"},
    )
    day: TripDay | None = Relationship()


class RouteOption(SQLModel, table=True):
    __tablename__ = "route_option"

    id: int | None = Field(default=None, primary_key=True)
    route_id: int = Field(
        foreign_key="item_route.id",
        index=True,
        ondelete="CASCADE",
    )

    mode: str
    duration_minutes: int | None = None
    distance_km: float | None = None
    cost: float | None = None
    line_name: str | None = None
    notes: str | None = None
    recommended: bool | None = False

    route: ItemRoute | None = Relationship()
