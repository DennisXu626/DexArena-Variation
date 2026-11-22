"""One family appearance draw per selected environment and episode."""
import copy
import json
from pathlib import Path

import numpy as np

CATALOG = Path(__file__).resolve().parents[1] / 'assets/variation/drawer_plug/family_variants.json'


class FamilyAppearance:
    def __init__(self, config, num_envs, loaded):
        self.config = copy.deepcopy(config)
        self.loaded = loaded
        self.catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
        seed = int(self.config.get('seed', 0))
        self.rng = [np.random.default_rng(np.random.SeedSequence([seed, i])) for i in range(num_envs)]
        self.schemes = ['original'] * num_envs
        self.episodes = [0] * num_envs
        self.records = []

    def select(self, env_idx, options):
        override = options.get('family_appearance', {})
        choices = self.catalog['schemes']
        requests = []
        for i in env_idx.tolist():
            request = {**self.config, **self.config.get('per_env', {}).get(str(i), {}),
                       **override, **override.get('per_env', {}).get(str(i), {})}
            mode = request.get('mode', 'explicit')
            if mode == 'explicit':
                candidates = [request.get('scheme_id', 'original')]
            elif mode == 'random_choice':
                candidates = request.get('scheme_ids', [])
            else:
                raise ValueError(f'Unknown family appearance mode: {mode}')
            if not candidates or any(s not in choices for s in candidates):
                raise ValueError(f'Invalid family scheme selection: {candidates}')
            requests.append((i, mode, candidates))
        for i, mode, candidates in requests:
            sid = candidates[0] if mode == 'explicit' else str(self.rng[i].choice(candidates))
            yield i, sid, choices[sid]

    def record(self, i, sid, mapping):
        self.schemes[i] = sid
        self.episodes[i] += 1
        self.records.append(dict(env_idx=i, episode_index=self.episodes[i], family_id=sid,
            catalog_version=self.catalog['version'],
            objects={obj: mapping[catalog] for obj, catalog in self.loaded.items()}))
