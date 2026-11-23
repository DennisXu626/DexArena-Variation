"""CPU fixtures for the production position parser and drawer frame transforms."""
import ast
import csv
import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from scipy.spatial.transform import Rotation
import torch


ROOT = Path(__file__).resolve().parents[2]
PLUG = ROOT / "tasks/drawer_plug"
spec = importlib.util.spec_from_file_location("layout", PLUG / "position_layout.py")
layout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layout)


def run(matrix):
    center = (-.11538825,-.00146325)
    env = SimpleNamespace(drawer_xy=(.18,.18),socket_center_xy=(-.125,-.38),
                          charger_place_center_xy=(-.29,-.61),charger_place_radius=.14,
                          _charger_drawer_center=lambda:center)
    counts = dict(legal=0,rejected=0,placement_diagnostic=0)
    with matrix.open(encoding="utf-8",newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows)==76
    for row in rows:
        name=row["task"].removeprefix("DrawerPlug").removesuffix("-Sharpa-v1")
        idx=torch.tensor([int(row["env_idx"])])
        request=json.loads(row["request"])
        if row["kind"].startswith("native_predicate"):
            assert "diagnostic_place_center_xy_m" in request
            counts["placement_diagnostic"]+=1
            continue
        try:
            result=layout.requested_layout(env,{"position_layout":{row["env_idx"]:request}},idx,name)
        except ValueError:
            assert row["kind"]=="expected_reject",row
            counts["rejected"]+=1
        else:
            assert result and row["kind"]!="expected_reject"
            counts["legal"]+=1
    assert counts==dict(legal=62,rejected=5,placement_diagnostic=9)
    assert layout.requested_layout(env,{},torch.tensor([0,1]),"PickCharger") is None
    requests={"0":{"drawer_xy_m":[.13,.13],"drawer_yaw_deg":5},
              "1":{"drawer_xy_m":[.23,.23],"drawer_yaw_deg":-5}}
    selected=layout.requested_layout(env,{"position_layout":requests},torch.tensor([1,0]),"PickCharger")
    assert selected[0]["drawer_xy"]==[.23,.23] and selected[1]["drawer_yaw"]>0
    for invalid in [{"0":{"drawer_yaw_deg":float("nan")}},{"1":{"drawer_yaw_deg":0}},
                    {"0":{"drawer_xy_m":[.12999,.18]}},{"0":{"drawer_yaw_deg":False}}]:
        try:
            layout.requested_layout(env,{"position_layout":invalid},torch.tensor([0]),"OpenDrawer")
        except ValueError:
            pass
        else:
            raise AssertionError(invalid)
    source=ast.parse((PLUG/"drawer_plug_long.py").read_text(encoding="utf-8"))
    cls=next(node for node in source.body if isinstance(node,ast.ClassDef) and node.name=="DrawerPlugLongEnv")
    methods={"_drawer_local_to_world_xy","_world_to_drawer_local_xy","_out_of_drawer"}
    namespace={"torch":torch,"np":np}
    for node in cls.body:
        if isinstance(node,ast.FunctionDef) and node.name in methods:
            exec(compile(ast.Module(body=[node],type_ignores=[]),"<production drawer method>","exec"),namespace)
    yaws=torch.tensor([-5,5],dtype=torch.float64)*math.pi/180
    quat=torch.stack([torch.cos(yaws/2),yaws*0,yaws*0,torch.sin(yaws/2)],dim=1)
    motion=SimpleNamespace(drawer=SimpleNamespace(pose=SimpleNamespace(q=quat)),drawer_yaw=0.,
        _drawer_episode_xy=torch.tensor([[.13,.16],[.23,.22]],dtype=torch.float64),
        drawer_travel=torch.tensor([0.,.22],dtype=torch.float64),
        out_of_drawer_margin=.01,drawer_wall_top_z=.4,
        drawer_interior_x=(-.26,.25),drawer_interior_y=(-.26,.255))
    forward=namespace["_drawer_local_to_world_xy"]
    inverse=namespace["_world_to_drawer_local_xy"]
    motion._world_to_drawer_local_xy=lambda points,travel:inverse(motion,points,travel)
    point=torch.tensor([[-.295,.01],[-.115,-.02]],dtype=torch.float64)
    world=forward(motion,point,motion.drawer_travel,yaw=yaws)
    independent=np.stack([Rotation.from_euler("z", y).apply([p[0]-q,p[1],0])[:2]+o
                         for y,p,q,o in zip(yaws.numpy(),point.numpy(),
                                            motion.drawer_travel.numpy(),motion._drawer_episode_xy.numpy())])
    assert np.allclose(world.numpy(),independent)
    assert torch.allclose(inverse(motion,world,motion.drawer_travel),point)
    middle=torch.zeros((2,3),dtype=torch.float64)
    middle[:,:2]=world
    assert namespace["_out_of_drawer"](motion,middle).tolist()==[True,False]
    motion.drawer.pose.q=torch.tensor([[1.,0,0,0],[1,0,0,0]],dtype=torch.float64)
    legacy=forward(motion,point,motion.drawer_travel)
    assert torch.equal(inverse(motion,legacy,motion.drawer_travel).round(decimals=10),
                       point.round(decimals=10))
    width=next(ast.literal_eval(node.value) for node in source.body if isinstance(node,ast.Assign)
               and any(isinstance(t,ast.Name) and t.id=="DRAWER_PLUG_TASK_STATE_DIM" for t in node.targets))
    assert width==18
    print(json.dumps(dict(status="pass",point_matrix=counts,reset_index_order=[1,0],
                          inverse_and_outside_test=True,legacy_identity_frame=True,task_state_width=width)))


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("samples",type=Path)
    run(parser.parse_args().samples)
