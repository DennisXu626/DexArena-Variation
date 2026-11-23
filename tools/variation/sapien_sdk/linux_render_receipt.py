"""Allow the private Linux launcher to observe a completed RGB readback."""

from contextlib import contextmanager


_observer = None


@contextmanager
def observe_render_readbacks(observer):
    global _observer
    previous, _observer = _observer, observer
    try:
        yield
    finally:
        _observer = previous


def record_render_readback():
    if _observer is not None:
        _observer()
