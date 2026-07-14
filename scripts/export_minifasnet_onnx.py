"""Convert Silent-Face MiniFASNet .pth checkpoints to ONNX (run once, off-device).

Prerequisites:
  pip install torch
  git clone https://github.com/minivision-ai/Silent-Face-Anti-Spoofing
  # copy its `src/model_lib/MiniFASNet.py` next to this script or add to PYTHONPATH

The two stock checkpoints map to the ensemble in config.yaml:
  2.7_80x80_MiniFASNetV2.pth      -> 2.7_80x80_MiniFASNetV2.onnx
  4_0_0_80x80_MiniFASNetV1SE.pth  -> 4_0_0_80x80_MiniFASNetV1SE.onnx
"""
from __future__ import annotations

import sys
from pathlib import Path

MODELS = Path(__file__).resolve().parent.parent / "models"


def convert(pth_path: str, out_path: str, arch: str = "MiniFASNetV2"):
    import torch
    from MiniFASNet import MiniFASNetV1SE, MiniFASNetV2  # from the Silent-Face repo

    builder = {"MiniFASNetV1SE": MiniFASNetV1SE, "MiniFASNetV2": MiniFASNetV2}[arch]
    model = builder(conv6_kernel=(5, 5)).eval()
    state = torch.load(pth_path, map_location="cpu")
    state = {k.replace("module.", ""): v for k, v in state.items()}
    model.load_state_dict(state, strict=False)

    dummy = torch.randn(1, 3, 80, 80)
    torch.onnx.export(model, dummy, out_path,
                      input_names=["input"], output_names=["logits"],
                      opset_version=11)
    print(f"[done] {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: export_minifasnet_onnx.py <in.pth> <out.onnx> [MiniFASNetV2|MiniFASNetV1SE]")
        raise SystemExit(1)
    convert(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "MiniFASNetV2")
