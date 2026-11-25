"""Independently re-solve representative vertices of the compiled joint cells."""
import json
from itertools import product
from pathlib import Path

import numpy as np
from build_pipette_workspace import TABLE, TASKS
from pipette_workspace_motion import screen


def main():
    out=Path(__file__).resolve().parents[2]/'docs/variation/evidence/pipette_workspace'
    source=json.loads((out/'BUILD.json').read_bytes())
    catalog=json.loads(TABLE.read_bytes())
    counts={}
    for task in TASKS:
        record=source[task]
        objects=record['objects']
        fixed={k:{field:np.array(v) for field,v in chain.items()} for k,chain in record['chains'].items()}
        counts[task]={}
        for yaw,nodes in catalog['tasks'][task]['cells'].items():
            nodes=np.asarray(nodes,dtype=float)
            rng=np.random.default_rng(9017+int(yaw))
            indices=np.unique(np.r_[np.argmin(nodes,axis=0),np.argmax(nodes,axis=0),
                                    rng.choice(len(nodes),12,replace=False)])
            corners=np.asarray(list(product([-1,1],repeat=nodes.shape[1])))
            witnesses=(nodes[indices,None]+catalog['half_mm']*corners)/1000
            cases=np.unique(witnesses.reshape(-1,nodes.shape[1]),axis=0)
            ok=np.ones(len(cases),dtype=bool)
            max_error=0.
            for j,obj in enumerate(objects):
                other='rack' if obj=='cup' else 'cup'
                geom={**record['geometry'][obj],'cell_corner':0}
                # The lookup stores metre-valued world points. Perturb the two
                # object positions independently, exercising mixed-sign corners.
                for slots in np.array_split(np.arange(len(cases)),1+len(cases)//220):
                    rows=cases[slots]
                    passed,err,_,_=screen(fixed[obj],rows[:,:2],rows[:,2+2*j:4+2*j],int(yaw),geom,
                                           'right' if obj=='cup' else 'left',passive=fixed.get(other))
                    ok[slots]&=passed
                    max_error=max(max_error,float(err.max()))
            counts[task][yaw]=dict(cells=len(indices),distinct_vertices=len(cases),passed=int(ok.sum()),
                max_tip_error_mm=max_error*1000,failed_world_xy_m=cases[~ok].tolist())
    print(json.dumps({k:{y:[g['passed'],g['distinct_vertices']] for y,g in v.items()}
                      for k,v in counts.items()}))
    (out/'CELL_VERTICES.json').write_text(json.dumps(counts,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()

