"""Tests for the multi-image place gallery.

Covers create/read/update/delete of a place's ``images`` gallery, the cover
selection via ``cover_index``, the per-endpoint count cap, the IDOR guard on
reused image ids, and that deleting a place cleans up its gallery Image rows.
"""

from __future__ import annotations

import base64
from io import BytesIO

import pytest
from PIL import Image as PILImage

from trip.models.models import Image, User
from trip.security import create_access_token, hash_password


def _png(color=(255, 0, 0)) -> str:
    """A small valid PNG as a data URI, so save_image_to_file always succeeds."""
    buf = BytesIO()
    PILImage.new("RGB", (10, 10), color).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _place_payload(category_id: int, images=None, cover_index=None) -> dict:
    payload = {
        "name": "Gallery Place",
        "lat": 48.8566,
        "lng": 2.3522,
        "place": "Paris, France",
        "category_id": category_id,
    }
    if images is not None:
        payload["images"] = images
    if cover_index is not None:
        payload["cover_index"] = cover_index
    return payload


@pytest.fixture()
def second_user(db):
    """A second, distinct user for cross-user (IDOR) checks."""
    user = User(username="seconduser", password=hash_password("pass12345"))
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token({"sub": user.username})
    return {"username": user.username, "headers": {"Authorization": f"Bearer {token}"}}


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestCreatePlacePhotos:
    def test_create_with_two_photos(self, client, test_user, test_category):
        resp = client.post(
            "/api/places",
            json=_place_payload(
                test_category.id, images=[{"data": _png()}, {"data": _png((0, 255, 0))}]
            ),
            headers=test_user["headers"],
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["images"]) == 2
        # Cover defaults to the first gallery image.
        assert body["image_id"] == body["images"][0]["id"]
        # Every gallery entry is served under the assets URL prefix.
        assert all(img["url"].startswith("/api/assets/") for img in body["images"])

    def test_create_cover_index(self, client, test_user, test_category):
        resp = client.post(
            "/api/places",
            json=_place_payload(
                test_category.id,
                images=[{"data": _png()}, {"data": _png((0, 255, 0))}],
                cover_index=1,
            ),
            headers=test_user["headers"],
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["image_id"] == body["images"][1]["id"]

    def test_create_without_photos(self, client, test_user, test_category):
        resp = client.post(
            "/api/places",
            json=_place_payload(test_category.id),
            headers=test_user["headers"],
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["images"] == []
        assert body["image_id"] is None

    def test_create_reused_image_id_rejected(self, client, test_user, test_category):
        # A new place has no gallery, so reusing any image id is invalid (404),
        # mirroring trip-item creation.
        resp = client.post(
            "/api/places",
            json=_place_payload(test_category.id, images=[{"id": 1}]),
            headers=test_user["headers"],
        )
        assert resp.status_code == 404

    def test_create_too_many_photos(self, client, test_user, test_category, monkeypatch):
        from trip.config import get_settings

        monkeypatch.setattr(get_settings(), "IMAGE_MAX_COUNT", 2)
        resp = client.post(
            "/api/places",
            json=_place_payload(
                test_category.id,
                images=[{"data": _png()}, {"data": _png()}, {"data": _png()}],
            ),
            headers=test_user["headers"],
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


class TestReadPlacePhotos:
    def test_list_includes_gallery(self, client, test_user, test_category):
        created = client.post(
            "/api/places",
            json=_place_payload(
                test_category.id, images=[{"data": _png()}, {"data": _png((0, 255, 0))}]
            ),
            headers=test_user["headers"],
        )
        assert created.status_code == 200
        listed = client.get("/api/places", headers=test_user["headers"])
        assert listed.status_code == 200
        place = next(p for p in listed.json() if p["id"] == created.json()["id"])
        assert len(place["images"]) == 2

    def test_get_place_includes_gallery(self, client, test_user, test_category):
        created = client.post(
            "/api/places",
            json=_place_payload(test_category.id, images=[{"data": _png()}]),
            headers=test_user["headers"],
        )
        place_id = created.json()["id"]
        resp = client.get(f"/api/places/{place_id}", headers=test_user["headers"])
        assert resp.status_code == 200
        assert len(resp.json()["images"]) == 1


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


class TestUpdatePlacePhotos:
    def test_update_drops_image(self, client, test_user, test_category):
        created = client.post(
            "/api/places",
            json=_place_payload(
                test_category.id, images=[{"data": _png()}, {"data": _png((0, 255, 0))}]
            ),
            headers=test_user["headers"],
        )
        body = created.json()
        keep_id = body["images"][0]["id"]
        place_id = body["id"]

        resp = client.put(
            f"/api/places/{place_id}",
            json={"images": [{"id": keep_id}]},
            headers=test_user["headers"],
        )
        assert resp.status_code == 200, resp.text
        updated = resp.json()
        assert len(updated["images"]) == 1
        assert updated["images"][0]["id"] == keep_id

    def test_update_clears_gallery(self, client, test_user, test_category):
        created = client.post(
            "/api/places",
            json=_place_payload(test_category.id, images=[{"data": _png()}]),
            headers=test_user["headers"],
        )
        place_id = created.json()["id"]

        resp = client.put(
            f"/api/places/{place_id}",
            json={"images": []},
            headers=test_user["headers"],
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["images"] == []
        assert body["image_id"] is None

    def test_update_adds_image(self, client, test_user, test_category):
        created = client.post(
            "/api/places",
            json=_place_payload(test_category.id, images=[{"data": _png()}]),
            headers=test_user["headers"],
        )
        body = created.json()
        place_id = body["id"]
        existing_id = body["images"][0]["id"]

        resp = client.put(
            f"/api/places/{place_id}",
            json={"images": [{"id": existing_id}, {"data": _png((0, 255, 0))}]},
            headers=test_user["headers"],
        )
        assert resp.status_code == 200, resp.text
        assert len(resp.json()["images"]) == 2

    def test_update_cover_index(self, client, test_user, test_category):
        created = client.post(
            "/api/places",
            json=_place_payload(
                test_category.id, images=[{"data": _png()}, {"data": _png((0, 255, 0))}]
            ),
            headers=test_user["headers"],
        )
        body = created.json()
        place_id = body["id"]
        ids = [img["id"] for img in body["images"]]

        resp = client.put(
            f"/api/places/{place_id}",
            json={"images": [{"id": ids[0]}, {"id": ids[1]}], "cover_index": 1},
            headers=test_user["headers"],
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["image_id"] == ids[1]

    def test_update_absent_key_keeps_gallery(self, client, test_user, test_category):
        created = client.post(
            "/api/places",
            json=_place_payload(
                test_category.id, images=[{"data": _png()}, {"data": _png((0, 255, 0))}]
            ),
            headers=test_user["headers"],
        )
        place_id = created.json()["id"]

        resp = client.put(
            f"/api/places/{place_id}",
            json={"name": "Renamed"},
            headers=test_user["headers"],
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "Renamed"
        assert len(resp.json()["images"]) == 2

    def test_update_idor_rejected(self, client, test_user, test_category, second_user, db):
        # Place owned by test_user with one gallery image.
        created = client.post(
            "/api/places",
            json=_place_payload(test_category.id, images=[{"data": _png()}]),
            headers=test_user["headers"],
        )
        body = created.json()
        place_id = body["id"]
        own_image_id = body["images"][0]["id"]

        # An image owned by the second user.
        foreign = Image(filename="foreign.png", file_size=9, user=second_user["username"])
        db.add(foreign)
        db.commit()
        db.refresh(foreign)

        # Trying to pull the foreign image into test_user's gallery must 404.
        resp = client.put(
            f"/api/places/{place_id}",
            json={"images": [{"id": own_image_id}, {"id": foreign.id}]},
            headers=test_user["headers"],
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestDeletePlacePhotos:
    def test_delete_removes_gallery_images(self, client, test_user, test_category, db):
        created = client.post(
            "/api/places",
            json=_place_payload(
                test_category.id, images=[{"data": _png()}, {"data": _png((0, 255, 0))}]
            ),
            headers=test_user["headers"],
        )
        body = created.json()
        place_id = body["id"]
        image_ids = [img["id"] for img in body["images"]]

        resp = client.delete(f"/api/places/{place_id}", headers=test_user["headers"])
        assert resp.status_code == 200, resp.text

        # Every gallery Image row must be gone.
        remaining = [db.get(Image, iid) for iid in image_ids]
        assert all(img is None for img in remaining)
