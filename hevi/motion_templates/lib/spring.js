/**
 * Hevi Motion Templates - Closed-Form Spring Library
 * 
 * Implements pure closed-form step response springs for stateless, deterministic animations.
 * Formula: Mass-spring-damper second order step response.
 * Multi-target animation is the sum of one step response per target change (LTI superposition).
 * 
 * Works in both browser (<script> / window.Spring) and CommonJS/ES module environments.
 */

(function (root, factory) {
  if (typeof define === 'function' && define.amd) {
    define([], factory);
  } else if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.Spring = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /**
   * Closed-form step response for second-order harmonic oscillator from 0 to 1.
   * @param {number} tau - Elapsed time since step (t - t0)
   * @param {number} omega_n - Natural angular frequency (rad/s), default 14
   * @param {number} zeta - Damping ratio, default 0.82 (underdamped, tiny controlled overshoot)
   * @returns {number} Value from 0 approaching 1 as tau increases.
   */
  function stepResponse(tau, omega_n = 14.0, zeta = 0.82) {
    if (tau <= 0) return 0;

    if (zeta < 0.9999) {
      // Underdamped (oscillates with tiny overshoot when zeta ~ 0.8)
      const omega_d = omega_n * Math.sqrt(1.0 - zeta * zeta);
      const decay = Math.exp(-zeta * omega_n * tau);
      const envelope = Math.cos(omega_d * tau) + (zeta / Math.sqrt(1.0 - zeta * zeta)) * Math.sin(omega_d * tau);
      return 1.0 - decay * envelope;
    } else if (zeta <= 1.0001) {
      // Critically damped (no overshoot)
      return 1.0 - Math.exp(-omega_n * tau) * (1.0 + omega_n * tau);
    } else {
      // Overdamped
      const alpha = zeta * omega_n;
      const beta = omega_n * Math.sqrt(zeta * zeta - 1.0);
      return 1.0 - Math.exp(-alpha * tau) * (Math.cosh(beta * tau) + (alpha / beta) * Math.sinh(beta * tau));
    }
  }

  /**
   * Multi-target spring value at time t.
   * Superposition of step responses for each target change.
   * @param {number} t - Current time in seconds
   * @param {Array<{t: number, val: number, omega?: number, zeta?: number}>} steps - Sorted or unsorted step sequence
   * @param {number} defaultOmega - Default natural frequency
   * @param {number} defaultZeta - Default damping ratio
   * @returns {number} Interpolated value
   */
  function multiTargetSpring(t, steps, defaultOmega = 14.0, defaultZeta = 0.82) {
    if (!steps || steps.length === 0) return 0;
    if (steps.length === 1) return steps[0].val;

    // Defensive copy and sort if needed
    let sorted = steps;
    for (let i = 1; i < steps.length; i++) {
      if (steps[i].t < steps[i - 1].t) {
        sorted = [...steps].sort((a, b) => a.t - b.t);
        break;
      }
    }

    if (t < sorted[0].t) {
      return sorted[0].val;
    }

    let val = sorted[0].val;
    for (let i = 1; i < sorted.length; i++) {
      const step = sorted[i];
      if (t < step.t) {
        break;
      }
      const prevStep = sorted[i - 1];
      const delta = step.val - prevStep.val;
      if (Math.abs(delta) < 1e-9) continue;

      const omega = step.omega !== undefined ? step.omega : defaultOmega;
      const zeta = step.zeta !== undefined ? step.zeta : defaultZeta;
      val += delta * stepResponse(t - step.t, omega, zeta);
    }

    return val;
  }

  /**
   * Parses hex, rgb, rgba into [r, g, b, a].
   */
  function parseColor(c) {
    if (!c) return [255, 255, 255, 1];
    if (Array.isArray(c)) {
      return [c[0], c[1], c[2], c[3] !== undefined ? c[3] : 1];
    }
    const str = String(c).trim();
    if (str.startsWith('#')) {
      let hex = str.slice(1);
      if (hex.length === 3) {
        hex = hex.split('').map(x => x + x).join('');
      }
      if (hex.length === 6) {
        const num = parseInt(hex, 16);
        return [(num >> 16) & 255, (num >> 8) & 255, num & 255, 1];
      }
      if (hex.length === 8) {
        const num = parseInt(hex, 16);
        return [(num >> 24) & 255, (num >> 16) & 255, (num >> 8) & 255, (num & 255) / 255];
      }
    }
    const match = str.match(/rgba?\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+))?\s*\)/i);
    if (match) {
      return [
        parseFloat(match[1]),
        parseFloat(match[2]),
        parseFloat(match[3]),
        match[4] !== undefined ? parseFloat(match[4]) : 1.0
      ];
    }
    return [255, 255, 255, 1];
  }

  /**
   * Multi-target color interpolation via spring.
   * @param {number} t - Current time in seconds
   * @param {Array<{t: number, color?: string, val?: string, omega?: number, zeta?: number}>} steps
   * @returns {string} CSS rgba(...) string
   */
  function multiTargetSpringColor(t, steps, defaultOmega = 14.0, defaultZeta = 0.82) {
    if (!steps || steps.length === 0) return 'rgba(0,0,0,1)';
    const parsedSteps = steps.map(s => {
      const rgba = parseColor(s.color || s.val);
      return { t: s.t, rgba, omega: s.omega, zeta: s.zeta };
    });

    const rSteps = parsedSteps.map(s => ({ t: s.t, val: s.rgba[0], omega: s.omega, zeta: s.zeta }));
    const gSteps = parsedSteps.map(s => ({ t: s.t, val: s.rgba[1], omega: s.omega, zeta: s.zeta }));
    const bSteps = parsedSteps.map(s => ({ t: s.t, val: s.rgba[2], omega: s.omega, zeta: s.zeta }));
    const aSteps = parsedSteps.map(s => ({ t: s.t, val: s.rgba[3], omega: s.omega, zeta: s.zeta }));

    const r = Math.max(0, Math.min(255, Math.round(multiTargetSpring(t, rSteps, defaultOmega, defaultZeta))));
    const g = Math.max(0, Math.min(255, Math.round(multiTargetSpring(t, gSteps, defaultOmega, defaultZeta))));
    const b = Math.max(0, Math.min(255, Math.round(multiTargetSpring(t, bSteps, defaultOmega, defaultZeta))));
    const a = Math.max(0, Math.min(1.0, multiTargetSpring(t, aSteps, defaultOmega, defaultZeta)));

    return `rgba(${r},${g},${b},${a.toFixed(3)})`;
  }

  /**
   * Smooth spring transition between two values a and b over a time window [t0, t0 + dur].
   * @param {number} a - Start value
   * @param {number} b - End value
   * @param {number} t - Current time
   * @param {number} t0 - Start time of transition
   * @param {number} omega_n - Natural frequency
   * @param {number} zeta - Damping ratio
   */
  function springTransition(a, b, t, t0, omega_n = 14.0, zeta = 0.82) {
    if (t <= t0) return a;
    const progress = stepResponse(t - t0, omega_n, zeta);
    return a + (b - a) * progress;
  }

  /**
   * Helper class to manage tracks of properties animated by closed-form springs.
   */
  class SpringTimeline {
    constructor(defaultOmega = 14.0, defaultZeta = 0.82) {
      this.defaultOmega = defaultOmega;
      this.defaultZeta = defaultZeta;
      this.tracks = new Map();
      this.colorTracks = new Map();
    }

    addStep(prop, t, val, omega, zeta) {
      if (!this.tracks.has(prop)) {
        this.tracks.set(prop, []);
      }
      this.tracks.get(prop).push({ t, val, omega, zeta });
      return this;
    }

    addColorStep(prop, t, color, omega, zeta) {
      if (!this.colorTracks.has(prop)) {
        this.colorTracks.set(prop, []);
      }
      this.colorTracks.get(prop).push({ t, color, omega, zeta });
      return this;
    }

    get(prop, t, fallback = 0) {
      const steps = this.tracks.get(prop);
      if (!steps) return fallback;
      return multiTargetSpring(t, steps, this.defaultOmega, this.defaultZeta);
    }

    getColor(prop, t, fallback = 'rgba(255,255,255,1)') {
      const steps = this.colorTracks.get(prop);
      if (!steps) return fallback;
      return multiTargetSpringColor(t, steps, this.defaultOmega, this.defaultZeta);
    }
  }

  return {
    stepResponse,
    multiTargetSpring,
    multiTargetSpringColor,
    springTransition,
    parseColor,
    SpringTimeline
  };
}));
