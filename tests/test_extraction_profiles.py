from pathlib import Path

import pytest
from pydantic import ValidationError

from app.extraction_profiles import ExtractionProfile, extract_profile_fields, load_profile


HTML = """
<html><body>
<h1>Catalog</h1><article class="product"><h2>Local Audit</h2><span data-price="199">$199</span></article>
<a href="mailto:team@example.com">Email</a>
<script type="application/ld+json">{"name":"Local Audit","offers":{"price":"199"}}</script>
</body></html>
"""


def test_profile_extracts_static_dynamic_attribute_xpath_regex_and_jsonld() -> None:
    profile = ExtractionProfile.model_validate({
        "name": "fixture",
        "fields": [
            {"name": "product", "selector": "article.product h2", "source": "static"},
            {"name": "price", "selector": "[data-price]", "source": "dynamic", "attribute": "data-price"},
            {"name": "email", "selector": "mailto:([\\w.+-]+@[\\w.-]+)", "selector_type": "regex", "source": "static"},
            {"name": "xpath_product", "selector": "//article[@class='product']//h2", "selector_type": "xpath", "source": "static"},
            {"name": "schema_name", "selector": "name", "selector_type": "jsonld", "source": "either"},
        ],
    })
    result = extract_profile_fields(profile, "https://owned.example/", HTML, HTML, [{"name": "Local Audit"}])
    assert result["fields"]["product"]["values"] == ["Local Audit"]
    assert result["fields"]["price"]["values"] == ["199"]
    assert result["fields"]["email"]["values"] == ["team@example.com"]
    assert result["fields"]["xpath_product"]["status"] == "found"
    assert result["fields"]["schema_name"]["values"] == ["Local Audit"]


def test_profile_preserves_missing_field_status_and_validates_unique_names(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text('{"name":"missing","fields":[{"name":"sku","selector":"[data-sku]"}]}', encoding="utf-8")
    profile = load_profile(profile_path)
    assert profile is not None
    result = extract_profile_fields(profile, "https://owned.example/", HTML)
    assert result["fields"]["sku"]["status"] == "missing"
    with pytest.raises(ValidationError):
        ExtractionProfile.model_validate({"fields": [{"name": "same", "selector": "p"}, {"name": "same", "selector": "h1"}]})
