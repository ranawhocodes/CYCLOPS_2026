"""
Grad-CAM over the IR branch, targeting the intensity output.

A nuance worth stating in the demo: for a REGRESSION output, Grad-CAM shows
which regions *increase the predicted wind speed*. That is a subtly different
question from the usual classification CAM, which shows what supports a class.
Being precise about it separates understanding the method from importing it.

Hand-rolled here rather than pulled from pytorch-grad-cam so the API image needs
no extra dependency, but the implementation is the standard one: channel weights
are the spatially-averaged gradients of the target scalar with respect to the
last convolutional feature map, applied to that map and passed through ReLU.
"""
from __future__ import annotations

import io

import numpy as np
import torch


class IntensityCAM:
    def __init__(self, model, device: str = "cpu"):
        self.model = model.eval().to(device)
        self.device = device
        self._acts = None
        self._grads = None
        target = model.ir.cam_target_layer
        target.register_forward_hook(self._fwd)
        target.register_full_backward_hook(self._bwd)

    def _fwd(self, _m, _i, out):
        self._acts = out

    def _bwd(self, _m, _gi, gout):
        self._grads = gout[0]

    def __call__(self, ir, wind, wind_present, env) -> np.ndarray:
        """Returns an (H, W) heatmap in [0, 1] at the input resolution."""
        ir = ir.clone().requires_grad_(True)
        self.model.zero_grad(set_to_none=True)
        out = self.model(ir, wind, wind_present, env)
        out["wind_kt"].sum().backward()

        acts, grads = self._acts, self._grads
        weights = grads.mean(dim=(2, 3), keepdim=True)
        cam = torch.relu((weights * acts).sum(dim=1, keepdim=True))
        cam = torch.nn.functional.interpolate(
            cam, size=ir.shape[-2:], mode="bilinear", align_corners=False)
        cam = cam[0, 0].detach().cpu().numpy()
        rng = cam.max() - cam.min()
        return (cam - cam.min()) / rng if rng > 1e-8 else np.zeros_like(cam)


def overlay_png(ir_norm: np.ndarray, heat: np.ndarray, alpha: float = 0.55) -> bytes:
    """Greyscale IR base with the CAM in a perceptually-uniform colormap."""
    from matplotlib import cm
    from PIL import Image

    base = (np.stack([np.clip(ir_norm, 0, 1)] * 3, -1) * 255).astype(np.uint8)
    hm = (cm.inferno(np.clip(heat, 0, 1))[..., :3] * 255).astype(np.uint8)
    blend = (base * (1 - alpha) + hm * alpha).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(blend).save(buf, "PNG", optimize=True)
    return buf.getvalue()


def frame_png(ir_norm: np.ndarray, colormap: str = "bone") -> bytes:
    """Render a normalised IR channel as a standalone PNG for the console."""
    import matplotlib as mpl
    from PIL import Image

    # matplotlib.cm.get_cmap was removed in 3.9; matplotlib.colormaps is the
    # supported accessor.
    cmap = mpl.colormaps[colormap]
    img = (cmap(np.clip(ir_norm, 0, 1))[..., :3] * 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, "PNG", optimize=True)
    return buf.getvalue()


# What a correct CAM looks like at each stage. Used in the console caption and
# in the written case-study analysis.
EXPECTED_CAM_FOCUS = {
    "D":    "diffuse, over the main convective blob",
    "DD":   "diffuse to weakly banded",
    "CS":   "along the curved band, following its curvature",
    "SCS":  "tightening band, centre becoming defined",
    "VSCS": "ring forming around the developing eyewall",
    "ESCS": "tight annulus on the eyewall, NOT the warm eye centre",
    "SuCS": "tight annulus on the eyewall, NOT the warm eye centre",
}
