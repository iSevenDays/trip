from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import selectinload
from sqlmodel import select

from ..config import get_settings
from ..deps import SessionDep, get_current_username
from ..models.models import Place, PlaceCreate, PlaceRead, PlaceUpdate
from ..security import verify_exists_and_owns
from ..utils.utils import remove_image
from .trips import _cover_image_id, _resolve_item_images

router = APIRouter(prefix="/api/places", tags=["places"])


@router.get("", response_model=list[PlaceRead])
def read_places(
    session: SessionDep, current_user: Annotated[str, Depends(get_current_username)]
) -> list[PlaceRead]:
    db_places = session.exec(
        select(Place)
        .options(
            selectinload(Place.image),
            selectinload(Place.images),
            selectinload(Place.category),
            selectinload(Place.trips),
        )
        .where(Place.user == current_user)
    ).all()
    return [PlaceRead.serialize(p) for p in db_places]


@router.post("", response_model=PlaceRead)
async def create_place(
    place: PlaceCreate, session: SessionDep, current_user: Annotated[str, Depends(get_current_username)]
) -> PlaceRead:
    new_place = Place(
        name=place.name,
        lat=place.lat,
        lng=place.lng,
        place=place.place,
        gpx=place.gpx,
        allowdog=place.allowdog,
        description=place.description,
        price=place.price,
        duration=place.duration,
        category_id=place.category_id,
        visited=place.visited,
        restroom=place.restroom,
        links=place.links,
        user=current_user,
    )

    new_filenames: list[str] = []
    if place.images:
        # A new place has no existing gallery, so only freshly uploaded entries
        # are valid here - reused ids have nothing to reference yet.
        resolved, new_filenames = await _resolve_item_images(
            session, place.images, current_user, set(), size=get_settings().PLACE_IMAGE_SIZE
        )
        new_place.images = resolved
        new_place.image_id = _cover_image_id(resolved, place.cover_index)

    try:
        session.add(new_place)
        session.commit()
    except Exception:
        session.rollback()
        for fn in new_filenames:
            remove_image(fn)
        raise HTTPException(status_code=500, detail="Failed to create")
    return PlaceRead.serialize(new_place)


@router.put("/{place_id}", response_model=PlaceRead)
async def update_place(
    session: SessionDep,
    place_id: int,
    place: PlaceUpdate,
    current_user: Annotated[str, Depends(get_current_username)],
) -> PlaceRead:
    db_place = session.get(Place, place_id)
    verify_exists_and_owns(current_user, db_place)

    place_data = place.model_dump(exclude_unset=True)
    place_data.pop("cover_index", None)
    # An absent "images" key leaves the gallery untouched; an empty list clears it.
    new_filenames: list[str] = []
    if "images" in place_data:
        place_data.pop("images")
        old_images = list(db_place.images)
        allowed_ids = {img.id for img in old_images}
        resolved, new_filenames = await _resolve_item_images(
            session, place.images or [], current_user, allowed_ids, size=get_settings().PLACE_IMAGE_SIZE
        )
        resolved_ids = {img.id for img in resolved}

        db_place.images = resolved
        db_place.image_id = _cover_image_id(resolved, place.cover_index)
        session.flush()

        for old in old_images:
            if old.id not in resolved_ids:
                session.delete(old)

    for key, value in place_data.items():
        setattr(db_place, key, value)

    try:
        session.add(db_place)
        session.commit()
    except Exception:
        session.rollback()
        for fn in new_filenames:
            remove_image(fn)
        raise HTTPException(status_code=500, detail="Failed to update")
    return PlaceRead.serialize(db_place)


@router.delete("/{place_id}")
def delete_place(
    session: SessionDep, place_id: int, current_user: Annotated[str, Depends(get_current_username)]
):
    db_place = session.get(Place, place_id)
    verify_exists_and_owns(current_user, db_place)

    # Delete every gallery image plus the cover if it isn't already a gallery
    # member (legacy/backup-imported places can have a cover outside the
    # gallery). The Image.after_delete listener removes each file.
    images_to_delete = list(db_place.images)
    if db_place.image and db_place.image not in images_to_delete:
        images_to_delete.append(db_place.image)

    if images_to_delete:
        try:
            for image in images_to_delete:
                session.delete(image)
        except Exception:
            raise HTTPException(
                status_code=500,
                detail="Roses are red, violets are blue, if you're reading this, I'm sorry for you",
            )

    session.delete(db_place)
    session.commit()
    return {}


@router.get("/{place_id}", response_model=PlaceRead)
def get_place(
    session: SessionDep,
    place_id: int,
    current_user: Annotated[str, Depends(get_current_username)],
) -> PlaceRead:
    db_place = session.exec(
        select(Place)
        .options(selectinload(Place.image), selectinload(Place.images), selectinload(Place.category))
        .where(Place.id == place_id)
    ).first()
    verify_exists_and_owns(current_user, db_place)

    return PlaceRead.serialize(db_place, exclude_gpx=False)
