"""Small fixture contract for the M2 repository-role classifier."""

from build_m2_oprim_artifacts import classify_path


def main() -> int:
    platform = "/data/soffy/projects/platform/3O/oprim/foo.py"
    assert classify_path(platform) == "CANONICAL_SOURCE"
    assert (
        classify_path("/data/soffy/projects/mneme/vendor/oprim/foo.py", exact_replica=True)
        == "CONTROLLED_EXACT_REPLICA"
    )
    assert (
        classify_path("/data/soffy/projects/mneme/compat/foo.py", thin_reexport=True)
        == "THIN_REEXPORT"
    )
    assert classify_path("/data/soffy/projects/mneme/services/foo.py") == "LAYER4_IMPLEMENTATION"
    assert classify_path("/data/soffy/projects/mneme/foo.py") == "REAL_DUPLICATE_IMPLEMENTATION"
    print("M2_CLASSIFIER_FIXTURES=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
