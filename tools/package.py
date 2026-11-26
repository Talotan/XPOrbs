"""Build dist/XPOrbs-<version>.zip: the same file set the BigWigs packager ships (see .pkgmeta).

Usage: uv run python tools/package.py
"""

import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "XPOrbs"
EXTRA = ["LICENSE", "README.md", "CHANGELOG.md", "Libs/README.md"]
DEV_BEGIN, DEV_END = "#@do-not-package@", "#@end-do-not-package@"  # dev-only toc lines (dev/Bench.lua)


def toc_version(toc: Path) -> str:
    m = re.search(r"^## Version:\s*(\S+)", toc.read_text(encoding="utf-8"), re.MULTILINE)
    if not m:
        raise SystemExit(f"no '## Version:' in {toc}")
    return m.group(1)


def strip_dev_blocks(text: str) -> str:
    """The toc text without its do-not-package blocks (markers included), as the BigWigs packager removes them."""
    kept, skipping = [], False
    for line in text.splitlines():
        marker = line.strip()
        if marker == DEV_BEGIN:
            skipping = True
        elif marker == DEV_END:
            skipping = False
        elif not skipping:
            kept.append(line)
    return "\n".join(kept) + "\n"


def toc_files(toc: Path) -> list[str]:
    lines = (ln.strip() for ln in strip_dev_blocks(toc.read_text(encoding="utf-8")).splitlines())
    return [ln.replace("\\", "/") for ln in lines if ln and not ln.startswith("#")]


def collect() -> list[str]:
    toc = ROOT / f"{NAME}.toc"
    listed = toc_files(toc)
    media = ROOT / "media"
    shipped_media = sorted(f"media/{p.relative_to(media).as_posix()}" for p in media.rglob("*") if p.is_file())
    files = [toc.name, *listed, *shipped_media, *EXTRA]
    missing = [f for f in files if not (ROOT / f).is_file()]
    if missing:
        raise SystemExit(f"missing files: {', '.join(missing)}")
    # the packager ships these even though the toc doesn't load them (dev/ is ignored by .pkgmeta)
    for p in ROOT.glob("*.lua"):
        if p.name not in listed:
            print(f"warning: {p.name} is not in the toc but would be packaged", file=sys.stderr)
    return list(dict.fromkeys(files))


def build(out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{NAME}-{toc_version(ROOT / f'{NAME}.toc')}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in collect():
            if rel == f"{NAME}.toc":  # the shipped toc has the dev-only block removed
                z.writestr(f"{NAME}/{rel}", strip_dev_blocks((ROOT / rel).read_text(encoding="utf-8")))
            else:
                z.write(ROOT / rel, f"{NAME}/{rel}")
    return zip_path


if __name__ == "__main__":
    path = build(ROOT / "dist")
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            print(f"{info.file_size:>9}  {info.filename}")
    print(f"-> {path}")
