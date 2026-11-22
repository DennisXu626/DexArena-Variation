"""Exact integer SAT for complete UV triangles and closed bilinear support.

Input UV values are actual float32 values represented as exact binary rationals.
No UV or texture is changed. Boundary contact is unsafe. Rectangles are protected
texel runs with the real W/H sampler support, rather than W-1/H-1 raster coverage.
"""
import hashlib
import math


def integer_scale(uv_values,width,height):
    denominator=max(float(value).as_integer_ratio()[1] for pair in uv_values for value in pair)
    return math.lcm(denominator,2*width,2*height)


def scaled_triangle(values,scale):
    return [[numerator*(scale//denominator) for numerator,denominator in
             (float(value).as_integer_ratio() for value in point)] for point in values]


def protected_rectangles(image,guard,scale):
    from PIL import ImageFilter
    width,height=image.size
    protected=image.filter(ImageFilter.MaxFilter(guard*2+1)) if guard else image
    data=protected.tobytes();active={};result=[]
    for y in range(height+1):
        runs=set()
        if y<height:
            row=data[y*width:(y+1)*width];offset=0
            while True:
                start=row.find(b'\xff',offset)
                if start<0:break
                end=row.find(b'\x00',start)
                if end<0:end=width
                runs.add((start,end));offset=end
        for key,first in list(active.items()):
            if key not in runs:
                start,end=key
                result.append({'pixel_run_x':[start,end],'pixel_rows_y':[first,y],
                    'scaled_closed_rect':[(2*start-1)*(scale//(2*width)),(2*first-1)*(scale//(2*height)),
                        (2*end+1)*(scale//(2*width)),(2*y+1)*(scale//(2*height))]})
                del active[key]
        for run in sorted(runs):
            if run not in active:active[run]=y
    result.sort(key=lambda row:(row['pixel_rows_y'],row['pixel_run_x']))
    if not result:raise ValueError('Office protection mask is empty')
    return result,hashlib.sha256(data).hexdigest()


def intersects(triangle,rectangle):
    x0,y0,x1,y1=rectangle
    if (max(x for x,y in triangle)<x0 or min(x for x,y in triangle)>x1
            or max(y for x,y in triangle)<y0 or min(y for x,y in triangle)>y1):return False
    for i in range(3):
        p,q=triangle[i],triangle[(i+1)%3];nx,ny=-(q[1]-p[1]),q[0]-p[0]
        if nx==ny==0:continue
        projected=[x*nx+y*ny for x,y in triangle]
        low=(x0 if nx>=0 else x1)*nx+(y0 if ny>=0 else y1)*ny
        high=(x1 if nx>=0 else x0)*nx+(y1 if ny>=0 else y0)*ny
        if high<min(projected) or low>max(projected):return False
    return True


def periodic_witness(triangle,protected,scale):
    rects=[row['scaled_closed_rect'] for row in protected]
    tlo=[min(p[k] for p in triangle) for k in (0,1)];thi=[max(p[k] for p in triangle) for k in (0,1)]
    rlo=[min(r[k] for r in rects) for k in (0,1)];rhi=[max(r[k] for r in rects) for k in (2,3)]
    lower=[-((-(tlo[k]-rhi[k]))//scale) for k in (0,1)]
    upper=[(thi[k]-rlo[k])//scale for k in (0,1)]
    for iy in range(lower[1],upper[1]+1):
        for ix in range(lower[0],upper[0]+1):
            for index,base in enumerate(rects):
                rectangle=[base[0]+ix*scale,base[1]+iy*scale,base[2]+ix*scale,base[3]+iy*scale]
                if intersects(triangle,rectangle):
                    return {'integer_tile':[ix,iy],'protected_rectangle_index':index,'scaled_closed_rect':rectangle}
    return None
