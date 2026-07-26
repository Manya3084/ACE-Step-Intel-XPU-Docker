#!/usr/bin/env python3
"""XPU-safe DCW: run DWT/IDWT on CPU (fp32), cast results back to XPU.

pytorch_wavelets filter banks on Intel Arc / XPU are unreliable (quality
and possible kernel gaps). Mirror the APG FP64 approach: wavelet math on
CPU, DiT stays on XPU.
"""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = "[XPU-DCW-CPU]"

OLD_DWT_PAIR = '''def _dwt_pair(x: torch.Tensor, y: torch.Tensor, wavelet: str):
    """Run DWT on both latents.

    Returns ``(xl, xh, yl, yh, iwt, out_T)`` or ``None`` if the optional
    ``pytorch_wavelets`` dependency is missing.

    ``out_T`` is the original time length of ``x`` — we slice the IDWT
    output back to this length because ``pytorch_wavelets`` pads odd-T
    inputs up to the next even value before running the filter bank.
    """
    modules = WAVELET_CACHE.get(x.device, x.dtype, wavelet)
    if modules is None:
        return None
    dwt, iwt = modules
    x_bct = _btc_to_bct(x.to(torch.float32))
    y_bct = _btc_to_bct(y.to(torch.float32))
    xl, xh = dwt(x_bct)
    yl, yh = dwt(y_bct)
    return xl, xh, yl, yh, iwt, x.shape[1]
'''

NEW_DWT_PAIR = '''def _dwt_pair(x: torch.Tensor, y: torch.Tensor, wavelet: str):
    """Run DWT on both latents.

    Returns ``(xl, xh, yl, yh, iwt, out_T)`` or ``None`` if the optional
    ``pytorch_wavelets`` dependency is missing.

    ``out_T`` is the original time length of ``x`` — we slice the IDWT
    output back to this length because ``pytorch_wavelets`` pads odd-T
    inputs up to the next even value before running the filter bank.

    [XPU-DCW-CPU] On xpu/mps, build filter banks and run DWT/IDWT on CPU
    in fp32, then callers cast the reconstructed latent back to x.device.
    """
    # Prefer CPU wavelet path on Arc / MPS (numerics + kernel coverage)
    if x.device.type in ("xpu", "mps"):
        run_device = torch.device("cpu")
    else:
        run_device = x.device
    modules = WAVELET_CACHE.get(run_device, torch.float32, wavelet)
    if modules is None:
        return None
    dwt, iwt = modules
    x_bct = _btc_to_bct(x.to(device=run_device, dtype=torch.float32))
    y_bct = _btc_to_bct(y.to(device=run_device, dtype=torch.float32))
    xl, xh = dwt(x_bct)
    yl, yh = dwt(y_bct)
    return xl, xh, yl, yh, iwt, x.shape[1]
'''


def patch_primitives(path: Path) -> bool:
    text = path.read_text()
    if MARKER in text and 'x.device.type in ("xpu", "mps")' in text:
        print(f"Already patched primitives: {path}")
        return False

    changed = False
    if OLD_DWT_PAIR in text:
        text = text.replace(OLD_DWT_PAIR, NEW_DWT_PAIR, 1)
        changed = True
        print(f"OK _dwt_pair CPU path in {path}")
    else:
        if "WAVELET_CACHE.get(x.device, x.dtype, wavelet)" in text:
            text = text.replace(
                "WAVELET_CACHE.get(x.device, x.dtype, wavelet)",
                (
                    "WAVELET_CACHE.get(\n"
                    "        torch.device(\"cpu\") if x.device.type in (\"xpu\", \"mps\") "
                    "else x.device,\n"
                    "        torch.float32,\n"
                    "        wavelet,\n"
                    "    )  # " + MARKER
                ),
                1,
            )
            changed = True
            print(f"OK loose WAVELET_CACHE.get CPU for xpu in {path}")
        if "x_bct = _btc_to_bct(x.to(torch.float32))" in text:
            text = text.replace(
                "x_bct = _btc_to_bct(x.to(torch.float32))\n"
                "    y_bct = _btc_to_bct(y.to(torch.float32))",
                (
                    "run_dev = torch.device(\"cpu\") if x.device.type in (\"xpu\", \"mps\") "
                    "else x.device  # " + MARKER + "\n"
                    "    x_bct = _btc_to_bct(x.to(device=run_dev, dtype=torch.float32))\n"
                    "    y_bct = _btc_to_bct(y.to(device=run_dev, dtype=torch.float32))"
                ),
                1,
            )
            changed = True
            print(f"OK tensor move to CPU in {path}")

    old_ret = "return _bct_to_btc(x_new[:, :, :out_T]).to(dtype=x.dtype)"
    new_ret = (
        "return _bct_to_btc(x_new[:, :, :out_T]).to(dtype=x.dtype, device=x.device)  # "
        + MARKER
    )
    if old_ret in text:
        text = text.replace(old_ret, new_ret)
        changed = True
        print(f"OK return to x.device in {path}")

    if not changed:
        print(f"WARN: no primitives changes in {path}", file=sys.stderr)
        return False
    path.write_text(text)
    return True


def patch_loader(path: Path) -> bool:
    text = path.read_text()
    if MARKER in text:
        print(f"Already patched loader: {path}")
        return False

    needle = (
        "        modules = self._try_import()\n"
        "        if modules is None:\n"
        "            return None\n"
        "        DWT1DForward, DWT1DInverse = modules\n"
        "        key = (str(device), str(dtype), wavelet)"
    )
    if needle not in text:
        print(f"WARN: loader insert site not found in {path}", file=sys.stderr)
        return False

    insert = (
        "        modules = self._try_import()\n"
        "        if modules is None:\n"
        "            return None\n"
        "        DWT1DForward, DWT1DInverse = modules\n"
        "        # [XPU-DCW-CPU] Arc/XPU: host the filter banks on CPU\n"
        "        if getattr(device, \"type\", str(device)) in (\"xpu\", \"mps\") "
        "or str(device).startswith(\"xpu\"):\n"
        "            device = torch.device(\"cpu\")\n"
        "            dtype = torch.float32\n"
        "        key = (str(device), str(dtype), wavelet)"
    )
    text = text.replace(needle, insert, 1)
    path.write_text(text)
    print(f"OK loader xpu→cpu in {path}")
    return True


def main() -> None:
    roots = [Path("/app"), Path(".")]
    prims: list[Path] = []
    loaders: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        prims.extend(root.rglob("dcw_primitives.py"))
        loaders.extend(root.rglob("dcw_loader.py"))

    def uniq(paths: list[Path]) -> list[Path]:
        seen: set[str] = set()
        out: list[Path] = []
        for p in paths:
            k = str(p.resolve()) if p.exists() else str(p)
            if k not in seen:
                seen.add(k)
                out.append(p)
        return out

    prims, loaders = uniq(prims), uniq(loaders)
    if not prims and not loaders:
        print("dcw_*.py not found", file=sys.stderr)
        sys.exit(1)

    n = 0
    for p in prims:
        if patch_primitives(p):
            n += 1
    for p in loaders:
        if patch_loader(p):
            n += 1
    print(f"dcw-xpu-cpu-fallback: {n} file(s) updated")


if __name__ == "__main__":
    main()
