"""Write the read-only public website: the 3D viewer plus the current results as plain files.

    python run.py publish                          # every imported run -> outputs/site/
    python run.py publish --batch 20261020_095105Z # only this batch (repeatable)
    python run.py publish --no-single-runs         # batches only
    python run.py publish --out D:/site            # somewhere else
    python run.py publish --batch <id> --no-single-runs --deploy   # build the viewer, publish, push to GitHub Pages
    python run.py publish --batch <id> --no-single-runs --serve    # publish and preview it at http://127.0.0.1:8766/
    python run.py publish --viewer-only [--serve|--deploy]         # after a viewer-only change: swap the bundle

With --deploy, the viewer is rebuilt first and the site is pushed as a single commit to the gh-pages branch of the
repository's origin (https://archigrad.io/HOUSIONNA/), replacing the previous site.

Upload the contents of the output folder to any static web host (one.com, GitHub Pages, a university server).
The site needs no Python server: the viewer reads data/viewer_scene.json.gz, and per HOUSIONNA run one
data/runs/<import>/assets.json (which geometry it uses) plus one <scenario>.json.gz per sensor. Geometry is stored
once under its content hash in data/assets/, so runs with the same room, crop and stage share it.
Files are gzipped because a site is capped (GitHub Pages: 1 GB); the browser unpacks them. The import, rerun and
simulation controls are hidden.
"""

from __future__ import annotations

import argparse
import hashlib
import gzip
import http.server
import functools
import webbrowser
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

from server.digital_twin_data import build_viewer_scene, housionna_viewer_payload


ROOT = Path(__file__).resolve().parents[2]
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
  # The data files are gzip files the viewer unpacks itself; serve them as they are.
  AddType application/gzip .gz
  RemoveEncoding .gz
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


SITE_PATHS_PER_RECEIVER = 20   # the viewer draws at most the 5 strongest; a few more stay clickable


def _slim(scenario: dict[str, Any]) -> dict[str, Any]:
    """Website copy of one transmitter: the strongest paths per receiver and radio-map values to 0.1 dB.
    Link metrics and path counts keep the full result; this only trims what is drawn."""
    out = dict(scenario)
    paths = scenario.get("paths") or []
    power = lambda path: float(path.get("magnitude_db", path.get("coefficient_magnitude_db_re_1", -300)) or -300)
    kept = []
    for receiver in dict.fromkeys(path.get("receiver") for path in paths):
        kept += sorted((path for path in paths if path.get("receiver") == receiver), key=power, reverse=True)[:SITE_PATHS_PER_RECEIVER]
    out["paths"], out["published_path_count"] = kept, len(paths)
    if isinstance(scenario.get("radio_map"), dict):
        radio_map = dict(scenario["radio_map"])
        radio_map["surfaces"] = [{**surface, "values_db": [None if value is None else round(value, 1)
                                                          for value in surface.get("values_db") or []]}
                                 for surface in radio_map.get("surfaces") or []]
        out["radio_map"] = radio_map
    return out


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
    """Write gzipped JSON (path ends in .json.gz); mtime 0 keeps unchanged files byte-identical between publishes."""
    text = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    leak = LOCAL_PATH.search(text)
    if leak:
        raise ValueError(f"{path.name} contains a local path ({leak.group(0)!r}); refusing to publish it")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = gzip.compress(text.encode("utf-8"), compresslevel=9, mtime=0)
    path.write_bytes(data)
    return len(data)


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


def _copy_bundle(bundle: Path, out: Path) -> None:
    # Source maps would publish the full viewer source; the site does not need them.
    shutil.copytree(bundle, out, ignore=shutil.ignore_patterns("*.map"), dirs_exist_ok=True)
    index = out / "index.html"
    html = index.read_text(encoding="utf-8")
    if '<html lang="en">' not in html:
        raise ValueError("Unexpected index.html: could not mark it as the static site")
    index.write_text(html.replace('<html lang="en">', '<html lang="en" data-site="static">', 1), encoding="utf-8")


def refresh_viewer(project_root: Path = ROOT, out: Path | None = None) -> Path:
    """Swap the viewer bundle of an existing published site and keep its data (a viewer-only change)."""
    project_root = Path(project_root).resolve()
    out = Path(out or project_root / "outputs" / "site").resolve()
    bundle = project_root.parent / "viewer" / "dist"
    if not (out / MARKER).is_file() or not (out / "data" / "viewer_scene.json.gz").is_file():
        raise ValueError(f"{out} has no published data yet; run a full publish first")
    if not (bundle / "index.html").is_file():
        raise FileNotFoundError("The viewer bundle is missing. Build it first: npm --prefix ../viewer run build")
    shutil.rmtree(out / "assets", ignore_errors=True)        # hashed bundle files of the previous build
    _copy_bundle(bundle, out)
    return out


def publish(project_root: Path = ROOT, out: Path | None = None, *,
            batches: list[str] | None = None, single_runs: bool = True) -> dict[str, Any]:
    project_root = Path(project_root).resolve()
    out = Path(out or project_root / "outputs" / "site").resolve()
    bundle = project_root.parent / "viewer" / "dist"           # the three.js app next to toolkit/
    if not (bundle / "index.html").is_file():
        raise FileNotFoundError("The viewer bundle is missing. Build it first: npm --prefix ../viewer run build")

    scene = _select(json.loads(build_viewer_scene(project_root).read_text(encoding="utf-8")), batches, single_runs)
    import_ids = sorted({row["import_id"] for row in scene["scenarios"].values()
                         if row.get("source_type") == "housionna" and row.get("import_id")})
    for import_id in import_ids:
        if not SAFE_ID.match(import_id):
            raise ValueError(f"Import id {import_id!r} is not safe as a file name")

    _clear(out)
    _copy_bundle(bundle, out)

    # The scene file's run summaries get the same rounding as the run files, so values compare equal in the viewer.
    sizes = {"scene": _write_json(out / "data" / "viewer_scene.json.gz", _compact(scene))}
    # Per run: the geometry its sensors share once, then one small file per transmitter, matching how the viewer
    # loads runs (data/runs/<import>/assets.json.gz and <scenario>.json.gz).
    for number, import_id in enumerate(import_ids, 1):
        names = [name for name, row in scene["scenarios"].items()
                 if row.get("source_type") == "housionna" and row.get("import_id") == import_id]
        for name in names:
            if not SAFE_ID.match(name):
                raise ValueError(f"Scenario name {name!r} is not safe as a file name")
        payload = housionna_viewer_payload(project_root, import_id)
        folder = out / "data" / "runs" / import_id
        refs: dict[str, dict[str, str]] = {}
        for kind in ("geometries", "meshes"):
            refs[kind] = {}
            for ref, value in (payload.get("assets", {}).get(kind) or {}).items():
                value = _compact(value)
                digest = hashlib.sha256(json.dumps(value, separators=(",", ":"), sort_keys=True).encode()).hexdigest()[:20]
                target = out / "data" / "assets" / f"{digest}.json.gz"
                if not target.is_file():
                    _write_json(target, value)
                refs[kind][ref] = digest
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "assets.json").write_text(json.dumps(refs, separators=(",", ":")), encoding="utf-8")
        for name in names:
            _write_json(folder / f"{name}.json.gz", _compact({
                "schema_version": payload.get("schema_version", 1), "import_id": import_id,
                "scenario_order": [name], "scenarios": {name: _slim(payload["scenarios"][name])}}))
        print(f"  {number}/{len(import_ids)} {import_id}: {len(names)} sensor(s)", flush=True)
    (out / ".htaccess").write_text(HTACCESS, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")       # GitHub Pages: serve the files as they are
    (out / MARKER).write_text("Made by run.py publish; the next publish replaces this whole folder.\n", encoding="utf-8")

    total = sum(path.stat().st_size for path in out.rglob("*") if path.is_file())
    return {"out": out, "runs": len(import_ids), "total_bytes": total, "scene_bytes": sizes["scene"]}


PAGES_BRANCH = "gh-pages"
PAGES_LIMIT_BYTES = 1e9          # GitHub Pages: 1 GB per site


def build_viewer(project_root: Path = ROOT) -> None:
    viewer = project_root.parent / "viewer"
    npm = "npm.cmd" if os.name == "nt" else "npm"
    subprocess.run([npm, "run", "build"], cwd=viewer, check=True)


def deploy(out: Path, project_root: Path = ROOT, message: str = "Publish viewer") -> str:
    """Push the published folder as one commit to the gh-pages branch of the repository's origin."""
    if not (out / MARKER).is_file():
        raise ValueError(f"{out} was not made by run.py publish; nothing pushed")
    remote = subprocess.run(["git", "-C", str(project_root), "remote", "get-url", "origin"],
                            check=True, capture_output=True, text=True).stdout.strip()
    git = ["git", "-C", str(out)]
    if not (out / ".git").is_dir():                            # publish removed the previous deployment repository
        subprocess.run([*git, "init", "-q", "-b", PAGES_BRANCH], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", message], check=True)
    subprocess.run([*git, "push", "--force", remote, PAGES_BRANCH], check=True)
    return remote


def serve(out: Path, port: int = 8766) -> None:
    """Serve the published folder as plain files, the way a web host would."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as server:
        url = f"http://127.0.0.1:{port}/"
        print(f"Previewing the site at {url} (Ctrl+C to stop)")
        webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run.py publish", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, help="output folder (default: outputs/site)")
    parser.add_argument("--batch", action="append", metavar="ID", help="publish only this batch (repeatable)")
    parser.add_argument("--no-single-runs", action="store_true", help="leave out runs that are not in a batch")
    parser.add_argument("--viewer-only", action="store_true",
                        help="only replace the viewer bundle in the existing site (keeps its data; fast)")
    parser.add_argument("--serve", action="store_true", help="preview the published site at http://127.0.0.1:8766/")
    parser.add_argument("--deploy", action="store_true",
                        help="rebuild the viewer first and push the site to the gh-pages branch (GitHub Pages)")
    args = parser.parse_args(argv)
    if args.viewer_only:
        try:
            if args.deploy:
                build_viewer(ROOT)
            out = refresh_viewer(ROOT, args.out)
        except (ValueError, FileNotFoundError, subprocess.CalledProcessError) as error:
            print(f"Publish failed: {error}", file=sys.stderr)
            return 2
        print(f"Replaced the viewer in {out}; the data is unchanged.")
        if args.serve:
            serve(out)
            return 0
        if args.deploy:
            try:
                remote = deploy(out, ROOT, "Publish viewer: viewer update")
            except (ValueError, subprocess.CalledProcessError) as error:
                print(f"Deploy failed: {error}", file=sys.stderr)
                return 2
            print(f"Pushed to {PAGES_BRANCH} of {remote}.")
        return 0
    try:
        if args.deploy:
            build_viewer(ROOT)
        result = publish(ROOT, args.out, batches=args.batch, single_runs=not args.no_single_runs)
    except (ValueError, FileNotFoundError, subprocess.CalledProcessError) as error:
        print(f"Publish failed: {error}", file=sys.stderr)
        return 2
    print(f"Published {result['runs']} HOUSIONNA run(s) and the built-in farm to {result['out']}")
    print(f"Total {result['total_bytes']/1e6:.1f} MB.")
    if result["total_bytes"] > 300e6:
        print("That is a large site; --batch publishes only the batches you name.")
    if args.serve:
        serve(result["out"])
        return 0
    if not args.deploy:
        print("Upload the folder's contents (including .htaccess) to your web host, or add --deploy for GitHub Pages.")
        return 0
    if result["total_bytes"] > PAGES_LIMIT_BYTES:
        print("Not pushed: GitHub Pages allows 1 GB per site. Publish fewer batches.", file=sys.stderr)
        return 2
    batches = ", ".join(args.batch) if args.batch else "all runs"
    try:
        remote = deploy(result["out"], ROOT, f"Publish viewer: {batches}")
    except (ValueError, subprocess.CalledProcessError) as error:
        print(f"Deploy failed: {error}", file=sys.stderr)
        return 2
    print(f"Pushed to {PAGES_BRANCH} of {remote}; the site updates within a minute: https://archigrad.io/HOUSIONNA/")
    return 0
