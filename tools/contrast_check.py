"""Measure WCAG contrast ratios for the local Field Manual interface tokens."""

from __future__ import annotations


PAIRS = {
    "body ink on paper": ("#182523", "#f7f4ee"),
    "headline spruce on paper": ("#173d3a", "#f7f4ee"),
    "lede on paper": ("#485851", "#f7f4ee"),
    "muted on paper": ("#61706a", "#f7f4ee"),
    "rail body on spruce": ("#b2c3bd", "#173d3a"),
    "rail navigation on spruce": ("#c6d1cd", "#173d3a"),
    "white action text on spruce": ("#ffffff", "#173d3a"),
    "permission title on amber paper": ("#5b3810", "#fff0d9"),
    "permission copy on amber paper": ("#583911", "#fff0d9"),
    "error text on error paper": ("#762e28", "#fae9e6"),
    "issue evidence on paper": ("#46554f", "#f7f4ee"),
    "high severity text on warning paper": ("#895015", "#fdeccf"),
    "medium severity text on mist": ("#285a53", "#e2eeee"),
    "low severity text on neutral": ("#53605b", "#e6e8e6"),
}


def luminance(value: str) -> float:
    channels = [int(value[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(foreground: str, background: str) -> float:
    first, second = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (first + 0.05) / (second + 0.05)


if __name__ == "__main__":
    for name, (foreground, background) in PAIRS.items():
        print(f"{name}: {contrast(foreground, background):.2f}:1 ({foreground} on {background})")
