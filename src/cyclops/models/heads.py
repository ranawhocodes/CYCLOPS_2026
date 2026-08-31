"""Output heads and losses."""
from __future__ import annotations

import torch
import torch.nn as nn


class IntensityHead(nn.Module):
    """Predicts 3-minute sustained wind in knots. Regression, not classification."""

    def __init__(self, in_dim: int = 256):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, 128), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(128, 1),
        )

    def forward(self, z):
        return self.net(z).squeeze(-1)


def huber_weighted(pred, target, delta: float = 10.0):
    """
    Huber loss with an intensity-proportional weight.

    Huber rather than L2 because best-track intensity carries genuine outliers
    and a squared loss lets one bad label dominate a batch.

    delta = 10 kt is chosen physically, not by search: it is roughly the
    inter-analyst disagreement in Dvorak estimation, so residuals smaller than
    that sit inside the noise floor of the label itself and should not be
    penalised quadratically. Being able to justify a hyperparameter from the
    domain is worth saying out loud in Q&A.

    The weight upsamples rare intense storms without the pathologies that
    classification-style resampling introduces.
    """
    w = 1.0 + (target / 60.0).clamp(0.0, 2.0)
    err = pred - target
    a = err.abs()
    loss = torch.where(a < delta, 0.5 * err ** 2, delta * (a - 0.5 * delta))
    return (loss * w).mean()
