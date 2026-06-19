import pytest

from mlx_chronos.model_reference import normalize_model_reference_url


@pytest.mark.parametrize("value", [None, "", "   "])
def test_empty_model_reference_normalizes_to_none(value):
    assert normalize_model_reference_url(value) is None


def test_model_reference_strips_valid_http_url():
    assert (
        normalize_model_reference_url(" https://huggingface.co/org/model ")
        == "https://huggingface.co/org/model"
    )


@pytest.mark.parametrize("value", ["org/model", "ftp://example.test/model", "https:///model"])
def test_model_reference_rejects_non_http_urls(value):
    with pytest.raises(ValueError, match=r"http\(s\)"):
        normalize_model_reference_url(value)


def test_model_reference_rejects_non_string_value():
    with pytest.raises(ValueError, match="must be a string"):
        normalize_model_reference_url(123)  # type: ignore[arg-type]
