"""Write the read-only public website: the 3D viewer plus the current results as plain files.

    python run.py publish                 # -> outputs/site/
    python run.py publish --out D:/site   # somewhere else

Upload the contents of the output folder to any static web host (one.com, GitHub Pages, a university server).
The site needs no Python server: the viewer reads data/viewer_scene.json and one data/runs/<import>.json per
HOUSIONNA run, and hides the import, rerun and simulation controls.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any

from digital_twin_data import build_viewer_scene, housionna_viewer_payload


ROOT = Path(__file__).resolve().parents[1]
MARKER = ".housionna-site"
SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
# Anything that looks like a local file location or account name must not reach a public website.
LOCAL_PATH = re.compile(r"[A-Za-z]:[\\/]{1,2}(?:Users|home)|/home/[^/\"]+|/Users/[^/\"]+|\\\\Users\\\\", re.IGNORECASE)

HTACCESS = """# Written by run.py publish. Apache (one.com and most shared hosts) reads this file; others ignore it.
<IfModule mod_deflate.c>
  AddOutputFilterByType DEFLATE application/json text/html text/css application/javascript image/svg+xml
</IfModule>
<IfModule mod_mime.c>
  AddType application/json .json
  AddType application/javascript .js
</IfModule>
<IfModule mod_headers.c>
  # Hashed bundle files never change; data and the page are re-checked so a new upload shows up at once.
  <FilesMatch "\\.(js|css|png|woff2?)$">
    Header set Cache-Control "public, max-age=604800"
  </FilesMatch>
  <FilesMatch "\\.(json|html)$">
    Header set Cache-Control "no-cache"
  </FilesMatch>
</IfModule>
Options -Indexes
"""


def _write_json(path: Path, value: Any) -> int:
    text = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    leak = LOCAL_PATH.search(text)
    if leak:
        raise ValueError(f"{path.name} contains a local path ({leak.group(0)!r}); refusing to publish it")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def _clear(out: Path) -> None:
    """Empty the output folder, but only if it is empty already or an earlier publish made it."""
    if not out.exists():
        return
    if any(out.iterdir()) and not (out / MARKER).is_file():
        raise ValueError(f"{out} is not empty and was not made by run.py publish; choose another --out folder")
    shutil.rmtree(out)


def publish(project_root: Path = ROOT, out: Path | None = None) -> dict[str, Any]:
    project_root = Path(project_root).resolve()
    out = Path(out or project_root / "outputs" / "site").resolve()
    bundle = project_root / "viewer" / "digital-twin-dist"
    if not (bundle / "index.html").is_file():
        raise FileNotFoundError("The viewer bundle is missing. Build it first: npm --prefix frontend run build")

    scene = json.loads(build_viewer_scene(project_root).read_text(encoding="utf-8"))
    import_ids = sorted({row["import_id"] for row in scene["scenarios"].values()
                         if row.get("source_type") == "housionna" and row.get("import_id")})
    for import_id in import_ids:
        if not SAFE_ID.match(import_id):
            raise ValueError(f"Import id {import_id!r} is not safe as a file name")

    _clear(out)
    # Source maps would publish the full viewer source; the site does not need them.
    shutil.copytree(bundle, out, ignore=shutil.ignore_patterns("*.map"))
    index = out / "index.html"
    html = index.read_text(encoding="utf-8")
    if '<html lang="en">' not in html:
        raise ValueError("Unexpected index.html: could not mark it as the static site")
    index.write_text(html.replace('<html lang="en">', '<html lang="en" data-site="static">', 1), encoding="utf-8")

    sizes = {"scene": _write_json(out / "data" / "viewer_scene.json", scene)}
    for import_id in import_ids:
        sizes[import_id] = _write_json(out / "data" / "runs" / f"{import_id}.json",
                                       housionna_viewer_payload(project_root, import_id))
    (out / ".htaccess").write_text(HTACCESS, encoding="utf-8")
    (out / MARKER).write_text("Made by run.py publish; the next publish replaces this whole folder.\n", encoding="utf-8")

    total = sum(path.stat().st_size for path in out.rglob("*") if path.is_file())
    return {"out": out, "runs": len(import_ids), "total_bytes": total, "scene_bytes": sizes["scene"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run.py publish", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, help="output folder (default: outputs/site)")
    args = parser.parse_args(argv)
    result = publish(ROOT, args.out)
    print(f"Published {result['runs']} HOUSIONNA run(s) and the built-in farm to {result['out']}")
    print(f"Total {result['total_bytes']/1e6:.1f} MB. Upload the folder's contents (including .htaccess) to your web host.")
    return 0
