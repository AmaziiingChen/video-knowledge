# Python dependency policy

`requirements.txt` is the supported runtime manifest for normal local use.
It deliberately retains platform markers and a few bounded version ranges, so
it is not a cross-platform byte-for-byte lock file.

`requirements-dev.txt` pins the Python verification tools used by local checks.
Install both manifests before running the backend quality gates:

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
```

The exact pins prevent a new linter, audit tool, or test-runner release from
changing local verification behavior without a reviewed repository diff. When
upgrading one of them, update its pin, run the applicable backend checks, and
review the diff.

`requirements-build.txt` pins the desktop packager separately. Install it only
when running `python scripts/build_desktop_backend.py`; PyInstaller is a build
tool and is not required to run KnowledgeHub.

A complete pair of Linux and macOS runtime lock files, and any corresponding
CI changes, are later explicit reproducibility work. Do not claim this small
manifest is a substitute for that work.
