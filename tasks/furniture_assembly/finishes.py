"""Original wood-grain maps for the furniture panel's native cube UVs."""

from functools import lru_cache

import numpy as np


# Annual-ring frequency, drift, latewood contrast, pores, and knot (x, y, spread).
WOOD_FINISHES = {
    'white_oak': (21, .078, .37, .062, None),
    'black_walnut': (12, .118, .38, .030, (.69, .69, .075)),
    'black_cherry': (17, .053, .28, .014, (.33, .31, .041)),
    'grey_ash': (26, .092, .37, .074, None),
    'birch': (35, .025, .23, .012, (.79, .41, .035)),
    'sapele': (44, .038, .37, .014, None),
    'maple': (24, .031, .24, .019, (.54, .61, .034)),
}

# SAPIEN's native cube uses a 4 by 3 UV cross. Each entry gives the tile
# (column, row), then the two axes in the unrotated panel's local XY space.
# The three separate face boxes share this panel-space grain field.
_FACE_TILES = (
    (0, 1, -1, -1, -1, 1),  # -X
    (1, 1, -1, 1, -1, 1),  # +Z
    (2, 1, 1, 1, -1, 1),  # +X
    (3, 1, 1, -1, -1, 1),  # -Z
    (1, 0, -1, 1, -1, -1),  # -Y
    (1, 2, -1, 1, 1, 1),  # +Y
)


def grain_tone(finish, x, y):
    """Sample longitudinal growth rings and continuous pores in panel space."""
    rings, drift, contrast, pores, knot = WOOD_FINISHES[finish]
    flow = y + drift * (np.sin(4.7 * x + 2.1 * y) + .42 * np.sin(10.2 * x - 3.4 * y))
    if finish == 'sapele':
        # Ribbon figure from alternating rows of interlocked grain.
        figure = .11 * (.5 + .5 * np.sin(46 * y + 1.8 * np.sin(4 * x)))
    else:
        figure = .054 * np.sin(22 * flow + .8 * np.sin(9.1 * x)) ** 2
    if knot is not None:
        cx, cy, spread = knot
        radius = np.hypot((x - cx) * .35, y - cy)
        flow += .7 * (y - cy) * np.exp(-radius ** 2 / spread ** 2)
        figure += .22 * np.exp(-radius ** 2 / (.29 * spread) ** 2)
    phase = 2 * np.pi * rings * flow + .67 * np.sin(15 * y + 5 * x)
    latewood = (.5 + .5 * np.sin(phase)) ** 3
    vessels = (.5 + .5 * np.sin(2.37 * phase + 2.1 * np.sin(17.6 * x))) ** 5
    return np.clip(1 - contrast * latewood - pores * vessels - figure, .57, 1)


@lru_cache(maxsize=96)
def panel_albedo(finish, color, center, half_size, width, height):
    """Bake the finish into the existing UV layout without editing mesh data."""
    rgba = np.broadcast_to(np.asarray(color, dtype=np.float32), (height, width, 4)).copy()
    if finish != 'plain':
        u = np.arange(width, dtype=float)[None, :] + .5
        v = np.arange(height, dtype=float)[:, None] + .5
        cx, cy = center
        hx, hy = half_size
        for col, row, x0, x1, y0, y1 in _FACE_TILES:
            tile_u, tile_v = 4 * u / width - col, 3 * v / height - row
            columns = (tile_u[0] >= 0) & (tile_u[0] < 1)
            rows = (tile_v[:, 0] >= 0) & (tile_v[:, 0] < 1)
            x = cx + hx * (x0 + (x1 - x0) * tile_u[:, columns])
            y = cy + hy * (y0 + (y1 - y0) * tile_v[rows, :])
            tone = grain_tone(finish, x / .40 + .5, y / .20 + .5)
            rgba[np.ix_(rows, columns, [0, 1, 2])] *= tone[..., None]
    rgba.flags.writeable = False
    return rgba


class PanelSurface:
    """Own one stable texture handle for a bound main panel face."""

    def __init__(self, material, shape, texture_class):
        self.material = material
        self.source = source = material.base_color_texture
        self.center = tuple(float(value) for value in shape.local_pose.p[:2])
        self.half_size = tuple(float(value) for value in shape.half_size[:2])
        if source is None:
            # The raster shader samples the albedo map IN PLACE OF base_color.
            # Use float32 and nearest so original reproduces the exact scalar.
            self.original_pixels = panel_albedo('plain', tuple(material.base_color),
                                                self.center, self.half_size, 384, 288)
            descriptor = dict(format='R32G32B32A32Sfloat', filter_mode='nearest')
        else:
            self.original_pixels = source.download().copy()
            if self.original_pixels.ndim != 3 or self.original_pixels.shape[2] not in (3, 4):
                raise ValueError('Furniture native albedo must be RGB or RGBA')
            descriptor = dict(format=source.format, mipmap_levels=source.mipmap_levels,
                              filter_mode=source.filter_mode, address_mode=source.address_mode,
                              srgb=source.is_srgb)
        self.texture = texture_class(array=self.original_pixels, **descriptor)
        self.current = 'original'
        material.base_color_texture = self.texture

    def pixels(self, scheme_id, finish=None, color=None):
        if scheme_id == 'original':
            return self.original_pixels
        height, width = self.original_pixels.shape[:2]
        pixels = panel_albedo(finish, tuple(color), self.center, self.half_size, width, height)
        if self.source is None:
            return pixels
        rgb = pixels[..., :3]
        if self.source.is_srgb:
            rgb = np.where(rgb <= .0031308, 12.92 * rgb, 1.055 * rgb ** (1 / 2.4) - .055)
        encoded = self.original_pixels.copy()
        if np.issubdtype(encoded.dtype, np.integer):
            rgb = np.rint(rgb * np.iinfo(encoded.dtype).max)
        encoded[..., :3] = rgb
        return encoded

    def apply(self, scheme_id, finish=None, color=None):
        if scheme_id != self.current:
            self.texture.upload(self.pixels(scheme_id, finish, color))
            self.current = scheme_id
