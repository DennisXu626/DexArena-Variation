"""Read-only source definition for two real furniture screw representations.

Only the screw_head link is selected. The rail_body link, joints, geometry,
physics, poses and task predicates are never written by this module.
"""

OBJECT_ID = 'screw'
SUPPORTED_TASKS = (
    'FurnitureAssemblyInsertRail-Sharpa-v1',
    'FurnitureAssemblyFastenScrew-Sharpa-v1',
)


def _role(color, roughness, metallic, editable, shape_count):
    return {
        'native': {'base_color': color, 'roughness': roughness, 'metallic': metallic},
        'editable': editable,
        'expected_shape_count': shape_count,
    }


def _world_center(entity, local_height):
    """Transform a point on the local screw axis without changing any pose."""
    pose = entity.pose
    p = [float(value) for value in pose.p]
    w, x, y, z = [float(value) for value in pose.q]
    normal = (2 * (x * z + w * y), 2 * (y * z - w * x),
              1 - 2 * (x * x + y * y))
    return [p[i] + local_height * normal[i] for i in range(3)]


def get_definition(env):
    """Describe this task's native head materials; binding stays with the caller.

    Both tasks use grip/reference with task-specific native signatures. In
    InsertRail, grip includes the floor, walls and chamfers of the cross head;
    the four gold caps stay native. In FastenScrew, the brass stem and stripe
    share one preserved native material role.
    """
    base = env.unwrapped
    task_id = getattr(getattr(env, 'spec', None), 'id', None)
    if task_id is None:
        task_id = getattr(getattr(base, 'spec', None), 'id', None)
    if task_id not in SUPPORTED_TASKS or base.num_envs != 1:
        raise ValueError('Screw preview requires one env of a supported formal furniture task')
    raw, = base.screw_head._objs
    entity = getattr(raw, 'entity', raw)
    if task_id == SUPPORTED_TASKS[0]:
        roles = {
            'grip': _role([0.08, 0.09, 0.10, 1.0], 0.55, 0.55, True, 17),
            'reference': _role([0.96, 0.82, 0.30, 1.0], 0.55, 0.25, False, 4),
        }
        total, local_height = 21, 0.004
        offset = [0.055, -0.075, 0.085]
    else:
        roles = {
            'grip': _role([0.10, 0.10, 0.11, 1.0], 0.60, 0.10, True, 2),
            'reference': _role([0.92, 0.78, 0.26, 1.0], 0.50, 0.30, False, 2),
        }
        total, local_height = 4, 0.026
        offset = [0.10, -0.15, 0.13]
    return {
        'entities': [('screw_head', entity)],
        'roles': roles,
        'expected_shape_count': total,
        'detail': {'target': _world_center(entity, local_height), 'eye_offset': offset},
    }
