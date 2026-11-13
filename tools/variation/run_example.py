"""Portable version of the accepted M2 example: load/reset, optional one frame.

Run only with resource permission. Does not execute a policy or complete a task.
Path/metadata adaptation only; the accepted task implementation is unchanged.
"""
import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', default=str(Path(__file__).resolve().parents[2]))
parser.add_argument('--config', required=True)
parser.add_argument('--output', required=True)
parser.add_argument('--task', choices=['PickBottle', 'UnscrewCap'], default='UnscrewCap')
parser.add_argument('--num-envs', type=int, default=1)
parser.add_argument('--seed', type=int, default=7)
parser.add_argument('--render-once', action='store_true')
args = parser.parse_args()
source = Path(args.source).resolve()
out = Path(args.output).resolve()
out.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(source))
import gymnasium as gym
import torch
import tasks

config_path = Path(args.config).resolve()
config = json.loads(config_path.read_text(encoding='utf-8-sig'))
config.update(manifest_ref='manifest.json', config_ref=args.config, record_path=str(out / 'episodes.jsonl'))
revision = subprocess.run(['git', '-C', str(source), 'rev-parse', 'HEAD'], capture_output=True, text=True)
manifest = {
    'base_code_commit': 'e7d5c49d079153e77da1ce2bfde16edf67ee7fa8',
    'team_commit': revision.stdout.strip() if revision.returncode == 0 else None,
    'config': config, 'task_id': f'CabinetPouring{args.task}-Sharpa-v1',
    'num_envs': args.num_envs, 'seed': args.seed,
    'versions': {p: metadata.version(p) for p in ['torch', 'sapien', 'mani_skill', 'numpy', 'gymnasium']},
    'slurm_job_id': os.environ.get('SLURM_JOB_ID'), 'pilot_file_sha256': {},
    'asset_source_note': 'External object resources supplied separately; see docs/variation/PROVENANCE.md. '
                         'This run does not rehash all external or robot assets.',
    'status': 'started',
}
# Only four pilot source files and the tiny project-authored appearance pool.
files = [source / 'tasks/cabinet_pouring' / name for name in
         ['cabinet_pouring_long.py', 'cabinet_pouring_pick_bottle.py',
          'cabinet_pouring_unscrew_cap.py', 'variation.py']]
files += sorted((source / 'tasks/assets/variation/cabinet_pouring/v1').iterdir())
for file in files:
    if file.is_file():
        manifest['pilot_file_sha256'][file.relative_to(source).as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
env = None
try:
    start = time.monotonic()
    env = gym.make(manifest['task_id'], num_envs=args.num_envs, obs_mode='state',
                   render_mode='rgb_array', variation=config)
    manifest['make_s'] = time.monotonic() - start
    e = env.unwrapped
    manifest['runtime'] = {'device': str(e.device), 'gpu_sim_enabled': e.gpu_sim_enabled,
                           'backend': repr(e.backend), 'robot_uid': e.agent.uid,
                           'reconfiguration_freq': e.reconfiguration_freq}
    start = time.monotonic()
    env.reset(seed=args.seed)
    manifest['reset_s'] = time.monotonic() - start

    def plain(value):
        if isinstance(value, dict):
            return {key: plain(v) for key, v in value.items()}
        return value.detach().cpu().tolist() if torch.is_tensor(value) else value

    (out / 'state.json').write_text(json.dumps(plain(e.get_state_dict()), indent=2), encoding='utf-8')
    if args.render_once:
        from PIL import Image
        frame = env.render().cpu().numpy()
        if frame.ndim == 3:
            frame = frame[None]
        for i, image in enumerate(frame):
            Image.fromarray(image[..., :3]).save(out / f'env_{i}.png')
    manifest['status'] = 'loaded_reset_and_optional_single_frame_only'
except Exception:
    manifest.update(status='failed', error=traceback.format_exc())
    raise
finally:
    if env is not None:
        env.close()
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
