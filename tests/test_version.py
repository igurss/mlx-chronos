from mlx_chronos import _resolve_version


def test_version_prefers_source_tree_metadata():
    assert _resolve_version("0.3.0", "0.2.1") == "0.3.0"


def test_version_falls_back_to_installed_distribution_metadata():
    assert _resolve_version(None, "0.2.1") == "0.2.1"


def test_version_never_falls_back_to_a_stale_release_number():
    assert _resolve_version(None, None) == "unknown"
