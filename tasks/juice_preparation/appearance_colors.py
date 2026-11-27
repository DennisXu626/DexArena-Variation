"""Deterministic texture transforms used by the reviewed Juice schemes."""
import colorsys
import numpy as np
from PIL import Image

def rgb_hex(color):
    return np.array([int(color[i:i+2], 16)/255 for i in (1, 3, 5)])

def linear_rgba(color):
    rgb = rgb_hex(color)
    return [*np.where(rgb <= .04045, rgb/12.92, ((rgb+.055)/1.055)**2.4), 1.]

def recolor_apple(rgba, color, match_target=False):
    source = Image.fromarray(rgba).convert("RGB")
    hsv = np.asarray(source.convert("HSV"), dtype=np.float32) / 255
    hue,sat,value = np.moveaxis(hsv,-1,0)
    target_h,target_s,target_v = colorsys.rgb_to_hsv(*rgb_hex(color))
    warm = (hue + .5) % 1 - .5
    weight = np.clip((warm+.13)/.095,0,1) * np.clip((.22-warm)/.06,0,1)
    weight *= np.clip((sat-.10)/.30,0,1) * np.clip((value-.20)/.27,0,1)
    mapped = np.stack(((target_h + .19*warm) % 1,
                       np.clip(sat * .36 + target_s*.42,0,1),
                       np.clip(value*.97+.015,0,1)),axis=-1)
    if match_target:
        # Include pale/yellow skin while protecting green stem and dark creases.
        # Map saturation/value as well as hue for white, black and vivid colors.
        weight = np.clip((warm+.13)/.06,0,1) * np.clip((.24-warm)/.04,0,1)
        weight *= np.clip((sat-.025)/.075,0,1)
        # The source atlas contains cool gray skin islands. Hue-based selection
        # misses them, so include neutral skin regardless of its unstable hue.
        neutral_skin = np.clip((.30-sat)/.12,0,1)
        weight = np.maximum(weight, neutral_skin) * np.clip((value-.12)/.15,0,1)
        mapped = np.stack(((target_h+.04*np.where(sat < .30, 0., warm)) % 1,
                           np.clip(target_s*(.88+.12*sat),0,1),
                           np.clip(target_v*(.40+.70*value),0,1)),axis=-1)
    colors = np.asarray(Image.fromarray(np.rint(mapped*255).astype(np.uint8),"HSV").convert("RGB"))
    rgba[..., :3] = np.rint((1-weight[...,None])*np.asarray(source) + weight[...,None]*colors)
    return rgba

def recolor_shell(rgba, color):
    rgb = rgba[..., :3].astype(np.float32) / 255
    luminance = rgb @ np.array([.2126,.7152,.0722], dtype=np.float32)
    strength = np.clip((luminance-.05)/.25, .48, .88) * np.clip((.96-luminance)/.20, 0, 1)
    shade = np.clip((.37 + luminance)[...,None]*rgb_hex(color) + (luminance*.23)[...,None],0,1)
    rgba[..., :3] = np.rint(((1-strength[...,None])*rgb + strength[...,None]*shade)*255)
    return rgba
