"""Controlled real CPU/GPU runs; never edits the export or changes RF presets."""
from pathlib import Path
import argparse
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from integrations.housionna_simulation import HousionnaLiveSimulationManager
from integrations.housionna_performance import atomic_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, default=ROOT/'outputs/live/.housionna-jobs/21c8eee8fdea48dabdee03864c9c592d/request.json')
    parser.add_argument('--output', type=Path, default=ROOT/'outputs/performance_refinement/benchmark.json')
    parser.add_argument('--timeout', type=int, default=120)
    parser.add_argument('--force-recompute',action='store_true',help='Save new realizations with unchanged seeds; preserve all existing result files')
    args=parser.parse_args()
    spec=json.loads(args.request.read_text(encoding='utf-8'))
    allowed={'source_run_id','import_id','transmitter','receiver_ids','tx_position','tx_orientation','frequency_hz','solver','samples_per_src','seed','quality'}
    request={k:v for k,v in spec.items() if k in allowed}
    manager=HousionnaLiveSimulationManager(ROOT)
    manager.timeouts.update(low=args.timeout, medium=args.timeout, high=args.timeout)
    report={'runtime':manager.runtime,'request':request,'runs':[],'comparisons':[]}
    arrays={}
    cases=[('cold','low',42,False),('warm_modified_tx','low',42,True),('cached','low',42,False),
           ('medium_seed42','medium',42,False),('high_seed42','high',42,False),
           ('low_seed43','low',43,False),('medium_seed43','medium',43,False),('high_seed43','high',43,False)]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    for name,quality,seed,move in cases:
        payload={**request,'quality':quality,'seed':seed}
        if move:payload['tx_position']=[request['tx_position'][0]+0.2,*request['tx_position'][1:]]
        started=time.perf_counter()
        original_lookup=manager._find_cached
        if args.force_recompute and name!='cached':manager._find_cached=lambda key:None
        job=manager.start(payload,map_job=True)
        manager._find_cached=original_lookup
        submission=time.perf_counter()-started
        while manager.active_job_id:
            time.sleep(.05)
        result=manager.result(job['job_id'])
        row={'case':name,'quality':quality,'seed':seed,'job_id':job['job_id'],'cache_hit':job.get('cache_hit',False),
             'submission_seconds':submission,'wall_seconds':time.perf_counter()-started,'status':result['status']}
        if result['status']=='completed':
            metadata=result['radio_map']['metadata']
            row['metadata']=metadata
            values=result['radio_map']['surfaces'][0]['values_db']
            arrays[name]=values
            import numpy as np
            valid=np.array([v for v in values if v is not None])
            row['summary_db']={'mean':float(valid.mean()) if valid.size else None,'median':float(np.median(valid)) if valid.size else None}
        else:row['error']=result.get('error')
        report['runs'].append(row)
        atomic_json(args.output,report)
        print(json.dumps({k:row[k] for k in ('case','status','cache_hit','wall_seconds','job_id')}),flush=True)
    pairs=[('cold','medium_seed42'),('medium_seed42','high_seed42'),('cold','high_seed42'),
           ('cold','low_seed43'),('medium_seed42','medium_seed43'),('high_seed42','high_seed43')]
    baseline=ROOT/'outputs/live/housionna-maps/04a2e48cde2b4163ad94c37e94fe6853/radio_map.json'
    if baseline.is_file():
        old=json.loads(baseline.read_text(encoding='utf-8'))
        old_inputs=old['metadata']
        if (old_inputs.get('source_run_id')==request['source_run_id'] and old_inputs.get('transmitter')==request['transmitter']
            and old_inputs.get('frequency_hz')==request['frequency_hz'] and old_inputs.get('tx_position_m')==request['tx_position']
            and old_inputs.get('tx_orientation_rad', [0,0,0])==request['tx_orientation']):
            arrays['pre_optimization']=old['surfaces'][0]['values_db']
            pairs.append(('pre_optimization','cold'))
    for a,b in pairs:
        if a not in arrays or b not in arrays:continue
        left,right=arrays[a],arrays[b]
        if len(left)!=len(right):continue
        jointly=[(x,y) for x,y in zip(left,right) if x is not None and y is not None]
        delta=np.array([y-x for x,y in jointly])
        report['comparisons'].append({'left':a,'right':b,'jointly_valid_cells':len(jointly),
          'same_missing_mask':all((x is None)==(y is None) for x,y in zip(left,right)),
          'mean_delta_db':float(delta.mean()) if delta.size else None,'rmse_db':float(np.sqrt(np.mean(delta**2))) if delta.size else None,
          'abs_delta_percentiles_db':dict(zip(['p50','p90','p99','max'],map(float,np.percentile(np.abs(delta),[50,90,99,100])))) if delta.size else {},
          'left_joint_mean_db':float(np.mean([x for x,y in jointly])) if jointly else None,
          'right_joint_mean_db':float(np.mean([y for x,y in jointly])) if jointly else None})
    atomic_json(args.output,report)


if __name__=='__main__':main()
