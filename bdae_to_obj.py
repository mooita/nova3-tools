#!/usr/bin/env python3
import struct, os, sys, re, math

VB_STRIDE = 56

def U32(d, p): return struct.unpack_from('<I', d, p)[0]
def F32(d, p): return struct.unpack_from('<f', d, p)[0]
def cstr(d, p, m=128):
    if not p or p >= len(d): return None
    e = d.find(b'\x00', p, p+m)
    if e < 0: return None
    try: return d[p:e].decode('ascii')
    except: return None

def sanitize(s):
    return re.sub(r'[^A-Za-z0-9_\-]', '_', s) or 'mesh'

def walk_table(d, off, stride=0x30, cap=256):
    i = 0
    while i < cap:
        b = off + i * stride
        if b + 16 > len(d):
            break
        nm, fr, pad, ptr = U32(d, b), U32(d, b+4), U32(d, b+8), U32(d, b+12)
        ok = cstr(d, nm) and pad == 0 and (ptr == 0 or (0 < ptr < len(d) and U32(d, ptr) == 1))
        if not ok:
            break
        i += 1
    return i

def find_mesh_table(d):
    mi = U32(d, 0x20)
    version = cstr(d, U32(d, mi))
    if not version:
        return None, None, None, version
    best = None
    for p in range(mi + 8, mi + 8 + 0x400, 4):
        cnt = U32(d, p)
        off = U32(d, p + 4)
        if cnt < 1 or not (0 < off < len(d)) or off + 0x30 > len(d):
            continue
        n = walk_table(d, off)
        if n >= 1 and (best is None or n > best[0]):
            best = (n, off, p)
    if best is None:
        return None, None, None, version
    return best[0], best[1], version, None

def sample_attr(d, src, nc, off=0, maxv=256, bound=2048.0):
    vb, vc, stride = src
    n = min(vc, maxv)
    good = 0
    for i in range(n):
        b = vb + 4 + i * stride + off
        for j in range(nc):
            if b + (j + 1) * 4 > len(d):
                return -1.0
            x = F32(d, b + j * 4)
            if math.isfinite(x) and abs(x) <= bound:
                good += 1
    return 0.0 if good == 0 else good / (n * nc)

def detect_layout(d, vb, vc, stride):
    thr = 0.8
    use_nrm = nrm_off = 0
    if stride >= 24 and sample_attr(d, (vb, vc, stride), 3, off=12) >= thr:
        unit = 0
        for i in range(min(vc, 256)):
            b = vb + 4 + i * stride + 12
            x, y, z = F32(d, b), F32(d, b + 4), F32(d, b + 8)
            if all(math.isfinite(v) for v in (x, y, z)):
                if 0.85 <= math.hypot(math.hypot(x, y), z) <= 1.15:
                    unit += 1
        if unit >= 0.7 * min(vc, 256):
            use_nrm, nrm_off = 1, 12
    use_uv = uv_off = 0
    for off in (24, 28):
        if stride >= off + 8 and sample_attr(d, (vb, vc, stride), 2, off=off) >= thr:
            use_uv, uv_off = 1, off
            break
    return use_uv, uv_off, use_nrm, nrm_off

def parse_geometry(d, name, ptr, errf):
    magic = U32(d, ptr)
    vc = U32(d, ptr + 4)
    vb = U32(d, ptr + 0x30)
    ibd = U32(d, ptr + 0x3C)
    stride = U32(d, ptr + 0x58) or VB_STRIDE
    if magic != 1 or vc == 0 or vc > 200000 or stride < 8 or stride > 512:
        errf.append(f'{name}: bad geom magic={magic} vc={vc} stride={stride}')
        return None
    if vb + 4 + vc * stride > len(d) or ibd + 56 > len(d):
        errf.append(f'{name}: geom past EOF vb+stride')
        return None
    verts, uvs, nrm = [], [], []
    uv_off = nrm_off = None
    for i in range(vc):
        b = vb + 4 + i * stride
        verts.append((F32(d, b), F32(d, b + 4), F32(d, b + 8)))
    use_uv, uo, use_nrm, no = detect_layout(d, vb, vc, stride)
    uv_off = uo if use_uv else None
    nrm_off = no if use_nrm else None
    for i in range(vc):
        b = vb + 4 + i * stride
        if uv_off is not None:
            uvs.append((F32(d, b + uv_off), F32(d, b + uv_off + 4)))
        if nrm_off is not None:
            nrm.append((F32(d, b + nrm_off), F32(d, b + nrm_off + 4), F32(d, b + nrm_off + 8)))
    tri = U32(d, ibd + 8)
    ics = U32(d, ibd + 0x28)
    ib_off = U32(d, ibd + 0x2C)
    faces = []
    if tri and ics == tri * 3 and ib_off + 4 + ics * 2 <= len(d):
        inds = struct.unpack_from('<%dH' % ics, d, ib_off + 4)
        faces = [tuple(inds[i:i+3]) for i in range(0, ics, 3)]
    elif tri:
        errf.append(f'{name}: IB mismatch tri={tri} ics={ics}')
    return {'name': name, 'verts': verts, 'uvs': uvs, 'nrm': nrm, 'faces': faces,
            'tri': tri, 'maxidx': U32(d, ibd + 0x24)}

def extract(path, outdir='extracted_models'):
    d = open(path, 'rb').read()
    if d[:4] != b'BRES':
        return f'{path}: not BDAE'
    cnt, off, version, err = find_mesh_table(d)
    if cnt is None:
        return f'{path}: no mesh table found ({version})'
    meshes, errf = [], []
    for e in range(cnt):
        b = off + e * 0x30
        for k in range(3):
            nm = U32(d, b); fr = U32(d, b + 4); pad = U32(d, b + 8); ptr = U32(d, b + 12)
            if 0 < ptr < len(d):
                g = parse_geometry(d, cstr(d, fr) or cstr(d, nm) or 'mesh_%d_%d' % (e, k), ptr, errf)
                if g:
                    meshes.append(g)
            b += 16
    if not meshes:
        return f'{path}: 0 meshes parsed'
    base = os.path.splitext(os.path.basename(path))[0]
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, base + '.obj')
    nf = 0
    with open(out, 'w') as f:
        f.write(f'# NOVA3 BDAE {version} conversion of {os.path.basename(path)}\n')
        voff = voffuv = voffn = 0
        for g in meshes:
            f.write('o %s\n' % sanitize(g['name']))
            for p in g['verts']:
                f.write('v %.6f %.6f %.6f\n' % p)
            has_uv = bool(g['uvs']); has_nrm = bool(g['nrm'])
            if has_uv:
                for uv in g['uvs']:
                    f.write('vt %.6f %.6f\n' % uv)
            if has_nrm:
                for v in g['nrm']:
                    f.write('vn %.6f %.6f %.6f\n' % v)
            f.write('usemtl mat\n')
            for a, b, c in g['faces']:
                if max(a, b, c) >= len(g['verts']):
                    continue
                a, b, c = a + 1, b + 1, c + 1
                if has_uv and has_nrm:
                    f.write('f %d/%d/%d %d/%d/%d %d/%d/%d\n' % (voff+a, voffuv+a, voffn+a, voff+b, voffuv+b, voffn+b, voff+c, voffuv+c, voffn+c))
                elif has_uv:
                    f.write('f %d/%d %d/%d %d/%d\n' % (voff+a, voffuv+a, voff+b, voffuv+b, voff+c, voffuv+c))
                elif has_nrm:
                    f.write('f %d//%d %d//%d %d//%d\n' % (voff+a, voffn+a, voff+b, voffn+b, voff+c, voffn+c))
                else:
                    f.write('f %d %d %d\n' % (voff+a, voff+b, voff+c))
                nf += 1
            voff += len(g['verts']); voffuv += len(g['uvs']); voffn += len(g['nrm'])
    names = ', '.join(g['name'] for g in meshes[:6])
    more = ' +%d more' % (len(meshes) - 6) if len(meshes) > 6 else ''
    nv = sum(len(g['verts']) for g in meshes)
    return f'{path}\n  -> {out} ({len(meshes)} meshes, {nv} vertices, {nf} tris): {names}{more}' + (f'\n  WARN: {errf[:3]}' if errf else '')

if __name__ == '__main__':
    import glob
    files = sys.argv[1:]
    if not files:
        files = glob.glob('extracted_patch_full/*.bdae')
    for fp in files:
        try:
            print(extract(fp))
        except Exception as ex:
            print(f'{fp}: ERROR {ex}')