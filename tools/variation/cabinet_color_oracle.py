"""PR10 named-color oracle: pure CPU logic, independent of the runtime catalog.

Hue windows allow shading/8-bit quantization around Dennis's named palette.
Neutral, near-black and low-chroma pixels never count as a target color.
Original is a pixel-restoration test, not a fourth color class.
"""
import numpy as np
from PIL import Image

HUE_DEGREES = {'ocean': (170., 230.), 'citrus': (25., 65.), 'violet': (260., 305.)}
MIN_SATURATION = .25
MIN_VALUE = 26
MIN_CHANNEL_SPAN = 18
MIN_COLOR_FRACTION = .60


def named_color_mask(rgb, scheme):
    if scheme not in HUE_DEGREES:
        raise ValueError('Only ocean/citrus/violet have a color oracle; original uses exact restoration')
    pixels = np.asarray(rgb, dtype=np.uint8)[..., :3]
    shape = pixels.shape[:-1]
    hsv = np.asarray(Image.fromarray(pixels.reshape(1, -1, 3), 'RGB').convert('HSV')).reshape(*shape, 3)
    hue = hsv[..., 0].astype(float) * (360. / 255.)
    low, high = HUE_DEGREES[scheme]
    span = np.ptp(pixels.astype(np.int16), axis=-1)
    return ((hue >= low) & (hue <= high) & (hsv[..., 1] >= 255 * MIN_SATURATION)
            & (hsv[..., 2] >= MIN_VALUE) & (span >= MIN_CHANNEL_SPAN))


def color_metrics(rgb, scheme, spatial_mask=None):
    pixels = np.asarray(rgb, dtype=np.uint8)[..., :3]
    valid = ((pixels.max(-1) >= MIN_VALUE)
             & (np.ptp(pixels.astype(np.int16), axis=-1) >= MIN_CHANNEL_SPAN))
    if spatial_mask is not None:
        valid &= np.asarray(spatial_mask, dtype=bool)
    matched = named_color_mask(pixels, scheme) & valid
    count = int(np.count_nonzero(matched))
    denominator = int(np.count_nonzero(valid))
    return {'scheme_id': scheme, 'matched_pixels': count, 'chromatic_pixels': denominator,
            'matched_fraction': count / denominator if denominator else 0.,
            'hue_window_degrees': list(HUE_DEGREES[scheme]),
            'min_saturation': MIN_SATURATION, 'min_value': MIN_VALUE,
            'min_channel_span': MIN_CHANNEL_SPAN}


def require_color(rgb, scheme, minimum_pixels, spatial_mask=None):
    result = color_metrics(rgb, scheme, spatial_mask)
    assert result['matched_pixels'] >= minimum_pixels, ('Insufficient named-color pixels', result)
    assert result['matched_fraction'] >= MIN_COLOR_FRACTION, ('Wrong dominant color in object ROI', result)
    return result
