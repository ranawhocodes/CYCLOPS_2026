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
    """Render a normalised IR channel as an opaque PNG (panel view)."""
    import matplotlib as mpl
    from PIL import Image

    # matplotlib.cm.get_cmap was removed in 3.9; matplotlib.colormaps is the
    # supported accessor.
    cmap = mpl.colormaps[colormap]
    img = (cmap(np.clip(ir_norm, 0, 1))[..., :3] * 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, "PNG", optimize=True)
    return buf.getvalue()


def frame_png_georef(ir_norm: np.ndarray, clear_c: float = -15.0,
                     opaque_c: float = -55.0) -> bytes:
    """
    Render the IR channel for draping on the map, with an alpha channel.

    Clear air is transparent so the coastline and track read through; cloud
    becomes opaque as it cools. The thresholds are stated in DEGREES CELSIUS
    rather than normalised units because that is the quantity that means
    something: nothing warmer than `clear_c` is drawn, and anything colder than
    `opaque_c` is fully opaque.

    The previous ramp was written in normalised units and was far too weak —
    -78 C deep convection reached only 0.70 alpha and -33 C mid cloud sat at
    0.33, so the storm rendered as a faint grey smudge. Working in Celsius makes
    that mistake visible instead of hiding it behind a magic 0.30.

    Colour follows the Dvorak BD enhancement: ordinary cloud greyscale, then the
    enhancement colours for the coldest tops. That is the same colour language
    the rest of the console uses, and it is what makes the eyewall legible.
    """
    from PIL import Image

    x = np.clip(np.asarray(ir_norm, dtype=np.float32), 0.0, 1.0)
    # normalise_bt maps cold high: x = 1 - (BT - BT_MIN) / (BT_MAX - BT_MIN)
    from ..config import BT_MAX, BT_MIN
    from ..domain.imd import KELVIN
    bt_c = (BT_MAX - x * (BT_MAX - BT_MIN)) - KELVIN

    alpha = np.clip((clear_c - bt_c) / max(1e-6, clear_c - opaque_c), 0.0, 1.0) ** 0.75

    # BD ramp, warm -> cold. Greys through white for ordinary convection, then
    # the enhancement colours where Dvorak analysis actually keys.
    stops_c = np.array([0.0, -20.0, -35.0, -50.0, -62.0, -70.0, -76.0, -82.0, -92.0])
    stops_rgb = np.array([
        (0.30, 0.42, 0.52),   #   0 C  thin low cloud
        (0.58, 0.70, 0.78),   # -20
        (0.82, 0.88, 0.92),   # -35
        (0.97, 0.98, 1.00),   # -50  bright white
        (0.36, 0.82, 0.44),   # -62  BD green
        (0.95, 0.78, 0.24),   # -70  BD amber
        (0.95, 0.50, 0.24),   # -76  BD orange
        (0.91, 0.25, 0.29),   # -82  BD red
        (0.66, 0.13, 0.47),   # -92  BD violet, overshooting tops
    ])
    rgb = np.empty((*x.shape, 3), np.float32)
    for ch in range(3):
        rgb[..., ch] = np.interp(bt_c, stops_c[::-1], stops_rgb[::-1, ch])

    rgba = np.concatenate([rgb, alpha[..., None].astype(np.float32)], axis=-1)
    img = (np.clip(rgba, 0, 1) * 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(img, mode="RGBA").save(buf, "PNG", optimize=True)
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
