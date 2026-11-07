"""oskill.hmm_regime_detect — Detect market regimes via Gaussian HMM.

Composites:
    - oprim.hmm_baum_welch  (Baum-Welch EM fit)
    - oprim.hmm_viterbi     (Viterbi decoding)
"""

from __future__ import annotations

from typing import Any


def hmm_regime_detect(
    features: Any,
    *,
    n_regimes: int,
    trained_model: dict[str, Any] | None = None,
    max_iter: int = 100,
    random_state: int | None = 42,
) -> dict[str, Any]:
    """Detect hidden market regimes in *features* using a Gaussian HMM.

    If *trained_model* is provided the Baum-Welch fit is skipped and only
    Viterbi decoding is performed.  This allows applying a model trained on
    historical data to new observations without re-fitting.

    Composites used:
        1. oprim.hmm_baum_welch — fits the emission and transition parameters.
        2. oprim.hmm_viterbi   — decodes the most-likely state sequence.

    Args:
        features: 1-D or 2-D array-like of shape (T,) or (T, D).
        n_regimes: Number of hidden regimes.
        trained_model: Pre-fitted model dict (output of hmm_baum_welch).
            When None the model is fitted from *features*.
        max_iter: EM iteration cap (used only when fitting).
        random_state: Seed for reproducibility (used only when fitting).

    Returns:
        Dict with keys:

        - ``regimes`` – List of integer regime labels, length T.
        - ``model``   – Fitted model dict (pass back as *trained_model*).
        - ``n_regimes`` – Number of regimes.
        - ``current_regime`` – Regime label of the last observation.
        - ``transition_matrix`` – n_regimes × n_regimes transition matrix.
    """
    from oprim.hmm_baum_welch import hmm_baum_welch  # noqa: PLC0415
    from oprim.hmm_viterbi import hmm_viterbi  # noqa: PLC0415

    if trained_model is None:
        model = hmm_baum_welch(
            features,
            n_states=n_regimes,
            max_iter=max_iter,
            random_state=random_state,
        )
    else:
        model = trained_model

    regimes = hmm_viterbi(features, model=model)

    return {
        "regimes": regimes,
        "model": model,
        "n_regimes": n_regimes,
        "current_regime": regimes[-1] if regimes else None,
        "transition_matrix": model.get("transmat", []),
    }
