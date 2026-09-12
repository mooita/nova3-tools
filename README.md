# Nova3 Tools

Conversion and extraction tools for the game **NOVA3** (N.O.V.A. Near Orbit Vanguard Alliance 3), Android.

## Scripts

| Script | Description |
| ------ | ----------- |
| `bdae_to_obj.py` | Converts `*.bdae` mesh files (`BRES` format) to `.obj`. |
| `extract_obb.py` | Extracts the game's OBB file (expanded ZIP container). |

---

## bdae_to_obj.py

Converts the game's mesh files (extension `.bdae`, magic header `BRES`) to `.obj`, readable by any 3D viewer (Blender, MeshLab...).

### Usage

```sh
python3 bdae_to_obj.py [files.bdae ...]
```

- Without arguments, it processes every `*.bdae` found in `extracted_patch_full/`.
- With arguments, it processes the given files (multiple paths and globs are accepted).

### Output

The output folder `extracted_models/` is created automatically if it does not exist. Each converted file is written there as `<name>.obj`.

The `.obj` contains:

- `o <mesh>`
- `v` position vertices
- `vt` texture coordinates (when detected)
- `vn` normals (when detected)
- `f` triangle faces with the matching vertex/texture/normal indices
- Default material `usemtl mat`

### How it works

1. **`find_mesh_table`** locates the mesh table by scanning candidate offsets in the file.
2. **`walk_table`** validates table entries (ASCII strings, padding, pointers).
3. **`detect_layout`** auto-detects the vertex buffer layout:
   - Normals: at offset 12 if the values have unit length (~1.0).
   - UVs: at offset 24 or 28 if the sampling ratio is above the threshold.
   - The default vertex stride is **56 bytes**.
4. **`parse_geometry`** reads vertices, UVs, normals and indices of each sub-mesh.
5. The `main` block prints a per-file summary (mesh/vertex/face counts) plus any `WARN` messages.

### Common warnings

- `bad geom magic` → the pointer does not point to valid geometry.
- `geom past EOF` → buffer exceeds the file bounds.
- `IB mismatch` → index count does not match triple the triangle count.

---

## extract_obb.py

Extracts the contents of the game's OBB file (`*.obb`). The OBB is an expanded ZIP archive, so the script scans the binary for local file headers `PK\x03\x04` and writes each entry to disk.

### Usage

```sh
python3 extract_obb.py <file.obb> <output_dir>
```

### Output

- Files are written under `<output_dir>/`, keeping the internal path structure.
- A log file at `<output_dir>_log.txt` details every entry (`[OK]`, `[FAIL deflate]`, `[SKIP ...]`).

### Behavior

- **Method 0 (stored):** dumps the chunk as-is.
- **Method 8 (deflate):** decompresses it with `zlib`.
- **Other methods:** skipped and recorded in the log.
- **Streaming (`flag & 0x8`):** if `comp_size == 0`, the size is estimated by locating the next local/central header.
- **Empty or unsafe names:** skipped, and paths are sanitized (`\` → `/`, no `.`/`..`).
- Names that cannot be decoded as UTF-8 are reinterpreted as *latin-1*.

Finally, it prints a summary: local headers found, successfully extracted files, failed ones, and the log path.