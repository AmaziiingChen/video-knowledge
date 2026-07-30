from __future__ import annotations

from pathlib import Path


def write_cookie_pairs_to_netscape(cookie_string: str, output_path: Path, domain: str) -> Path:
    """Persist browser Cookie pairs in the format yt-dlp accepts."""
    lines = [
        "# Netscape HTTP Cookie File",
        "# https://curl.haxx.se/rfc/cookie_spec.html",
        "# This is a generated file!  Do not edit.",
        "",
    ]
    count = 0
    for pair in (part.strip() for part in cookie_string.split(";") if part.strip()):
        if "=" not in pair:
            continue
        name, value = (part.strip() for part in pair.split("=", 1))
        if not name or not value or any(char in f"{name}{value}" for char in "\t\r\n"):
            continue
        lines.append(f"{domain}\tTRUE\t/\tFALSE\t0\t{name}\t{value}")
        count += 1

    if not count:
        raise ValueError("Cookie 格式无效，未识别到 name=value 项")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    output_path.chmod(0o600)
    return output_path
