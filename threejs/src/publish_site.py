"""Write the read-only public website: the 3D viewer plus the current results as plain files.

    python run.py publish                          # every imported run -> outputs/site/
    python run.py publish --batch 20261020_095105Z # only this batch (repeatable)
    python run.py publish --no-single-runs         # batches only
    python run.py publish --out D:/site            # somewhere else

Upload the contents of the output folder to any static web host (one.com, GitHub Pages, a university server).
The site needs no Python server: the viewer reads data/viewer_scene.json and one data/runs/<import>.json per
HOUSIONNA run, and hides the import, rerun and simulation controls.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
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


def _compact(value: Any) -> Any:
    """Six significant digits: micrometres on a 10 m scene, 0.0001 dB, and tiny linear gains survive (unlike fixed
    decimals). Cuts run files by about a third."""
    if isinstance(value, float):
        return float(f"{value:.6g}")
    if isinstance(value, list):
        return [_compact(item) for item in value]
    if isinstance(value, dict):
        return {key: _compact(item) for key, item in value.items()}
    return value


def _select(scene: dict[str, Any], batches: list[str] | None, single_runs: bool) -> dict[str, Any]:
    """Keep the built-in scenes plus the chosen HOUSIONNA runs; the rest leave the published scene file."""
    def keep(row: dict[str, Any]) -> bool:
        if row.get("source_type") != "housionna":
            return True
        batch = (row.get("run_metadata") or {}).get("batch", {}).get("id")
        return (batch in batches) if batch and batches is not None else (bool(batch) or single_runs)
    names = [name for name in scene["scenario_order"] if keep(scene["scenarios"][name])]
    if batches is not None:
        found = {(scene["scenarios"][name].get("run_metadata") or {}).get("batch", {}).get("id") for name in names}
        missing = sorted(set(batches) - found)
        if missing:
            raise ValueError(f"No imported runs for batch {', '.join(missing)}")
    selected = {**scene, "scenario_order": names, "scenarios": {name: scene["scenarios"][name] for name in names},
                "scenario_labels": {name: label for name, label in scene.get("scenario_labels", {}).items() if name in names}}
    if selected.get("featured_scenario") not in selected["scenarios"]:
        housionna = [name for name in names if selected["scenarios"][name].get("source_type") == "housionna"]
        selected["featured_scenario"] = (housionna or names)[-1] if names else None
    return selected


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
    shutil.rmtree(out, onexc=_make_writable)


def _make_writable(function, path, _error) -> None:
    """Git stores its objects read-only, which Windows refuses to delete (a deployment repo in the site folder)."""
    os.chmod(path, stat.S_IWRITE)
    function(path)


def publish(project_root: Path = ROOT, out: Path | None = None, *,
            batches: list[str] | None = None, single_runs: bool = True) -> dict[str, Any]:
    project_root = Path(project_root).resolve()
    out = Path(out or project_root / "outputs" / "site").resolve()
    bundle = project_root / "viewer" / "digital-twin-dist"
    if not (bundle / "index.html").is_file():
        raise FileNotFoundError("The viewer bundle is missing. Build it first: npm --prefix frontend run build")

    scene = _select(json.loads(build_viewer_scene(project_root).read_text(encoding="utf-8")), batches, single_runs)
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

    # The scene file's run summaries get the same rounding as the run files, so values compare equal in the viewer.
    sizes = {"scene": _write_json(out / "data" / "viewer_scene.json", _compact(scene))}
    # One file per transmitter, matching how the viewer loads runs (data/runs/<import>/<scenario>.json).
    for name, row in scene["scenarios"].items():
        if row.get("source_type") == "housionna" and row.get("import_id"):
            if not SAFE_ID.match(name):
                raise ValueError(f"Scenario name {name!r} is not safe as a file name")
            sizes[name] = _write_json(out / "data" / "runs" / row["import_id"] / f"{name}.json",
                                      _compact(housionna_viewer_payload(project_root, row["import_id"], name)))
    (out / ".htaccess").write_text(HTACCESS, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")       # GitHub Pages: serve the files as they are
    (out / MARKER).write_text("Made by run.py publish; the next publish replaces this whole folder.\n", encoding="utf-8")

    total = sum(path.stat().st_size for path in out.rglob("*") if path.is_file())
    return {"out": out, "runs": len(import_ids), "total_bytes": total, "scene_bytes": sizes["scene"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run.py publish", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, help="output folder (default: outputs/site)")
    parser.add_argument("--batch", action="append", metavar="ID", help="publish only this batch (repeatable)")
    parser.add_argument("--no-single-runs", action="store_true", help="leave out runs that are not in a batch")
    args = parser.parse_args(argv)
    try:
        result = publish(ROOT, args.out, batches=args.batch, single_runs=not args.no_single_runs)
    except (ValueError, FileNotFoundError) as error:
        print(f"Publish failed: {error}", file=sys.stderr)
        return 2
    print(f"Published {result['runs']} HOUSIONNA run(s) and the built-in farm to {result['out']}")
    print(f"Total {result['total_bytes']/1e6:.1f} MB. Upload the folder's contents (including .htaccess) to your web host.")
    if result["total_bytes"] > 300e6:
        print("That is a large upload; --batch publishes only the batches you name.")
    return 0
