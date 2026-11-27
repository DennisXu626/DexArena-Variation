"""Bake the accepted UV rim and produce bagel recolors from the installed asset."""
import numpy as np
from PIL import Image


def plate_rim(root):
    """Project a continuous circular stripe onto the original plate UV triangles."""
    obj = root / "visual/model_normalized_0.obj"
    verts, uv, faces = [], [], []
    for line in obj.read_text().splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] == "v":
            verts.append([float(v) for v in fields[1:3]])
        elif fields[0] == "vt":
            uv.append([float(fields[1]), 1-float(fields[2])])
        elif fields[0] == "f":
            faces.append([[int(v)-1 for v in item.split("/")[:2]] for item in fields[1:]])
    width, height = 2048, 1024
    coords = np.asarray(uv) * [width-1,height-1]
    verts = np.asarray(verts)
    pixels = np.zeros((height,width), dtype=np.float32)
    for face in faces:
        for i in range(1,len(face)-1):
            ids = np.asarray([face[0],face[i],face[i+1]])
            pts = coords[ids[:,1]]
            lo = np.maximum(np.floor(pts.min(0)).astype(int)-1, 0)
            hi = np.minimum(np.ceil(pts.max(0)).astype(int)+1,[width-1,height-1])
            if np.any(hi<lo):
                continue
            a,b,c = pts
            m = np.stack([b-a,c-a],axis=1)
            if abs(np.linalg.det(m)) < 1e-8:
                continue
            yy,xx=np.mgrid[lo[1]:hi[1]+1,lo[0]:hi[0]+1]
            bc=(np.stack([xx,yy],axis=-1)-a)@np.linalg.inv(m).T
            bary=np.stack([1-bc.sum(-1),bc[...,0],bc[...,1]],axis=-1)
            inside=np.all(bary>=-.015,axis=-1)
            pos=bary@verts[ids[:,0]]
            radius=np.linalg.norm(pos,axis=-1)
            stripe=np.clip((radius-.429)/.005,0,1)*np.clip((.459-radius)/.005,0,1)
            tile=pixels[lo[1]:hi[1]+1,lo[0]:hi[0]+1]
            np.maximum(tile,stripe*inside,out=tile)
    if np.count_nonzero(pixels) < 100:
        raise RuntimeError("Could not project a rim stripe onto the plate UVs")
    alpha=pixels[...,None]
    rgb=np.rint(np.array([243,234,214])*(1-alpha)+np.array([30,84,61])*alpha)
    return rgb.astype(np.uint8)


def recolor_bagel(root, style):
    src = np.asarray(Image.open(root / "visual/image0.png").convert("RGB"),
                     dtype=np.float32)/255
    if style.startswith("roast"):
        # Ordered baking ladder: preserve original surface luminance, while
        # moving from pale yellow through amber to almost-charred brown.
        recipes = [
            (.35, [1.10, 1.10, .95], [.180, .140, .060]),
            (.48, [1.08, 1.04, .83], [.130, .095, .035]),
            (.62, [1.05, .97, .70], [.090, .060, .018]),
            (.78, [1.02, .88, .60], [.065, .040, .012]),
            (.95, [.98, .78, .50], [.040, .023, .008]),
            (1.15, [.90, .66, .44], [.028, .016, .006]),
            (1.40, [.78, .54, .38], [.018, .010, .004]),
            (1.65, [.63, .42, .31], [.010, .006, .003]),
            (2.00, [.48, .31, .24], [.006, .004, .002]),
            (2.40, [.30, .21, .17], [.003, .002, .001]),
        ]
        level = int(style[5:])
        if not 1 <= level <= len(recipes):
            raise ValueError(f"Unknown roast level: {style}")
        gamma, gain, bias = recipes[level-1]
        # Keep the original warm RGB relationships and surface detail.
        # Increasing gamma and decreasing gain/bias darken every source pixel.
        out = np.power(src, gamma)*gain+bias
    elif style=="light":
        out = np.power(src,0.63)*[1.06,1.08,.91]+[.045,.034,.012]
    elif style=="dark":
        out = np.power(src,1.32)*[.94,.66,.55]+[.025,.014,.01]
    else:
        # Preserve source UV and surface variation; these are color recipes,
        # not additional grains, toppings, geometry or ingredient models.
        recipes = {
            "honey": (.78, [1.10, .98, .73], [.035, .025, .008]),
            "sesame": (.88, [1.08, 1.02, .89], [.040, .035, .020]),
            "rye": (1.16, [.82, .76, .64], [.025, .022, .015]),
            "milk": (.55, [1.02, 1.00, .94], [.075, .065, .045]),
            "cocoa": (1.46, [.72, .51, .44], [.035, .020, .016]),
            "wholegrain": (1.04, [.95, .85, .65], [.030, .022, .010]),
            "caramel": (1.12, [1.08, .69, .43], [.040, .018, .006]),
            "pretzel": (1.38, [1.05, .57, .32], [.030, .012, .004]),
        }
        gamma, gain, bias = recipes[style]
        out = np.power(src, gamma)*gain+bias
    return np.uint8(np.clip(out,0,1)*255)



def bake_texture(root, name):
    if name == "plate_green_rim.png":
        rgb = plate_rim(root)
    elif name.startswith("bagel_") and name.endswith("_generated.png"):
        rgb = recolor_bagel(root, name.split("_")[1])
    else:
        raise ValueError(f"Unknown Meal texture recipe: {name}")
    alpha = np.full((*rgb.shape[:2], 1), 255, dtype=np.uint8)
    return np.concatenate((rgb, alpha), axis=-1)
