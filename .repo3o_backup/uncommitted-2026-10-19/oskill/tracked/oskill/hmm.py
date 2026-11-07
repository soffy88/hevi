"""Hidden Markov Model workflows."""

from __future__ import annotations

import numpy as np


def gaussian_hmm(
    x: np.ndarray,
    n_states: int = 2,
    n_iter: int = 100,
    tol: float = 1e-4,
    random_state: int | None = None,
) -> dict:
    """Fit Gaussian HMM via Baum-Welch EM algorithm.

    Parameters
    ----------
    x : np.ndarray
        1-D observation sequence.
    n_states : int
        Number of hidden states.
    n_iter : int
        Maximum EM iterations.
    tol : float
        Convergence tolerance on log-likelihood.
    random_state : int, optional
        RNG seed.

    Returns
    -------
    dict
        "means": state means, "stds": state stds,
        "transition_matrix": (n_states, n_states),
        "state_probs": posterior state probabilities (T, n_states),
        "viterbi_path": most likely state sequence,
        "log_likelihood": final log-likelihood,
        "converged": bool.

    References
    ----------
    .. [1] Baum, L.E. et al. (1970). A maximization technique in statistical analysis of probabilistic functions of Markov chains.
    .. [2] Extraction source: Selene project, sel_v2/observation_tools/bayesian_hmm.py:_GaussianHMM
    """
    np.random.default_rng(random_state)
    x = np.asarray(x, dtype=float).ravel()
    T = len(x)

    # Initialize
    means = np.linspace(x.min(), x.max(), n_states)
    stds = np.full(n_states, x.std() / n_states)
    A = np.full((n_states, n_states), 1.0 / n_states)  # transition
    pi = np.full(n_states, 1.0 / n_states)  # initial

    prev_ll = -np.inf
    converged = False

    for iteration in range(n_iter):
        # E-step: forward-backward
        B = _emission(x, means, stds)
        alpha, scale = _forward(B, A, pi)
        beta = _backward(B, A, scale)
        gamma = alpha * beta
        gamma /= gamma.sum(axis=1, keepdims=True) + 1e-300

        xi = np.zeros((T - 1, n_states, n_states))
        for t in range(T - 1):
            numer = alpha[t, :, None] * A * B[t + 1, None, :] * beta[t + 1, None, :]
            xi[t] = numer / (numer.sum() + 1e-300)

        # Log-likelihood
        ll = float(np.sum(np.log(scale + 1e-300)))
        if abs(ll - prev_ll) < tol:
            converged = True
            break
        prev_ll = ll

        # M-step
        pi = gamma[0] / (gamma[0].sum() + 1e-300)
        A = xi.sum(axis=0) / (gamma[:-1].sum(axis=0)[:, None] + 1e-300)
        for k in range(n_states):
            w = gamma[:, k]
            w_sum = w.sum() + 1e-300
            means[k] = np.dot(w, x) / w_sum
            stds[k] = np.sqrt(np.dot(w, (x - means[k]) ** 2) / w_sum + 1e-10)

    # Viterbi
    viterbi = _viterbi(B, A, pi)

    return {
        "means": means.tolist(),
        "stds": stds.tolist(),
        "transition_matrix": A.tolist(),
        "state_probs": gamma,
        "viterbi_path": viterbi,
        "log_likelihood": float(prev_ll),
        "converged": converged,
    }


def _emission(x: np.ndarray, means: np.ndarray, stds: np.ndarray) -> np.ndarray:
    """Gaussian emission probabilities."""
    T = len(x)
    K = len(means)
    B = np.zeros((T, K))
    for k in range(K):
        B[:, k] = np.exp(-0.5 * ((x - means[k]) / stds[k]) ** 2) / (stds[k] * np.sqrt(2 * np.pi))
    return B + 1e-300


def _forward(B: np.ndarray, A: np.ndarray, pi: np.ndarray):
    """Scaled forward algorithm."""
    T, K = B.shape
    alpha = np.zeros((T, K))
    scale = np.zeros(T)
    alpha[0] = pi * B[0]
    scale[0] = alpha[0].sum()
    alpha[0] /= scale[0] + 1e-300
    for t in range(1, T):
        alpha[t] = (alpha[t - 1] @ A) * B[t]
        scale[t] = alpha[t].sum()
        alpha[t] /= scale[t] + 1e-300
    return alpha, scale


def _backward(B: np.ndarray, A: np.ndarray, scale: np.ndarray):
    """Scaled backward algorithm."""
    T, K = B.shape
    beta = np.zeros((T, K))
    beta[-1] = 1.0
    for t in range(T - 2, -1, -1):
        beta[t] = A @ (B[t + 1] * beta[t + 1])
        beta[t] /= scale[t + 1] + 1e-300
    return beta


def _viterbi(B: np.ndarray, A: np.ndarray, pi: np.ndarray) -> np.ndarray:
    """Viterbi decoding."""
    T, K = B.shape
    log_A = np.log(A + 1e-300)
    log_B = np.log(B + 1e-300)
    log_pi = np.log(pi + 1e-300)

    V = np.zeros((T, K))
    ptr = np.zeros((T, K), dtype=int)
    V[0] = log_pi + log_B[0]
    for t in range(1, T):
        for k in range(K):
            trans = V[t - 1] + log_A[:, k]
            ptr[t, k] = int(np.argmax(trans))
            V[t, k] = trans[ptr[t, k]] + log_B[t, k]

    path = np.zeros(T, dtype=int)
    path[-1] = int(np.argmax(V[-1]))
    for t in range(T - 2, -1, -1):
        path[t] = ptr[t + 1, path[t + 1]]
    return path
