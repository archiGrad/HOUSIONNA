from __future__ import annotations

import gzip
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import urllib.request
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import rt_backend
from integrations.housionna_simulation import HousionnaLiveSimulationManager, HousionnaSimulationApiError
from integrations.housionna_performance import ImportCache, atomic_json
from viewer_server import DashboardHandler
from integrations.housionna import discover_runs, ADAPTER_VERSION
from digital_twin_data import _housionna_content_signature


class ManagerReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.manager=HousionnaLiveSimulationManager(self.root)
        folder=self.root/'job';folder.mkdir()
        self.job={'job_id':'a'*32,'status':'running','stage':'running','task':'radio_map',
          'job_folder':folder,'output_dir':self.root/'result','started_monotonic':time.perf_counter(),
          'timeout_seconds':10,'attempt':1,'cache_key':'key','request':{},'submission_seconds':.01,
          'process':Mock()}
        self.job['process'].poll.return_value=1
        self.manager.jobs[self.job['job_id']]=self.job
        self.manager.active_job_id=self.job['job_id']
        (folder/'worker.log').write_text('worker stopped')
        atomic_json(folder/'status.json',{'status':'running','stage':'running','message':'old progress'})

    def tearDown(self):self.temp.cleanup()

    def test_native_exit_cannot_be_overwritten_by_stale_running_status(self):
        self.job['process'].wait.return_value=1
        self.manager._monitor(self.job['job_id'])
        self.assertEqual(self.manager.status(self.job['job_id'])['status'],'failed')
        atomic_json(self.job['job_folder']/'status.json',{'status':'running'})
        self.assertEqual(self.manager.status(self.job['job_id'])['status'],'failed')
        self.assertIsNone(self.manager.active_job_id)

    def test_completion_waits_for_supervisor_provenance(self):
        self.job['process'].poll.return_value=0
        self.job['process'].wait.return_value=0
        self.job['output_dir'].mkdir()
        atomic_json(self.job['job_folder']/'status.json',{'status':'completed','run_id':self.job['job_id']})
        self.assertEqual(self.manager.status(self.job['job_id'])['status'],'exporting')
        self.manager._monitor(self.job['job_id'])
        self.assertEqual(self.manager.status(self.job['job_id'])['status'],'completed')
        self.assertTrue((self.job['output_dir']/'execution.json').is_file())
        self.assertIsNone(self.manager.active_job_id)

    def test_timeout_terminates_only_the_tracked_worker_and_releases_gate(self):
        self.job['process'].wait.side_effect=[subprocess.TimeoutExpired('worker',10),1]
        self.manager._monitor(self.job['job_id'])
        self.job['process'].kill.assert_called_once()
        self.assertEqual(self.manager.status(self.job['job_id'])['status'],'failed')
        self.assertIn('10 s',self.manager.status(self.job['job_id'])['error'])
        self.assertIsNone(self.manager.active_job_id)

    def test_stop_worker_reaps_owned_launcher_and_children(self):
        import psutil
        process=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        time.sleep(.3)
        children=psutil.Process(process.pid).children(recursive=True)
        try:
            self.manager._stop_worker({'process':process})
            self.assertIsNotNone(process.poll())
            _,alive=psutil.wait_procs(children,timeout=2)
            self.assertEqual(alive,[])
        finally:
            if process.poll() is None:process.kill();process.wait()

    def test_native_jit_retry_is_bounded_and_preserves_request(self):
        (self.job['job_folder']/'worker.log').write_text('Failed to materialize symbols')
        self.job['process'].wait.return_value=1
        with patch.object(self.manager,'_spawn') as spawn:
            self.manager._monitor(self.job['job_id'])
        spawn.assert_called_once_with(self.job)
        self.assertEqual(self.job['attempt'],2)
        self.assertEqual(self.job['request'],{})
        self.assertEqual(self.job['status'],'failed')

    def test_failed_status_survives_new_manager(self):
        self.manager._fail(self.job,'specific failure')
        folder=self.manager.jobs_root/self.job['job_id'];folder.mkdir(parents=True)
        atomic_json(folder/'request.json',{'task':'radio_map'})
        atomic_json(folder/'status.json',json.loads((self.job['job_folder']/'status.json').read_text()))
        restored=HousionnaLiveSimulationManager(self.root).status(self.job['job_id'])
        self.assertEqual(restored['status'],'failed')
        self.assertEqual(restored['error'],'specific failure')

    def test_identical_active_request_deduplicated_other_request_conflicts(self):
        with patch.object(self.manager,'_normalize',return_value={'cache_key':'key'}):
            self.assertEqual(self.manager.start({},map_job=True)['job_id'],self.job['job_id'])
        with patch.object(self.manager,'_normalize',return_value={'cache_key':'other'}):
            with self.assertRaises(HousionnaSimulationApiError) as error:self.manager.start({},map_job=True)
            self.assertEqual(error.exception.status,409)

    def test_incomplete_artifact_never_reused(self):
        folder=self.manager.live_root/'housionna-maps'/('b'*32);folder.mkdir(parents=True)
        atomic_json(folder/'execution.json',{'status':'completed','cache_key':'key'})
        self.assertIsNone(self.manager._find_cached('key'))
        atomic_json(folder/'radio_map.json',{'surfaces':[]})
        atomic_json(folder/'metadata.json',{'run_id':'b'*32})
        atomic_json(folder/'comparison.json',{})
        self.assertEqual(self.manager._find_cached('key'),'b'*32)


class CacheKeyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.manager=HousionnaLiveSimulationManager(self.root)
        self.solver={'max_depth':3,'los':True,'specular_reflection':True,'refraction':True,'diffuse_reflection':False,'diffraction':False}
        self.payload={'source_run_id':'run','import_id':'import','transmitter':'tx_0','receiver_ids':['rx_0'],
          'tx_position':[0,0,1],'tx_orientation':[0,0,0],'frequency_hz':3.5e9,'solver':self.solver,'samples_per_src':100000,'seed':42,'quality':'low'}
        self.scenario={'transmitter':{'name':'tx_0'},'geometry_ref':'geometry','provenance':{'run_folder_name':'run','source_sha256':'source'}}
        self.document={'scenarios':{'scene':self.scenario},'assets':{'geometries':{'geometry':{'bounds_m':{'x_min':-5,'x_max':5,'y_min':-5,'y_max':5,'z_min':0,'z_max':5}}}}}
        self.patches=[patch('integrations.housionna_simulation.resolve_source_run',return_value=self.root),
          patch('integrations.housionna_simulation._source_documents',return_value=(None,{},None,None,[{'name':'tx_0','position_m':[0,0,1],'orientation_rad':[0,0,0],'power_dbm':30}],[{'name':'rx_0'},{'name':'rx_1'}])),
          patch('integrations.housionna_simulation._source_fingerprint',return_value=('source',{'scene.xml':'hash'})),
          patch.object(self.manager.import_cache,'read',return_value=self.document)]
        for p in self.patches:p.start()

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def key(self,**changes):return self.manager._normalize({**self.payload,**changes},map_job=True)['cache_key']

    def test_exact_requests_equal_and_rf_changes_invalidate(self):
        original=self.key();self.assertEqual(original,self.key())
        for change in [{'tx_position':[.1,0,1]},{'tx_orientation':[0,0,.1]},{'frequency_hz':2.4e9},
                       {'solver':{**self.solver,'max_depth':2}},{'quality':'medium'},{'seed':43}]:
            with self.subTest(change=change):self.assertNotEqual(original,self.key(**change))
        self.manager.runtime={**self.manager.runtime,'packages':{'sionna-rt':'different'}}
        self.assertNotEqual(original,self.key())

    def test_map_key_excludes_irrelevant_path_samples_and_rx_selection(self):
        self.assertEqual(self.key(),self.key(samples_per_src=200000,receiver_ids=['rx_1']))

    def test_selected_worker_import_contains_one_tx_and_no_other_maps(self):
        normalized=self.manager._normalize(self.payload,map_job=True)
        self.assertEqual(list(normalized['_worker_import']['scenarios']),['tx_0'])
        self.assertEqual(normalized['_worker_import']['scenarios']['tx_0']['provenance']['source_sha256'],'source')

    def test_path_key_includes_rx_and_path_sampling(self):
        original=self.manager._normalize(self.payload,map_job=False)['cache_key']
        for change in [{'receiver_ids':['rx_1']},{'samples_per_src':200000}]:
            self.assertNotEqual(original,self.manager._normalize({**self.payload,**change},map_job=False)['cache_key'])

    def test_changed_source_rejected_until_reimported(self):
        self.scenario['provenance']['source_sha256']='stale'
        with self.assertRaises(HousionnaSimulationApiError) as error:self.key()
        self.assertEqual(error.exception.status,409)


class TransportAndMemoryTests(unittest.TestCase):
    def test_atomic_status_retries_transient_windows_handle_lock(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'status.json';atomic_json(path,{'status':'running'})
            original=os.replace;calls=0
            def replace(source,target):
                nonlocal calls
                calls+=1
                if calls<3:
                    self.assertEqual(json.loads(path.read_text()),{'status':'running'})
                    raise PermissionError('Transient Windows handle lock')
                return original(source,target)
            with patch('integrations.housionna_performance.os.replace',side_effect=replace):
                atomic_json(path,{'status':'completed'})
            self.assertEqual(json.loads(path.read_text()),{'status':'completed'})
            self.assertEqual(list(path.parent.glob('*.tmp')),[])

    def test_backend_preference_routes_to_requested_variant(self):
        with tempfile.TemporaryDirectory() as directory:
            library=Path(directory)/'LLVM-C.dll';library.write_bytes(b'library test stub')
            for requested,variant in [('llvm','llvm_ad_mono_polarized'),('cuda','cuda_ad_mono_polarized')]:
                mi=Mock();mi.variant.return_value=None;rt=object()
                with patch.dict('os.environ',{'SIONNA_RT_BACKEND':requested,'DRJIT_LIBLLVM_PATH':str(library)}),patch.dict(sys.modules,{'mitsuba':mi,'sionna':SimpleNamespace(rt=rt)}):
                    self.assertIs(rt_backend.load_rt()[0],rt)
                    mi.set_variant.assert_called_once_with(variant)
    def test_catalog_reuses_validated_bytes_but_checks_changed_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);exports=root/'exports';run=exports/'run';run.mkdir(parents=True)
            for suffix in ['_scene.xml','_txrx.json','_settings.json','_result.json']:(run/('test'+suffix)).write_text('{}')
            folder=root/'outputs/integrations/housionna/import';folder.mkdir(parents=True)
            atomic_json(folder/'viewer_import.json',{'schema_version':1,'adapter_version':ADAPTER_VERSION,
              'provenance':{'source_sha256':'source','path_endpoint_tolerance_m':.001},
              'run_metadata':{'run_id':'run','tx_count':1,'source_sha256':'source'},'scenario_order':['tx'],
              'scenarios':{'tx':{'transmitter':{'name':'tx_0'}}}})
            with patch.dict('os.environ',{'HOUSIONNA_RUNS_DIRECTORY':str(exports)}),patch('integrations.housionna._source_fingerprint',return_value=('source',{})),patch('integrations.housionna.import_run') as importer:
                self.assertEqual(discover_runs(root)[0]['status'],'valid');importer.assert_not_called()
            with patch.dict('os.environ',{'HOUSIONNA_RUNS_DIRECTORY':str(exports)}),patch('integrations.housionna._source_fingerprint',return_value=('changed',{})),patch('integrations.housionna.import_run',side_effect=ValueError('Changed export rejected')) as importer:
                self.assertEqual(discover_runs(root)[0]['status'],'invalid');importer.assert_called_once()

    def test_geometry_hash_optimization_detects_reordered_triangles(self):
        doc={'scenario_order':['tx'],'scenarios':{'tx':{'geometry_ref':'g','radio_map':{'surfaces':[{'mesh_ref':'m','values_db':[None,-80]}]}}},
          'assets':{'geometries':{'g':{'objects':[]}},'meshes':{'m':{'vertices_m':[[0,0,0],[1,0,0],[0,1,0]],'faces':[[0,1,2],[0,2,1]]}}}}
        original=_housionna_content_signature(doc)
        doc['assets']['meshes']['m']['faces'].reverse()
        self.assertNotEqual(original,_housionna_content_signature(doc))

    def test_bounded_import_cache_reuses_and_invalidates_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);reader=Mock(return_value={'value':'old'});cache=ImportCache(2)
            for name in ['a','b','c']:
                path=root/'outputs/integrations/housionna'/name/'viewer_import.json';path.parent.mkdir(parents=True);path.write_text('{}')
            cache.read(root,'a',reader);cache.read(root,'a',reader);self.assertEqual(reader.call_count,1)
            cache.read(root,'b',reader);cache.read(root,'c',reader);self.assertEqual(len(cache.entries),2)
            (root/'outputs/integrations/housionna/c/viewer_import.json').write_text('{"changed":true}')
            cache.read(root,'c',reader);self.assertEqual(reader.call_count,4)

    def test_gzip_preserves_null_masks_and_triangle_order(self):
        expected={'surfaces':[{'values_db':[None,-42.25,-999.0]*3000}]}
        class Handler(DashboardHandler):
            def do_GET(self):self._send_json(200,expected)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            request=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/',headers={'Accept-Encoding':'gzip'})
            with urllib.request.urlopen(request,timeout=3) as response:
                self.assertEqual(response.headers['Content-Encoding'],'gzip')
                wire=response.read();self.assertEqual(json.loads(gzip.decompress(wire)),expected)
                self.assertLess(len(wire),int(response.headers['X-Uncompressed-Bytes']))
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
