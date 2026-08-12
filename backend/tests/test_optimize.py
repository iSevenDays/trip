"""Tests for the route optimization endpoint (R3: nearest-neighbor reorder)."""

import pytest

from trip.models.models import Category, Place, Trip, TripDay, TripItem, User
from trip.security import hash_password


def _trip_day(db, username, label="Day 1"):
    trip = Trip(name="Geo Trip", user=username)
    db.add(trip)
    db.commit()
    db.refresh(trip)
    day = TripDay(label=label, trip_id=trip.id)
    db.add(day)
    db.commit()
    db.refresh(day)
    return trip, day


class TestRouteOptimization:
    """POST /api/trips/{trip_id}/days/{day_id}/optimize"""

    def test_optimize_is_valid_permutation_with_signed_savings(self, client, test_user, db):
        """4+ geolocated items: optimized_order is a valid permutation of the
        input, starts at points[0], and savings_km == original - optimized
        (signed). Permutation correctness is asserted via a deterministic
        nearest-neighbor layout. We do NOT assert optimized <= original."""
        trip, day = _trip_day(db, test_user["username"])

        # Collinear points. Time order is A, X, B, C (original).
        # Nearest-neighbor from A walks A -> B -> C -> X (the deterministic,
        # correct NN order), which differs from the original A, X, B, C.
        items = [
            TripItem(time="09:00", text="A", day_id=day.id, lat=0.0, lng=0.0),
            TripItem(time="10:00", text="X", day_id=day.id, lat=0.0, lng=5.0),
            TripItem(time="11:00", text="B", day_id=day.id, lat=0.0, lng=1.0),
            TripItem(time="12:00", text="C", day_id=day.id, lat=0.0, lng=2.0),
        ]
        for item in items:
            db.add(item)
        db.commit()

        resp = client.post(
            f"/api/trips/{trip.id}/days/{day.id}/optimize",
            headers=test_user["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()

        original_ids = [p["id"] for p in data["original_order"]]
        optimized_ids = [p["id"] for p in data["optimized_order"]]

        # Valid permutation: same length, same elements
        assert len(optimized_ids) == len(original_ids) == 4
        assert sorted(optimized_ids) == sorted(original_ids)
        # Nearest-neighbor starts at points[0]
        assert optimized_ids[0] == original_ids[0]

        # Deterministic NN order for this layout: A, B, C, X
        opt_names = [p["name"] for p in data["optimized_order"]]
        assert opt_names == ["A", "B", "C", "X"]

        # Signed savings identity (robust; no assumption that optimized is shorter)
        assert data["savings_km"] == round(
            data["original_distance_km"] - data["optimized_distance_km"], 2
        )
        # For this layout the NN order is in fact shorter, so savings > 0 here.
        assert data["savings_km"] > 0

    def test_optimize_fewer_than_two_points(self, client, test_user, db):
        """A single-item day returns identical orders and zero savings."""
        trip, day = _trip_day(db, test_user["username"])
        db.add(TripItem(time="09:00", text="Solo", day_id=day.id, lat=41.0, lng=29.0))
        db.commit()

        resp = client.post(
            f"/api/trips/{trip.id}/days/{day.id}/optimize",
            headers=test_user["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["original_order"]) == 1
        assert data["original_distance_km"] == 0.0
        assert data["optimized_distance_km"] == 0.0
        assert data["savings_km"] == 0.0

    def test_optimize_excludes_items_without_coords(self, client, test_user, db):
        """Items without coordinates (own or place) are excluded."""
        trip, day = _trip_day(db, test_user["username"])
        db.add(TripItem(time="09:00", text="Geo", day_id=day.id, lat=0.0, lng=0.0))
        db.add(TripItem(time="10:00", text="NoGeo", day_id=day.id))  # no coords, no place
        db.commit()

        resp = client.post(
            f"/api/trips/{trip.id}/days/{day.id}/optimize",
            headers=test_user["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        # Only the geolocated item counts; <2 points -> identical, zero savings
        names = [p["name"] for p in data["original_order"]]
        assert names == ["Geo"]
        assert data["savings_km"] == 0.0

    def test_optimize_uses_place_coordinates(self, client, test_user, db):
        """Items without own lat/lng fall back to linked place coordinates."""
        cat = Category(name="Cat", user=test_user["username"])
        db.add(cat)
        db.commit()
        db.refresh(cat)
        place = Place(
            name="Museum",
            lat=41.0,
            lng=29.0,
            place="Istanbul",
            user=test_user["username"],
            category_id=cat.id,
        )
        db.add(place)
        db.commit()
        db.refresh(place)

        trip, day = _trip_day(db, test_user["username"])
        db.add(TripItem(time="09:00", text="Start", day_id=day.id, lat=40.0, lng=28.0))
        db.add(TripItem(time="10:00", text="Museum Visit", day_id=day.id, place_id=place.id))
        db.commit()

        resp = client.post(
            f"/api/trips/{trip.id}/days/{day.id}/optimize",
            headers=test_user["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["original_order"]) == 2
        museum = [i for i in data["original_order"] if i["name"] == "Museum Visit"][0]
        assert museum["lat"] == 41.0
        assert museum["lng"] == 29.0

    def test_optimize_unauthenticated(self, client, test_trip_with_item):
        trip = test_trip_with_item["trip"]
        day = test_trip_with_item["day"]
        resp = client.post(f"/api/trips/{trip.id}/days/{day.id}/optimize")
        assert resp.status_code == 401

    def test_optimize_foreign_user(self, client, db, test_user):
        """A non-member gets 404."""
        owner = User(username="owner-opt", password=hash_password("pw"))
        db.add(owner)
        db.commit()
        trip, day = _trip_day(db, "owner-opt")

        resp = client.post(
            f"/api/trips/{trip.id}/days/{day.id}/optimize",
            headers=test_user["headers"],
        )
        assert resp.status_code == 404

    def test_optimize_trip_not_found(self, client, test_user, test_trip_with_item):
        resp = client.post(
            "/api/trips/99999/days/1/optimize",
            headers=test_user["headers"],
        )
        assert resp.status_code == 404

    def test_optimize_day_not_found(self, client, test_user, test_trip_with_item):
        trip = test_trip_with_item["trip"]
        resp = client.post(
            f"/api/trips/{trip.id}/days/99999/optimize",
            headers=test_user["headers"],
        )
        assert resp.status_code == 404
