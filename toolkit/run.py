from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "import-housionna":
        from housionna.importer import main as import_housionna

        raise SystemExit(import_housionna(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "housionna-rerun":
        from housionna.simulation import main as housionna_rerun

        raise SystemExit(housionna_rerun(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "housionna-position-test":
        from housionna.simulation import position_test_main

        raise SystemExit(position_test_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "housionna-worker":
        import os
        import time
        os.environ["HYROPA_WORKER_BOOT_NS"] = str(time.perf_counter_ns())
        # A NumPy/LLVM import can be delayed on a busy Windows host. Publish a
        # real startup stage before loading those numerical libraries.
        import json
        from housionna.performance import atomic_json
        try:
            spec_path=Path(sys.argv[sys.argv.index("--spec")+1])
            bootstrap_spec=json.loads(spec_path.read_text(encoding="utf-8"))
            atomic_json(Path(bootstrap_spec["job_folder"])/"status.json",{
                "status":"preparing","stage":"python_imports",
                "message":"Starting Python and loading numerical libraries"})
        except (OSError,ValueError,KeyError,IndexError):
            pass
        from housionna.simulation import simulation_worker_main

        raise SystemExit(simulation_worker_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "maps":
        from engine.application_maps import main as application_maps

        raise SystemExit(application_maps(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "placement":
        from engine.placement import main as placement

        raise SystemExit(placement(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "apps":
        from engine.application_engine import main as application_engine

        raise SystemExit(application_engine(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "casestudy":
        from engine.casestudy import main as casestudy

        raise SystemExit(casestudy(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "publish":
        from server.publish_site import main as publish_site

        raise SystemExit(publish_site(sys.argv[2:]))
    from demos.poc import main  # noqa: E402

    main()
