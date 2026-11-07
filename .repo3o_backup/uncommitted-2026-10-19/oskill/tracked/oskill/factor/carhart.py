"""Carhart 4-factor model (Fama-French 3 + momentum)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from oskill.factor.fama_french import fama_french_5_factor_model

_CARHART_FACTORS = ["MKT", "SMB", "HML", "MOM"]


def carhart_4_factor_model(
    asset_returns: np.ndarray | pd.Series,
    factor_returns: pd.DataFrame,
    *,
    risk_free_rate: float = 0.0,
) -> dict[str, Any]:
    """Carhart 4-factor model (FF3 + MOM/UMD).

    R_i - Rf = alpha + beta_MKT*MKT + beta_SMB*SMB + beta_HML*HML + beta_MOM*MOM + e

    Extends the Fama-French 3-factor model with a momentum factor (MOM or UMD),
    capturing the tendency of past winners to continue outperforming.

    Required columns in factor_returns: ['MKT', 'SMB', 'HML', 'MOM']

    Args:
        asset_returns: Asset return series (length T).
        factor_returns: DataFrame with columns ['MKT', 'SMB', 'HML', 'MOM'] (T x 4).
        risk_free_rate: Risk-free rate to subtract from asset_returns (default 0).

    Returns dict (same structure as fama_french_5_factor_model):
        - 'alpha': float
        - 'betas': dict {factor: beta}
        - 'beta_t_stats': dict {factor: t_stat}
        - 'alpha_t_stat': float
        - 'r_squared': float
        - 'adjusted_r_squared': float
        - 'residual_std': float
        - 'n_obs': int
    """
    return fama_french_5_factor_model(
        asset_returns,
        factor_returns,
        factors=_CARHART_FACTORS,
        risk_free_rate=risk_free_rate,
    )
