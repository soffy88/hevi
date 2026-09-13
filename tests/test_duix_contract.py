from hevi.digital_human.duix_service import DuixLiveService


def test_duix_remains_optional_with_license_and_capability_contract() -> None:
    service = DuixLiveService(base_url="")
    assert service.license_metadata == {
        "provider": "duix",
        "license": "DUIX.COM Community License",
        "bundled": False,
        "optional": True,
        "commercial_review_required": True,
    }
    assert service.capabilities["optional_external_provider"] is True
