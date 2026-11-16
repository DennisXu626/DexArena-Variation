"""Panel-rack source roles for the real single-environment furniture preview.

Only describes the already loaded rack. A preview binder owns actual shape/
part inspection, captured-native restoration and evidence; this is not a task
appearance interface or a physics/geometry builder.
"""

OBJECT_ID = "panel_rack"
SUPPORTED_TASKS = ("FurnitureAssemblyLayFlatPanel-Sharpa-v1",)


def get_definition(env):
    """Return the source PBR signatures and real rack entity after task reset."""
    base = env.unwrapped
    task_id = getattr(getattr(base, "spec", None), "id", None)
    if (type(base).__name__ != "FurnitureAssemblyLayFlatPanelEnv"
            or base.num_envs != 1
            or (task_id is not None and task_id not in SUPPORTED_TASKS)):
        raise ValueError("panel_rack preview supports only one real LayFlatPanel-Sharpa environment")
    if not base.visual_detail:
        raise ValueError("panel_rack preview requires visual_detail=True (32 source visual shapes)")
    if not hasattr(base, "rack"):
        raise ValueError("The selected task has no panel-rack actor")
    raw, = base.rack._objs
    entity = getattr(raw, "entity", raw)
    matrix = entity.pose.to_transformation_matrix()
    target = [float(matrix[i, 3] + 0.045 * matrix[i, 2]) for i in range(3)]
    return {
        "entities": [("rack", entity)],
        "roles": {
            "body": {
                "native": {"base_color": [0.29, 0.31, 0.34, 1.0], "roughness": 0.55, "metallic": 0.35},
                "editable": True,
                "expected_shape_count": 8,
            },
            "plate": {
                "native": {"base_color": [0.21, 0.23, 0.26, 1.0], "roughness": 0.70, "metallic": 0.30},
                "editable": True,
                "expected_shape_count": 1,
            },
            "pad": {
                "native": {"base_color": [0.12, 0.14, 0.16, 1.0], "roughness": 0.9, "metallic": 0.0},
                "editable": False,
                "expected_shape_count": 6,
            },
            "bolt": {
                "native": {"base_color": [0.62, 0.64, 0.67, 1.0], "roughness": 0.30, "metallic": 0.90},
                "editable": False,
                "expected_shape_count": 8,
            },
            "decal": {
                "native": {"base_color": [0.85, 0.68, 0.15, 1.0], "roughness": 0.55, "metallic": 0.0},
                "editable": False,
                "expected_shape_count": 9,
            },
        },
        "expected_shape_count": 32,
        "detail": {"target": target, "eye_offset": [0.48, -0.48, 0.34]},
    }
