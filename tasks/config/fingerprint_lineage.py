"""Record-neutral fingerprint transitions of the released environments.

A dataset's certificate (``meta/recording_integrity.json``) and the identity in its
replay sidecar (``replay/source_*/meta.json``) carry the per-environment code
fingerprint (``tasks.config.code_fingerprint``) of the build that recorded it. Some
later edits move that fingerprint without changing anything the environment records,
for example a fix that only acts on a simulation backend the data was not recorded
with. Such an edit is registered here as ``(old, new, evidence)`` once it has been
measured record-neutral, and every tool that compares a recorded fingerprint with the
current build resolves both through :func:`resolve` first. The dataset files keep the
fingerprint they were written with.

An edit that changes what the environment records is a new version, not a lineage
entry: data recorded under the old fingerprint stays a separate dataset and keeps
reporting ``fingerprint DRIFT``.
"""
from __future__ import annotations

from typing import Mapping, Sequence

_GPU_STAGE_BODY_WEIGHT = (
    "tasks/cabinet_pouring/cabinet_pouring_long.py: _apply_gpu_stage_body_weight added to "
    "_before_simulation_step. On physx_cuda, set_disable_gravity(False) changes the flag but "
    "not the simulation, so the detached cap twin and the open bottle were weightless and, with "
    "zero linear damping, drifted at constant velocity; the method applies m*g to them on every "
    "substep on the GPU backend only and returns before reading or writing anything on the CPU "
    "backend the datasets were recorded with. Record-neutral: recordings through the "
    "teleoperation entry point (fixed seed) before and after the edit are byte-identical "
    "(episode.npz, raw_states.pkl, env_states.pkl) on all five targets of the family; CPU "
    "action replay of three UnscrewCap episodes that cross attached cap -> free twin -> placed "
    "-> open bottle gives an identical per-step state hash chain before and after (3/3); "
    "replay_success_rate over the released OpenCabinet and UnscrewCap datasets gives the same "
    "per-episode verdicts before and after."
)

#: env_id -> ((old_fingerprint, new_fingerprint, evidence), ...), 12-hex prefixes.
LINEAGE: Mapping[str, Sequence[tuple[str, str, str]]] = {
    "CabinetPouringLong-Sharpa-v1": (
        ("75ebc737dcbb", "48d4ba761ad7", _GPU_STAGE_BODY_WEIGHT),
    ),
    "CabinetPouringOpenCabinet-Sharpa-v1": (
        ("2accab13a715", "141205a29a6e", _GPU_STAGE_BODY_WEIGHT),
    ),
    "CabinetPouringPickBottle-Sharpa-v1": (
        ("8a4a1e792709", "a7853bbc4f11", _GPU_STAGE_BODY_WEIGHT),
    ),
    "CabinetPouringPourBeads-Sharpa-v1": (
        ("5071b207bc01", "b2122d450589", _GPU_STAGE_BODY_WEIGHT),
    ),
    "CabinetPouringUnscrewCap-Sharpa-v1": (
        ("827f7215c131", "e7828140b26f", _GPU_STAGE_BODY_WEIGHT),
    ),
}


def _bare(version: str) -> str:
    return version[3:] if version.startswith("fp:") else version


def resolve(env_id: str, version: str) -> str:
    """The head of ``version``'s chain for ``env_id``; unchanged when no entry applies.

    Accepts and returns either the bare 12-hex form or the certificate's ``fp:`` form.
    """
    prefix = "fp:" if version.startswith("fp:") else ""
    current = _bare(version)[:12]
    chain = {old: new for old, new, _evidence in LINEAGE.get(env_id, ())}
    seen = set()
    while current in chain and current not in seen:
        seen.add(current)
        current = chain[current]
    return prefix + current


def equivalent(env_id: str, a: str, b: str) -> bool:
    """Whether two fingerprints of ``env_id`` resolve to the same head."""
    return resolve(env_id, a)[-12:] == resolve(env_id, b)[-12:]
