"""Compatibility names for pixel adapters.

TableCleanBase now owns batched construction and partial reset. The old
single-env trampoline would size appearance records for one row; the old
builder shim would duplicate explicitly scoped actors across every scene.
PixelObsMixin therefore delegates directly to the production task.
"""


class TableCleanMixin:
    pass


class DumpDustpanMixin(TableCleanMixin):
    pass
