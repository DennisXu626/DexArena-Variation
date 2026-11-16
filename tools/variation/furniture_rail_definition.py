"""Source-derived rail-body definition for the furniture authoring preview.

This selects only the real rail_body link of an already reset, single-env
InsertRail or FastenScrew task. It never includes screw_head, builds geometry,
changes physics, resets or steps the task. The shared preview binder validates
the native PBR signatures and the task-specific shape counts before editing.
"""

OBJECT_ID = 'rail'
SUPPORTED_TASKS = (
    'FurnitureAssemblyInsertRail-Sharpa-v1',
    'FurnitureAssemblyFastenScrew-Sharpa-v1',
)

_TASK_CLASSES = {
    'FurnitureAssemblyInsertRailEnv': SUPPORTED_TASKS[0],
    'FurnitureAssemblyFastenScrewEnv': SUPPORTED_TASKS[1],
}


def _single_entity(link):
    """ManiSkill Link stores a SAPIEN component; Actor may store an Entity."""
    import sapien

    objects = list(link._objs)
    if len(objects) != 1:
        raise ValueError('Rail preview requires exactly one real rail_body')
    raw = objects[0]
    if isinstance(raw, sapien.Entity):
        return raw
    entity = getattr(raw, 'entity', None)
    if isinstance(entity, sapien.Entity):
        return entity
    raise TypeError('rail_body must resolve to a SAPIEN Entity or component.entity')


def get_definition(env):
    """Return semantic entities, native PBR roles and a world-space detail view."""
    base = env.unwrapped
    task_id = _TASK_CLASSES.get(type(base).__name__)
    if task_id is None or base.num_envs != 1:
        raise ValueError('Rail preview supports one real InsertRail or FastenScrew environment')
    declared_id = getattr(getattr(env, 'spec', None), 'id', None)
    if declared_id is not None and declared_id != task_id:
        raise ValueError(f'Unsupported rail task ID: {declared_id}')
    if not base.visual_detail:
        raise ValueError('Rail authoring preview requires visual_detail=True')
    entity = _single_entity(base.rail_body)
    if entity != _single_entity(base.rail.links_map['rail_body']):
        raise ValueError('rail_body handle does not belong to the task rail articulation')
    # Keep the current native builder's difference. In InsertRail, the two
    # lip and nine stamped-slot visuals are inside the two-flange loop and
    # therefore occur twice. FastenScrew's _add_rail_body adds them once.
    # The preview must preserve this geometry rather than fix the builder.
    detail_count = 22 if task_id == SUPPORTED_TASKS[0] else 11
    roles = {
        'metal_body': {
            'native': {
                'base_color': [0.66, 0.68, 0.72, 1.0],
                'roughness': 0.28,
                'metallic': 0.92,
            },
            'editable': True,
            'expected_shape_count': 3,
        },
        'channel_details': {
            'native': {
                'base_color': [0.42, 0.44, 0.48, 1.0],
                'roughness': 0.42,
                'metallic': 0.85,
            },
            'editable': True,
            'expected_shape_count': detail_count,
        },
    }
    return {
        'entities': [('rail_body', entity)],
        'roles': roles,
        'expected_shape_count': 3 + detail_count,
        'detail': {
            'target': [float(value) for value in entity.pose.p],
            'eye_offset': [0.22, -0.32, 0.25],
        },
    }
