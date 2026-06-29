"""Layer4 asset store + E4 asset_loader bridge."""
import pytest

from hevi.assets import AssetRepository, load_asset_map, make_asset_loader
from hevi.assets.repository import ASSET_TYPES


def test_asset_types_taxonomy():
    assert ASSET_TYPES == frozenset({"character", "scene", "voice", "prop", "fx"})


@pytest.mark.asyncio
async def test_asset_crud_and_isolation(client):
    from hevi.db.pg_pool import get_hevi_pg_pool
    repo = AssetRepository(await get_hevi_pg_pool())

    a = await repo.create(
        asset_type="character", name="Ada",
        data={"reference_images": ["img/ada.jpg"]}, user_id="u1",
    )
    assert a["asset_type"] == "character"
    got = await repo.get(str(a["id"]))
    assert got is not None and got["data"]["reference_images"] == ["img/ada.jpg"]

    # official + own visible; another user's private not listed
    await repo.create(asset_type="voice", name="Official", user_id=None, is_official=True)
    await repo.create(asset_type="prop", name="OtherPriv", user_id="u2")
    names = {x["name"] for x in await repo.list_for_user(user_id="u1")}
    assert "Ada" in names and "Official" in names and "OtherPriv" not in names

    assert await repo.soft_delete(str(a["id"])) is True
    assert await repo.get(str(a["id"])) is None


@pytest.mark.asyncio
async def test_invalid_asset_type_rejected(client):
    from hevi.db.pg_pool import get_hevi_pg_pool
    repo = AssetRepository(await get_hevi_pg_pool())
    with pytest.raises(ValueError, match="Invalid asset_type"):
        await repo.create(asset_type="alien", name="x")


@pytest.mark.asyncio
async def test_loader_bridges_to_oskill_asset_reference_inject(client):
    """End-to-end: pre-fetch → sync loader → oskill.asset_reference_inject stamps _assets."""
    from oskill.asset_reference_inject import asset_reference_inject

    from hevi.db.pg_pool import get_hevi_pg_pool
    repo = AssetRepository(await get_hevi_pg_pool())
    char = await repo.create(
        asset_type="character", name="Hero",
        data={"reference_images": ["img/hero.jpg"]}, user_id="u1",
    )

    asset_refs = {"character_id": str(char["id"])}
    asset_map = await load_asset_map(repo, asset_refs)
    loader = make_asset_loader(asset_map)

    enriched = asset_reference_inject(
        shot_spec={"prompt": "hero walks"}, asset_refs=asset_refs, asset_loader=loader
    )
    assert "_assets" in enriched
    resolved = enriched["_assets"]["character_id"]
    assert resolved["data"]["reference_images"] == ["img/hero.jpg"]


def test_loader_returns_none_for_missing():
    loader = make_asset_loader({})
    assert loader("character", "nope") is None
