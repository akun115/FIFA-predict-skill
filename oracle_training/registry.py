"""Immutable fitted-model artifacts and explicit atomic promotion."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from oracle_core.fitted import FittedNationalModel


class ArtifactIntegrityError(ValueError):
    pass


class PromotionRejected(ValueError):
    pass


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ModelRegistry:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _artifact(self, version: str) -> Path:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", version) is None:
            raise ValueError("invalid model version")
        return self.root / version

    def save_candidate(self, model: dict, manifest: dict, report: dict) -> Path:
        version = str(model.get("version", ""))
        FittedNationalModel.from_dict(model)
        destination = self._artifact(version)
        if destination.exists():
            self.validate(version)
            return destination
        temporary = Path(tempfile.mkdtemp(prefix=f".{version}-", dir=self.root))
        try:
            files = {
                "model.json": model,
                "data-manifest.json": manifest,
                "backtest-report.json": report,
            }
            for filename, value in files.items():
                (temporary / filename).write_bytes(_json_bytes(value))
            checksums = {
                filename: _hash(temporary / filename) for filename in sorted(files)
            }
            (temporary / "checksum.sha256").write_bytes(_json_bytes(checksums))
            os.replace(temporary, destination)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return destination

    def validate(self, version: str) -> dict:
        artifact = self._artifact(version)
        try:
            expected = json.loads((artifact / "checksum.sha256").read_text(encoding="utf-8"))
            for filename in ("model.json", "data-manifest.json", "backtest-report.json"):
                if expected.get(filename) != _hash(artifact / filename):
                    raise ArtifactIntegrityError(f"checksum mismatch: {filename}")
            model = json.loads((artifact / "model.json").read_text(encoding="utf-8"))
            FittedNationalModel.from_dict(model)
            report = json.loads(
                (artifact / "backtest-report.json").read_text(encoding="utf-8")
            )
            return {"model": model, "report": report, "checksums": expected}
        except ArtifactIntegrityError:
            raise
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ArtifactIntegrityError(f"invalid artifact: {version}") from error

    def promote(self, version: str, *, confirm: bool) -> Path:
        if not confirm:
            raise PromotionRejected("promotion requires explicit confirmation")
        validated = self.validate(version)
        gates = validated["report"].get("gates", {})
        if not gates or not all(value is True for value in gates.values()):
            raise PromotionRejected("candidate has failed or incomplete promotion gates")
        pointer = {
            "version": version,
            "artifact": version,
            "model_sha256": validated["checksums"]["model.json"],
        }
        temporary = self.root / "current.json.tmp"
        temporary.write_bytes(_json_bytes(pointer))
        os.replace(temporary, self.root / "current.json")
        return self.root / "current.json"

    def status(self, version: str = "") -> dict:
        if version:
            validated = self.validate(version)
            current = self.status().get("version") if (self.root / "current.json").exists() else None
            return {
                "version": version,
                "status": "promoted" if current == version else "candidate",
                "gates": validated["report"].get("gates", {}),
            }
        pointer = self.root / "current.json"
        if not pointer.exists():
            return {"status": "no_promoted_model", "version": None}
        value = json.loads(pointer.read_text(encoding="utf-8"))
        self.validate(value["version"])
        return {"status": "promoted", "version": value["version"]}

    def load_current(self) -> FittedNationalModel:
        status = self.status()
        if not status.get("version"):
            raise ArtifactIntegrityError("no promoted model")
        artifact = self._artifact(status["version"])
        return FittedNationalModel.from_dict(
            json.loads((artifact / "model.json").read_text(encoding="utf-8"))
        )
