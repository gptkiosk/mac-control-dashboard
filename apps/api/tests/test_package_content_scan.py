"""The release package is rejected if its content looks like an email address, a home path or a secret.
Run the same scanner over the source that ships, so a literal that would fail the release build fails the suite first."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def load_release_module():
    spec = importlib.util.spec_from_file_location("release_scan_under_test", REPO / "scripts" / "release" / "release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def shipped_files() -> dict[str, bytes]:
    """The files the packer would include (packaging/product.json), read from the working tree."""
    patterns = json.loads((REPO / "packaging" / "product.json").read_text())["include"]
    files = {}
    for pattern in patterns:
        for path in sorted(REPO.glob(pattern)):
            if path.is_file():
                files[str(path.relative_to(REPO))] = path.read_bytes()
    return files


def test_shipped_source_passes_the_release_content_scan():
    release = load_release_module()
    files = shipped_files()
    assert "apps/api/source_update.py" in files and "CHANGELOG.md" in files
    findings = release.scan_contents(files, [])
    assert findings == [], "\n".join(findings)
