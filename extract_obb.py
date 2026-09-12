#!/usr/bin/env python3
"""Extract files from a NOVA3 .obb archive (an expanded ZIP container)."""
import sys
import os
import struct
import zlib

LOCAL_SIG = b"PK\x03\x04"


def sanitize_name(name: str) -> str:
    name = name.replace("\\", "/")
    parts = [p for p in name.split("/") if p not in ("", ".", "..")]
    return "/".join(parts)


def extract(obb_path: str, out_dir: str, log_path: str):
    with open(obb_path, "rb") as f:
        data = f.read()

    total_len = len(data)
    os.makedirs(out_dir, exist_ok=True)

    entries = []
    pos = 0
    found = 0
    ok = 0
    failed = 0
    skipped_empty_name = 0

    log = open(log_path, "w", encoding="utf-8")

    while True:
        idx = data.find(LOCAL_SIG, pos)
        if idx == -1:
            break
        found += 1

        try:
            header = data[idx:idx + 30]
            if len(header) < 30:
                pos = idx + 4
                continue

            (sig, ver, flag, method, modtime, moddate, crc32,
             comp_size, uncomp_size, name_len, extra_len) = struct.unpack(
                "<IHHHHHIIIHH", header
            )

            name_start = idx + 30
            name_end = name_start + name_len
            extra_end = name_end + extra_len
            raw_name = data[name_start:name_end]
            try:
                name = raw_name.decode("utf-8")
            except UnicodeDecodeError:
                name = raw_name.decode("latin-1")

            data_start = extra_end

            streaming = bool(flag & 0x8)

            if streaming and comp_size == 0:
                next_local = data.find(LOCAL_SIG, data_start)
                next_central = data.find(b"PK\x01\x02", data_start)
                candidates = [x for x in (next_local, next_central) if x != -1]
                data_end = min(candidates) if candidates else total_len
                comp_size_guess = data_end - data_start
            else:
                data_end = data_start + comp_size
                comp_size_guess = comp_size

            entry_info = {
                "offset": idx,
                "name": name,
                "method": method,
                "comp_size": comp_size_guess,
                "uncomp_size": uncomp_size,
                "streaming": streaming,
            }

            if not name:
                skipped_empty_name += 1
                log.write(f"[SKIP empty name] offset={idx}\n")
                pos = idx + 4
                continue

            raw_chunk = data[data_start:data_end]

            out_bytes = None
            if method == 0:
                out_bytes = raw_chunk
            elif method == 8:
                try:
                    out_bytes = zlib.decompress(raw_chunk, -15)
                except Exception as e:
                    out_bytes = None
                    log.write(f"[FAIL deflate] {name} offset={idx} err={e}\n")
            else:
                log.write(f"[SKIP unsupported method {method}] {name} offset={idx}\n")

            if out_bytes is not None:
                safe_name = sanitize_name(name)
                if safe_name:
                    out_path = os.path.join(out_dir, safe_name)
                    os.makedirs(os.path.dirname(out_path) or out_dir, exist_ok=True)
                    if not safe_name.endswith("/"):
                        with open(out_path, "wb") as out_f:
                            out_f.write(out_bytes)
                        ok += 1
                        log.write(f"[OK] {name} ({len(out_bytes)} bytes) offset={idx}\n")
            else:
                failed += 1

            entries.append(entry_info)

            if comp_size_guess > 0:
                pos = data_end
            else:
                pos = idx + 4

        except Exception as e:
            log.write(f"[ERROR parseando header] offset={idx} err={e}\n")
            pos = idx + 4

    log.write(f"\nSummary: found={found} extracted_ok={ok} failed={failed} empty_name={skipped_empty_name}\n")
    log.close()

    return entries, found, ok, failed


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 extract_obb.py <file.obb> <output_dir>")
        sys.exit(1)

    obb_path = sys.argv[1]
    out_dir = sys.argv[2]
    log_path = out_dir.rstrip("/") + "_log.txt"

    entries, found, ok, failed = extract(obb_path, out_dir, log_path)

    print(f"Local headers found:     {found}")
    print(f"Extracted successfully:  {ok}")
    print(f"Failed/unsupported:      {failed}")
    print(f"Full log at:             {log_path}")
    print(f"Files in:                {out_dir}")
