from __future__ import annotations

import argparse
import importlib.metadata
import hashlib
import json
import shutil
from pathlib import Path

from packaging.requirements import Requirement


RUNTIME_ROOTS = (
    "auralwarden", "streamlink", "yt-dlp", "PyAudioWPatch", "pycaw", "comtypes",
    "faster-whisper", "sherpa-onnx", "sherpa-onnx-bin", "PySide6", "QtAwesome",
)


def runtime_distributions(profile: str):
    pending = list(RUNTIME_ROOTS)
    if profile == "cuda":
        pending.append("nvidia-cublas-cu12")
    found = {}
    while pending:
        requested = pending.pop()
        try:
            distribution = importlib.metadata.distribution(requested)
        except importlib.metadata.PackageNotFoundError:
            raise RuntimeError(f"Required runtime distribution is missing: {requested}")
        key = (distribution.metadata.get("Name") or requested).casefold()
        if key in found:
            continue
        found[key] = distribution
        for raw in distribution.requires or ():
            requirement = Requirement(raw)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                pending.append(requirement.name)
    return sorted(found.values(), key=lambda item: (item.metadata.get("Name") or "").casefold())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=("cpu", "cuda"), required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    catalog = json.loads((root / "docs/vendor-notices.json").read_text(encoding="utf-8"))
    rows = []
    for distribution in runtime_distributions(args.profile):
        name = distribution.metadata.get("Name") or "unknown"
        files = []
        for item in distribution.files or ():
            basename = Path(str(item)).name.casefold()
            if not (basename.startswith(("license", "licence", "copying", "notice")) or basename in {"authors", "authors.txt", "authors.rst"}):
                continue
            source = Path(distribution.locate_file(item)).resolve()
            if not source.is_file() or source.stat().st_size > 2 * 1024**2:
                continue
            destination = args.output / f"{name}-{distribution.version}-{Path(str(item)).name}"
            counter = 2
            while destination.exists():
                destination = args.output / f"{name}-{distribution.version}-{counter}-{Path(str(item)).name}"
                counter += 1
            shutil.copy2(source, destination)
            files.append(destination.name)
        upstream = []
        key = name.casefold().replace("-", "_")
        fallback = next((value for package, value in catalog["packages"].items()
                         if package.replace("-", "_") == key), None)
        if fallback is not None:
            if distribution.version != fallback["version"]:
                raise RuntimeError(f"Upstream notices need review for {name} {distribution.version}")
            for filename in fallback["files"]:
                original = root / "docs/vendor-notices" / filename
                provenance = catalog["files"][filename]
                digest = hashlib.sha256(original.read_bytes()).hexdigest()
                if digest.casefold() != provenance["sha256"].casefold():
                    raise RuntimeError(f"Notice checksum mismatch: {filename}")
                destination = args.output / filename
                shutil.copy2(original, destination)
                files.append(filename)
                upstream.append(provenance)
        if name.casefold() == "auralwarden":
            destination = args.output / "AuralWarden-LICENSE"
            shutil.copy2(root / "LICENSE", destination)
            files.append(destination.name)
        if not files:
            raise RuntimeError(f"No license notice found for {name} {distribution.version}")
        rows.append({
            "name": name,
            "version": distribution.version,
            "license": distribution.metadata.get("License-Expression") or distribution.metadata.get("License") or "not declared in package metadata",
            "notices": files,
            "upstream_notices": upstream,
            "notice_sha256": {file: hashlib.sha256((args.output / file).read_bytes()).hexdigest()
                              for file in files},
        })
    shutil.copy2(root / "docs/vendor-notices.json", args.output / "vendor-notices.json")
    (args.output / "inventory.json").write_text(
        json.dumps({"profile": args.profile, "packages": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
