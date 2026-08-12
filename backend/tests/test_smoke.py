"""Smoke tests to verify the test infrastructure works correctly."""

from sqlmodel import select

from trip.models.models import User


def test_db_fixture_creates_tables(db):
    """The db fixture should create tables and yield a queryable session."""
    # Querying a table confirms the schema was actually created, not just that
    # the session object is truthy.
    assert db.exec(select(User)).all() == []


def test_client_fixture(client):
    """The client fixture should return a working TestClient."""
    response = client.get("/api/info")
    assert response.status_code == 200
    assert "version" in response.json()


def test_user_fixture(test_user):
    """The test_user fixture should create a user and return auth headers."""
    assert test_user["username"] == "testuser"
    assert "Authorization" in test_user["headers"]
    assert test_user["headers"]["Authorization"].startswith("Bearer ")


def test_place_fixture(test_place):
    """The test_place fixture should create a place with valid fields."""
    assert test_place.id is not None
    assert test_place.name == "Test Place"
    assert test_place.lat == 48.8566


def test_trip_with_item_fixture(test_trip_with_item):
    """The test_trip_with_item fixture should create a linked trip/day/item."""
    trip = test_trip_with_item["trip"]
    day = test_trip_with_item["day"]
    item = test_trip_with_item["item"]

    assert trip.id is not None
    assert day.trip_id == trip.id
    assert item.day_id == day.id
    assert item.place_id is not None


def test_authenticated_request(client, test_user):
    """An authenticated request should succeed with the test_user headers."""
    response = client.get("/api/settings", headers=test_user["headers"])
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "testuser"
