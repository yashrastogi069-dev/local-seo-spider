"""Regression guard for audited Field Manual text and semantic-status contrast pairs."""

from tools.contrast_check import PAIRS, contrast


def test_all_audited_field_manual_text_pairs_meet_wcag_aa_normal_text_contrast() -> None:
    failures = {
        name: ratio
        for name, (foreground, background) in PAIRS.items()
        if (ratio := contrast(foreground, background)) < 4.5
    }
    assert not failures, f"Color pairs below 4.5:1: {failures}"
