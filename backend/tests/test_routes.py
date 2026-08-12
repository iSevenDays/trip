"""Tests for Transport Routes CRUD router (ItemRoute, RouteOption)."""

import pytest

from sqlmodel import select

from trip.models.extensions import ItemRoute, RouteOption
from trip.models.models import TripItem
from trip.security import create_access_token, hash_password


# ---------------------------------------------------------------------------
# Helper: create a second TripItem for route endpoints
# ---------------------------------------------------------------------------


@pytest.fixture()
def second_item(db, test_trip_with_item, test_place):
    """Add a second TripItem to the same day so we can create routes."""
    day = test_trip_with_item["day"]
    item = TripItem(
        time="10:00",
        text="Visit park",
        day_id=day.id,
        place_id=test_place.id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@pytest.fixture()
def second_user(db) -> dict:
    """A second, unrelated user (no membership in the test trip) for auth checks."""
    from trip.models.models import User

    u = User(username="otheruser", password=hash_password("otherpass123"))
    db.add(u)
    db.commit()
    db.refresh(u)
    token = create_access_token({"sub": u.username})
    return {"username": u.username, "headers": {"Authorization": f"Bearer {token}"}}


# ---------------------------------------------------------------------------
# Helper: create a route via the API
# ---------------------------------------------------------------------------


def _create_route(client, trip_id, from_id, to_id, day_id, headers, **kwargs):
    payload = {
        "from_item_id": from_id,
        "to_item_id": to_id,
        "day_id": day_id,
        **kwargs,
    }
    return client.post(
        f"/api/trips/{trip_id}/routes",
        json=payload,
        headers=headers,
    )


# ---------------------------------------------------------------------------
# ItemRoute tests
# ---------------------------------------------------------------------------


class TestCreateRoute:
    """POST /api/trips/{trip_id}/routes"""

    def test_create_route(self, client, test_user, test_trip_with_item, second_item):
        trip = test_trip_with_item["trip"]
        day = test_trip_with_item["day"]
        item_a = test_trip_with_item["item"]
        item_b = second_item

        resp = _create_route(
            client,
            trip.id,
            item_a.id,
            item_b.id,
            day.id,
            test_user["headers"],
            recommended_mode="walking",
            notes="Short walk",
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["from_item_id"] == item_a.id
        assert data["to_item_id"] == item_b.id
        assert data["day_id"] == day.id
        assert data["recommended_mode"] == "walking"
        assert data["notes"] == "Short walk"
        assert "id" in data

    def test_create_route_minimal(self, client, test_user, test_trip_with_item, second_item):
        trip = test_trip_with_item["trip"]
        day = test_trip_with_item["day"]
        resp = _create_route(
            client,
            trip.id,
            test_trip_with_item["item"].id,
            second_item.id,
            day.id,
            test_user["headers"],
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["recommended_mode"] is None
        assert data["notes"] is None

    def test_create_route_trip_not_found(self, client, test_user, test_trip_with_item, second_item):
        day = test_trip_with_item["day"]
        resp = _create_route(
            client,
            99999,
            test_trip_with_item["item"].id,
            second_item.id,
            day.id,
            test_user["headers"],
        )
        assert resp.status_code == 404


class TestListRoutes:
    """GET /api/trips/{trip_id}/routes"""

    def test_list_routes(self, client, test_user, test_trip_with_item, second_item):
        trip = test_trip_with_item["trip"]
        day = test_trip_with_item["day"]
        item_a = test_trip_with_item["item"]
        item_b = second_item

        _create_route(client, trip.id, item_a.id, item_b.id, day.id, test_user["headers"])
        _create_route(client, trip.id, item_b.id, item_a.id, day.id, test_user["headers"])

        resp = client.get(
            f"/api/trips/{trip.id}/routes",
            headers=test_user["headers"],
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_list_routes_empty(self, client, test_user, test_trip_with_item):
        trip = test_trip_with_item["trip"]
        resp = client.get(
            f"/api/trips/{trip.id}/routes",
            headers=test_user["headers"],
        )
        assert resp.status_code == 200
        assert resp.json() == []


class TestGetRoute:
    """GET /api/trips/{trip_id}/routes/{route_id}"""

    def test_get_route(self, client, test_user, test_trip_with_item, second_item):
        trip = test_trip_with_item["trip"]
        day = test_trip_with_item["day"]
        create_resp = _create_route(
            client,
            trip.id,
            test_trip_with_item["item"].id,
            second_item.id,
            day.id,
            test_user["headers"],
            recommended_mode="transit",
        )
        route_id = create_resp.json()["id"]

        resp = client.get(
            f"/api/trips/{trip.id}/routes/{route_id}",
            headers=test_user["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == route_id
        assert data["recommended_mode"] == "transit"
        assert "options" in data

    def test_get_route_not_found(self, client, test_user, test_trip_with_item):
        trip = test_trip_with_item["trip"]
        resp = client.get(
            f"/api/trips/{trip.id}/routes/99999",
            headers=test_user["headers"],
        )
        assert resp.status_code == 404


class TestDeleteRoute:
    """DELETE /api/trips/{trip_id}/routes/{route_id}"""

    def test_delete_route(self, client, test_user, test_trip_with_item, second_item):
        trip = test_trip_with_item["trip"]
        day = test_trip_with_item["day"]
        create_resp = _create_route(
            client,
            trip.id,
            test_trip_with_item["item"].id,
            second_item.id,
            day.id,
            test_user["headers"],
        )
        route_id = create_resp.json()["id"]

        resp = client.delete(
            f"/api/trips/{trip.id}/routes/{route_id}",
            headers=test_user["headers"],
        )
        assert resp.status_code == 204

        # Verify it's gone
        get_resp = client.get(
            f"/api/trips/{trip.id}/routes/{route_id}",
            headers=test_user["headers"],
        )
        assert get_resp.status_code == 404

    def test_delete_route_not_found(self, client, test_user, test_trip_with_item):
        trip = test_trip_with_item["trip"]
        resp = client.delete(
            f"/api/trips/{trip.id}/routes/99999",
            headers=test_user["headers"],
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# RouteOption tests
# ---------------------------------------------------------------------------


class TestCreateRouteOption:
    """POST /api/trips/{trip_id}/routes/{route_id}/options"""

    def test_create_option(self, client, test_user, test_trip_with_item, second_item):
        trip = test_trip_with_item["trip"]
        day = test_trip_with_item["day"]
        route_resp = _create_route(
            client,
            trip.id,
            test_trip_with_item["item"].id,
            second_item.id,
            day.id,
            test_user["headers"],
        )
        route_id = route_resp.json()["id"]

        resp = client.post(
            f"/api/trips/{trip.id}/routes/{route_id}/options",
            json={
                "mode": "bus",
                "duration_minutes": 25,
                "distance_km": 3.5,
                "cost": 2.50,
                "line_name": "Line 42",
                "notes": "Runs every 10 min",
                "recommended": True,
            },
            headers=test_user["headers"],
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["mode"] == "bus"
        assert data["duration_minutes"] == 25
        assert data["distance_km"] == 3.5
        assert data["cost"] == 2.50
        assert data["line_name"] == "Line 42"
        assert data["notes"] == "Runs every 10 min"
        assert data["recommended"] is True
        assert data["route_id"] == route_id
        assert "id" in data

    def test_create_option_minimal(self, client, test_user, test_trip_with_item, second_item):
        trip = test_trip_with_item["trip"]
        day = test_trip_with_item["day"]
        route_resp = _create_route(
            client,
            trip.id,
            test_trip_with_item["item"].id,
            second_item.id,
            day.id,
            test_user["headers"],
        )
        route_id = route_resp.json()["id"]

        resp = client.post(
            f"/api/trips/{trip.id}/routes/{route_id}/options",
            json={"mode": "walk"},
            headers=test_user["headers"],
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["mode"] == "walk"
        assert data["duration_minutes"] is None
        assert data["recommended"] is False

    def test_create_option_invalid_mode(self, client, test_user, test_trip_with_item, second_item):
        """mode outside ROUTE_MODES is rejected with 422."""
        trip = test_trip_with_item["trip"]
        day = test_trip_with_item["day"]
        route_resp = _create_route(
            client,
            trip.id,
            test_trip_with_item["item"].id,
            second_item.id,
            day.id,
            test_user["headers"],
        )
        route_id = route_resp.json()["id"]

        resp = client.post(
            f"/api/trips/{trip.id}/routes/{route_id}/options",
            json={"mode": "teleport"},
            headers=test_user["headers"],
        )
        assert resp.status_code == 422

    def test_create_option_route_not_found(self, client, test_user, test_trip_with_item):
        trip = test_trip_with_item["trip"]
        resp = client.post(
            f"/api/trips/{trip.id}/routes/99999/options",
            json={"mode": "bus"},
            headers=test_user["headers"],
        )
        assert resp.status_code == 404


class TestListRouteOptions:
    """GET /api/trips/{trip_id}/routes/{route_id}/options"""

    def test_list_options(self, client, test_user, test_trip_with_item, second_item):
        trip = test_trip_with_item["trip"]
        day = test_trip_with_item["day"]
        route_resp = _create_route(
            client,
            trip.id,
            test_trip_with_item["item"].id,
            second_item.id,
            day.id,
            test_user["headers"],
        )
        route_id = route_resp.json()["id"]

        client.post(
            f"/api/trips/{trip.id}/routes/{route_id}/options",
            json={"mode": "bus"},
            headers=test_user["headers"],
        )
        client.post(
            f"/api/trips/{trip.id}/routes/{route_id}/options",
            json={"mode": "metro"},
            headers=test_user["headers"],
        )

        resp = client.get(
            f"/api/trips/{trip.id}/routes/{route_id}/options",
            headers=test_user["headers"],
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_list_options_empty(self, client, test_user, test_trip_with_item, second_item):
        trip = test_trip_with_item["trip"]
        day = test_trip_with_item["day"]
        route_resp = _create_route(
            client,
            trip.id,
            test_trip_with_item["item"].id,
            second_item.id,
            day.id,
            test_user["headers"],
        )
        route_id = route_resp.json()["id"]

        resp = client.get(
            f"/api/trips/{trip.id}/routes/{route_id}/options",
            headers=test_user["headers"],
        )
        assert resp.status_code == 200
        assert resp.json() == []


class TestUpdateRoute:
    """PATCH endpoints (R1 update requirement, added beyond the PR)."""

    def test_update_route(self, client, test_user, test_trip_with_item, second_item):
        trip = test_trip_with_item["trip"]
        day = test_trip_with_item["day"]
        route_id = _create_route(
            client,
            trip.id,
            test_trip_with_item["item"].id,
            second_item.id,
            day.id,
            test_user["headers"],
            recommended_mode="walk",
            notes="old",
        ).json()["id"]

        resp = client.patch(
            f"/api/trips/{trip.id}/routes/{route_id}",
            json={"recommended_mode": "bus", "notes": "new notes"},
            headers=test_user["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["recommended_mode"] == "bus"
        assert data["notes"] == "new notes"

        # Read-back matches
        get = client.get(
            f"/api/trips/{trip.id}/routes/{route_id}",
            headers=test_user["headers"],
        )
        assert get.json()["recommended_mode"] == "bus"
        assert get.json()["notes"] == "new notes"

    def test_update_route_partial(self, client, test_user, test_trip_with_item, second_item):
        """PATCH with one field leaves the other unchanged."""
        trip = test_trip_with_item["trip"]
        day = test_trip_with_item["day"]
        route_id = _create_route(
            client,
            trip.id,
            test_trip_with_item["item"].id,
            second_item.id,
            day.id,
            test_user["headers"],
            recommended_mode="walk",
            notes="keep me",
        ).json()["id"]

        resp = client.patch(
            f"/api/trips/{trip.id}/routes/{route_id}",
            json={"recommended_mode": "metro"},
            headers=test_user["headers"],
        )
        assert resp.status_code == 200
        assert resp.json()["recommended_mode"] == "metro"
        assert resp.json()["notes"] == "keep me"

    def test_update_route_not_found(self, client, test_user, test_trip_with_item):
        trip = test_trip_with_item["trip"]
        resp = client.patch(
            f"/api/trips/{trip.id}/routes/99999",
            json={"notes": "x"},
            headers=test_user["headers"],
        )
        assert resp.status_code == 404

    def test_update_option(self, client, test_user, test_trip_with_item, second_item):
        trip = test_trip_with_item["trip"]
        day = test_trip_with_item["day"]
        route_id = _create_route(
            client,
            trip.id,
            test_trip_with_item["item"].id,
            second_item.id,
            day.id,
            test_user["headers"],
        ).json()["id"]
        option_id = client.post(
            f"/api/trips/{trip.id}/routes/{route_id}/options",
            json={"mode": "bus"},
            headers=test_user["headers"],
        ).json()["id"]

        resp = client.patch(
            f"/api/trips/{trip.id}/routes/{route_id}/options/{option_id}",
            json={"mode": "metro", "duration_minutes": 12, "distance_km": 4.2},
            headers=test_user["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "metro"
        assert data["duration_minutes"] == 12
        assert data["distance_km"] == 4.2

    def test_update_option_invalid_mode(self, client, test_user, test_trip_with_item, second_item):
        """An out-of-range mode on PATCH is rejected with 422."""
        trip = test_trip_with_item["trip"]
        day = test_trip_with_item["day"]
        route_id = _create_route(
            client,
            trip.id,
            test_trip_with_item["item"].id,
            second_item.id,
            day.id,
            test_user["headers"],
        ).json()["id"]
        option_id = client.post(
            f"/api/trips/{trip.id}/routes/{route_id}/options",
            json={"mode": "bus"},
            headers=test_user["headers"],
        ).json()["id"]

        resp = client.patch(
            f"/api/trips/{trip.id}/routes/{route_id}/options/{option_id}",
            json={"mode": "spaceship"},
            headers=test_user["headers"],
        )
        assert resp.status_code == 422

    def test_update_option_not_found(self, client, test_user, test_trip_with_item, second_item):
        trip = test_trip_with_item["trip"]
        day = test_trip_with_item["day"]
        route_id = _create_route(
            client,
            trip.id,
            test_trip_with_item["item"].id,
            second_item.id,
            day.id,
            test_user["headers"],
        ).json()["id"]

        resp = client.patch(
            f"/api/trips/{trip.id}/routes/{route_id}/options/99999",
            json={"mode": "bus"},
            headers=test_user["headers"],
        )
        assert resp.status_code == 404


class TestDeleteRouteOption:
    """DELETE /api/trips/{trip_id}/routes/{route_id}/options/{option_id}"""

    def test_delete_option(self, client, test_user, test_trip_with_item, second_item):
        trip = test_trip_with_item["trip"]
        day = test_trip_with_item["day"]
        route_resp = _create_route(
            client,
            trip.id,
            test_trip_with_item["item"].id,
            second_item.id,
            day.id,
            test_user["headers"],
        )
        route_id = route_resp.json()["id"]

        option_resp = client.post(
            f"/api/trips/{trip.id}/routes/{route_id}/options",
            json={"mode": "bus"},
            headers=test_user["headers"],
        )
        option_id = option_resp.json()["id"]

        resp = client.delete(
            f"/api/trips/{trip.id}/routes/{route_id}/options/{option_id}",
            headers=test_user["headers"],
        )
        assert resp.status_code == 204

        # Verify it's gone
        list_resp = client.get(
            f"/api/trips/{trip.id}/routes/{route_id}/options",
            headers=test_user["headers"],
        )
        assert list_resp.json() == []

    def test_delete_option_not_found(self, client, test_user, test_trip_with_item, second_item):
        trip = test_trip_with_item["trip"]
        day = test_trip_with_item["day"]
        route_resp = _create_route(
            client,
            trip.id,
            test_trip_with_item["item"].id,
            second_item.id,
            day.id,
            test_user["headers"],
        )
        route_id = route_resp.json()["id"]

        resp = client.delete(
            f"/api/trips/{trip.id}/routes/{route_id}/options/99999",
            headers=test_user["headers"],
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Cascade
# ---------------------------------------------------------------------------


class TestRoutesCascade:
    """Deleting a route drops its options; deleting an item drops referencing routes."""

    def test_delete_route_drops_options(
        self, client, db, test_user, test_trip_with_item, second_item
    ):
        trip = test_trip_with_item["trip"]
        day = test_trip_with_item["day"]
        route_id = _create_route(
            client,
            trip.id,
            test_trip_with_item["item"].id,
            second_item.id,
            day.id,
            test_user["headers"],
        ).json()["id"]
        client.post(
            f"/api/trips/{trip.id}/routes/{route_id}/options",
            json={"mode": "bus"},
            headers=test_user["headers"],
        )

        client.delete(
            f"/api/trips/{trip.id}/routes/{route_id}",
            headers=test_user["headers"],
        )

        # Assert the RouteOption rows were actually cascade-deleted, not just
        # that the listing endpoint 404s (which only proves the parent route is
        # gone). Requires PRAGMA foreign_keys=ON, now set in conftest.
        leftover = db.exec(
            select(RouteOption).where(RouteOption.route_id == route_id)
        ).all()
        assert leftover == []

    def test_delete_item_cascades_routes(
        self, db, test_trip_with_item, second_item
    ):
        """FK CASCADE: deleting a TripItem removes ItemRoute rows referencing it."""
        day = test_trip_with_item["day"]
        item = test_trip_with_item["item"]
        route = ItemRoute(
            from_item_id=item.id,
            to_item_id=second_item.id,
            day_id=day.id,
        )
        db.add(route)
        db.commit()
        db.refresh(route)
        route_id = route.id  # capture before the cascade delete invalidates the instance

        db.delete(item)
        db.commit()

        assert db.exec(select(ItemRoute).where(ItemRoute.id == route_id)).all() == []


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestRoutesAuth:
    """Unauthenticated access should return 401."""

    def test_unauthenticated_list_routes(self, client, test_trip_with_item):
        trip = test_trip_with_item["trip"]
        resp = client.get(f"/api/trips/{trip.id}/routes")
        assert resp.status_code == 401

    def test_unauthenticated_create_route(self, client, test_trip_with_item):
        trip = test_trip_with_item["trip"]
        resp = client.post(
            f"/api/trips/{trip.id}/routes",
            json={"from_item_id": 1, "to_item_id": 2, "day_id": 1},
        )
        assert resp.status_code == 401

    def test_unauthenticated_list_options(self, client, test_trip_with_item):
        trip = test_trip_with_item["trip"]
        resp = client.get(f"/api/trips/{trip.id}/routes/1/options")
        assert resp.status_code == 401


class TestRoutesForeignUser:
    """A foreign user (no membership) gets 404 on every route and option endpoint."""

    def test_foreign_list_routes(self, client, second_user, test_trip_with_item):
        trip = test_trip_with_item["trip"]
        resp = client.get(f"/api/trips/{trip.id}/routes", headers=second_user["headers"])
        assert resp.status_code == 404

    def test_foreign_create_route(
        self, client, second_user, test_trip_with_item, second_item
    ):
        trip = test_trip_with_item["trip"]
        day = test_trip_with_item["day"]
        resp = _create_route(
            client,
            trip.id,
            test_trip_with_item["item"].id,
            second_item.id,
            day.id,
            second_user["headers"],
        )
        assert resp.status_code == 404

    def test_foreign_update_route(
        self, client, test_user, second_user, test_trip_with_item, second_item
    ):
        trip = test_trip_with_item["trip"]
        day = test_trip_with_item["day"]
        route_id = _create_route(
            client,
            trip.id,
            test_trip_with_item["item"].id,
            second_item.id,
            day.id,
            test_user["headers"],
        ).json()["id"]

        resp = client.patch(
            f"/api/trips/{trip.id}/routes/{route_id}",
            json={"notes": "hijack"},
            headers=second_user["headers"],
        )
        assert resp.status_code == 404

    def test_foreign_update_option(
        self, client, test_user, second_user, test_trip_with_item, second_item
    ):
        trip = test_trip_with_item["trip"]
        day = test_trip_with_item["day"]
        route_id = _create_route(
            client,
            trip.id,
            test_trip_with_item["item"].id,
            second_item.id,
            day.id,
            test_user["headers"],
        ).json()["id"]
        option_id = client.post(
            f"/api/trips/{trip.id}/routes/{route_id}/options",
            json={"mode": "bus"},
            headers=test_user["headers"],
        ).json()["id"]

        resp = client.patch(
            f"/api/trips/{trip.id}/routes/{route_id}/options/{option_id}",
            json={"mode": "metro"},
            headers=second_user["headers"],
        )
        assert resp.status_code == 404
