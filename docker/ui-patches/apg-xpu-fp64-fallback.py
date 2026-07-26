#!/usr/bin/env python3
"""XPU-safe APG project(): avoid FP64 normalize on Intel Arc.

Upstream apg_guidance.project() does:
  if device_type == "mps": v0, v1 = v0.cpu(), v1.cpu()
  v0, v1 = v0.double(), v1.double()
  F.normalize(...)

Arc A770 has no native FP64 → RuntimeError:
  Kernel is incompatible with all devices in devs

Base / XL-base always call apg_forward (not only the UI "Use ADG" toggle).
Mirror the MPS path for XPU: run the projection on CPU, then cast back.
"""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = "[XPU-APG-FP64]"

OLD = '''def project(
    v0: torch.Tensor,  # [B, C, T]
    v1: torch.Tensor,  # [B, C, T]
    dims=[-1],
):
    dtype = v0.dtype
    device_type = v0.device.type
    if device_type == "mps":
        v0, v1 = v0.cpu(), v1.cpu()

    v0, v1 = v0.double(), v1.double()
    v1 = torch.nn.functional.normalize(v1, dim=dims)
    v0_parallel = (v0 * v1).sum(dim=dims, keepdim=True) * v1
    v0_orthogonal = v0 - v0_parallel
    return v0_parallel.to(dtype).to(device_type), v0_orthogonal.to(dtype).to(device_type)
'''

NEW = '''def project(
    v0: torch.Tensor,  # [B, C, T]
    v1: torch.Tensor,  # [B, C, T]
    dims=[-1],
):
    # [XPU-APG-FP64] Arc/XPU has no native FP64; MPS already CPU-fell-back.
    # Run double-precision project on CPU for mps + xpu, then cast back.
    dtype = v0.dtype
    device_type = v0.device.type
    origin_device = v0.device
    if device_type in ("mps", "xpu"):
        v0, v1 = v0.cpu(), v1.cpu()

    v0, v1 = v0.double(), v1.double()
    v1 = torch.nn.functional.normalize(v1, dim=dims)
    v0_parallel = (v0 * v1).sum(dim=dims, keepdim=True) * v1
    v0_orthogonal = v0 - v0_parallel
    if device_type in ("mps", "xpu"):
        return (
            v0_parallel.to(dtype=dtype, device=origin_device),
            v0_orthogonal.to(dtype=dtype, device=origin_device),
        )
    return v0_parallel.to(dtype).to(device_type), v0_orthogonal.to(dtype).to(device_type)
'''


def patch_file(path: Path) -> bool:
    text = path.read_text()
    if MARKER in text and 'device_type in ("mps", "xpu")' in text:
        print(f"Already patched: {path}")
        return False
    if OLD in text:
        text = text.replace(OLD, NEW, 1)
        path.write_text(text)
        print(f"OK patched project() in {path}")
        return True
    if 'if device_type == "mps":' in text and "v0.double()" in text:
        text2 = text.replace(
            'if device_type == "mps":\n        v0, v1 = v0.cpu(), v1.cpu()',
            'if device_type in ("mps", "xpu"):  # [XPU-APG-FP64]\n'
            "        v0, v1 = v0.cpu(), v1.cpu()",
            1,
        )
        if text2 != text:
            path.write_text(text2)
            print(f"OK extended mps→xpu CPU fallback in {path}")
            return True
    print(f"WARN: project() pattern not found in {path}", file=sys.stderr)
    return False


def main() -> None:
    paths = list(Path("/app").rglob("apg_guidance.py"))
    if not paths:
        paths = list(Path(".").rglob("apg_guidance.py"))
    if not paths:
        print("apg_guidance.py not found", file=sys.stderr)
        sys.exit(1)

    n = 0
    for p in paths:
        if patch_file(p):
            n += 1
    print(f"apg-xpu-fp64-fallback: {n} file(s)")


if __name__ == "__main__":
    main()
