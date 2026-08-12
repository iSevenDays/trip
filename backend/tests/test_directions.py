"""Tests for Google Maps directions endpoints (R2: keyed on place names)."""

from datetime import date
from types import SimpleNamespace

import pytest

from trip.models.models import Category, Place, Trip, TripDay, TripItem, User
from trip.routers.directions import _build_stops, _build_url
from trip.security import create_access_token, hash_password


# ---------------------------------------------------------------------------
# Fixtures local to directions tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def sights_category(db, test_user):
    cat = Category(name="Sights", user=test_user["username"])
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def _make_place(db, user, category, name, lat, lng):
    place = Place(
        name=name,
        lat=lat,
        lng=lng,
        place="Somewhere",
        user=user,
        category_id=category.id,
    )
    db.add(place)
    db.commit()
    db.refresh(place)
    return place


def _make_item(db, day, time_, text, place_id=None, lat=None, lng=None):
    item = TripItem(time=time_, text=text, day_id=day.id, place_id=place_id, lat=lat, lng=lng)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


# ---------------------------------------------------------------------------
# _build_stops unit tests (verify R2 name-based selection)
# ---------------------------------------------------------------------------


class TestBuildStops:
    """The name-based selection rule: a place with a name is included even
    without coordinates (coords are not a gate)."""

    def test_named_place_without_coords_is_included(self):
        item = SimpleNamespace(
            id=1,
            time="09:00",
            place=SimpleNamespace(name="Hagia Sophia", lat=None, lng=None),
        )
        stops = _build_stops([item])
        assert len(stops) == 1
        assert stops[0].name == "Hagia Sophia"
        assert stops[0].lat is None  # coords not required for a name-based URL
        url = _build_url(stops)
        assert "Hagia%20Sophia" in url

    def test_item_without_place_is_omitted(self):
        item = SimpleNamespace(id=1, time="09:00", place=None)
        assert _build_stops([item]) == []

    def test_place_with_empty_name_is_omitted(self):
        item = SimpleNamespace(
            id=1, time="09:00", place=SimpleNamespace(name="", lat=1.0, lng=2.0)
        )
        assert _build_stops([item]) == []


# ---------------------------------------------------------------------------
# Day-level directions
# ---------------------------------------------------------------------------


class TestDayDirections:
    """GET /api/trips/{trip_id}/days/{day_id}/directions"""

    def test_three_named_places_in_time_order(self, client, test_user, db, sights_category):
        trip = Trip(name="Istanbul Trip", user=test_user["username"])
        db.add(trip)
        db.commit()
        db.refresh(trip)
        day = TripDay(label="Day 1", trip_id=trip.id, dt=date(2026, 4, 10))
        db.add(day)
        db.commit()
        db.refresh(day)

        p1 = _make_place(db, test_user["username"], sights_category, "Hagia Sophia", 41.0086, 28.9802)
        p2 = _make_place(db, test_user["username"], sights_category, "Basilica Cistern", 41.0084, 28.9775)
        p3 = _make_place(db, test_user["username"], sights_category, "Galata Tower", 41.0257, 28.9744)
        # Insert out of time order to verify sorting
        _make_item(db, day, "12:00", "Lunch", place_id=p2.id)
        _make_item(db, day, "09:00", "Morning", place_id=p1.id)
        _make_item(db, day, "18:00", "Evening", place_id=p3.id)

        resp = client.get(
            f"/api/trips/{trip.id}/days/{day.id}/directions",
            headers=test_user["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["stop_count"] == 3
        url = data["google_maps_url"]
        assert "/maps/dir/" in url
        # URL-encoded names present
        assert "Hagia%20Sophia" in url
        assert "Galata%20Tower" in url
        # Time order
        names = [s["name"] for s in data["stops"]]
        assert names == ["Hagia Sophia", "Basilica Cistern", "Galata Tower"]

    def test_item_without_place_is_omitted(self, client, test_user, db, sights_category):
        trip = Trip(name="T", user=test_user["username"])
        db.add(trip)
        db.commit()
        db.refresh(trip)
        day = TripDay(label="Day 1", trip_id=trip.id)
        db.add(day)
        db.commit()
        db.refresh(day)

        p = _make_place(db, test_user["username"], sights_category, "Named Place", 1.0, 2.0)
        _make_item(db, day, "09:00", "With place", place_id=p.id)
        _make_item(db, day, "10:00", "No place", place_id=None)  # omitted

        resp = client.get(
            f"/api/trips/{trip.id}/days/{day.id}/directions",
            headers=test_user["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["stop_count"] == 1
        assert data["stops"][0]["name"] == "Named Place"

    def test_order_param_overrides_time_sort(self, client, test_user, db, sights_category):
        trip = Trip(name="T", user=test_user["username"])
        db.add(trip)
        db.commit()
        db.refresh(trip)
        day = TripDay(label="Day 1", trip_id=trip.id)
        db.add(day)
        db.commit()
        db.refresh(day)

        p1 = _make_place(db, test_user["username"], sights_category, "Alpha", 1.0, 1.0)
        p2 = _make_place(db, test_user["username"], sights_category, "Beta", 2.0, 2.0)
        p3 = _make_place(db, test_user["username"], sights_category, "Gamma", 3.0, 3.0)
        i1 = _make_item(db, day, "09:00", "a", place_id=p1.id)
        i2 = _make_item(db, day, "10:00", "b", place_id=p2.id)
        i3 = _make_item(db, day, "11:00", "c", place_id=p3.id)

        # Request reverse-of-time order
        order = f"{i3.id},{i2.id},{i1.id}"
        resp = client.get(
            f"/api/trips/{trip.id}/days/{day.id}/directions?order={order}",
            headers=test_user["headers"],
        )
        assert resp.status_code == 200
        names = [s["name"] for s in resp.json()["stops"]]
        assert names == ["Gamma", "Beta", "Alpha"]

    def test_empty_day(self, client, test_user, db):
        trip = Trip(name="T", user=test_user["username"])
        db.add(trip)
        db.commit()
        db.refresh(trip)
        day = TripDay(label="Empty", trip_id=trip.id)
        db.add(day)
        db.commit()
        db.refresh(day)

        resp = client.get(
            f"/api/trips/{trip.id}/days/{day.id}/directions",
            headers=test_user["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["stop_count"] == 0
        assert data["stops"] == []
        assert data["google_maps_url"] == ""

    def test_day_not_found(self, client, test_user, db):
        trip = Trip(name="T", user=test_user["username"])
        db.add(trip)
        db.commit()
        db.refresh(trip)

        resp = client.get(
            f"/api/trips/{trip.id}/days/99999/directions",
            headers=test_user["headers"],
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Trip-level directions
# ---------------------------------------------------------------------------


class TestTripDirections:
    """GET /api/trips/{trip_id}/directions"""

    def test_returns_all_days_with_urls(self, client, test_user, db, sights_category):
        trip = Trip(name="Multi-day", user=test_user["username"])
        db.add(trip)
        db.commit()
        db.refresh(trip)

        day1 = TripDay(label="Day A", trip_id=trip.id, dt=date(2026, 5, 1))
        day2 = TripDay(label="Day B", trip_id=trip.id, dt=date(2026, 5, 2))
        db.add_all([day1, day2])
        db.commit()
        db.refresh(day1)
        db.refresh(day2)

        p1 = _make_place(db, test_user["username"], sights_category, "Stop One", 10.0, 20.0)
        p2 = _make_place(db, test_user["username"], sights_category, "Stop Two", 11.0, 21.0)
        _make_item(db, day1, "09:00", "s1", place_id=p1.id)
        _make_item(db, day1, "14:00", "s2", place_id=p2.id)
        _make_item(db, day2, "10:00", "s3", place_id=p1.id)

        resp = client.get(
            f"/api/trips/{trip.id}/directions",
            headers=test_user["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["days"]) == 2
        d1 = data["days"][0]
        assert d1["label"] == "Day A"
        assert d1["date"] == "2026-05-01"
        assert d1["stop_count"] == 2
        assert "Stop%20One" in d1["google_maps_url"]
        assert data["days"][1]["stop_count"] == 1

    def test_trip_with_no_days(self, client, test_user, db):
        trip = Trip(name="Empty", user=test_user["username"])
        db.add(trip)
        db.commit()
        db.refresh(trip)

        resp = client.get(
            f"/api/trips/{trip.id}/directions",
            headers=test_user["headers"],
        )
        assert resp.status_code == 200
        assert resp.json()["days"] == []


# ---------------------------------------------------------------------------
# Auth & ownership
# ---------------------------------------------------------------------------


class TestDirectionsAuth:
    """Unauthenticated / wrong-user access."""

    def test_unauthenticated_day_directions(self, client, db):
        user = User(username="owner", password=hash_password("pw"))
        db.add(user)
        db.commit()
        trip = Trip(name="T", user="owner")
        db.add(trip)
        db.commit()
        db.refresh(trip)
        day = TripDay(label="D", trip_id=trip.id)
        db.add(day)
        db.commit()
        db.refresh(day)

        resp = client.get(f"/api/trips/{trip.id}/days/{day.id}/directions")
        assert resp.status_code == 401

    def test_foreign_user_day_directions(self, client, db, test_user):
        """A non-member gets 404."""
        owner = User(username="owner3", password=hash_password("pw"))
        db.add(owner)
        db.commit()
        trip = Trip(name="T", user="owner3")
        db.add(trip)
        db.commit()
        db.refresh(trip)
        day = TripDay(label="D", trip_id=trip.id)
        db.add(day)
        db.commit()
        db.refresh(day)

        resp = client.get(
            f"/api/trips/{trip.id}/days/{day.id}/directions",
            headers=test_user["headers"],
        )
        assert resp.status_code == 404

    def test_trip_not_found(self, client, test_user):
        resp = client.get(
            "/api/trips/99999/directions",
            headers=test_user["headers"],
        )
        assert resp.status_code == 404
