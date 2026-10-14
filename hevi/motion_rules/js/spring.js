/**
 * Closed-form spring animation system for JavaScript (pure function step response).
 *
 * Mathematically identical to hevi/motion_rules/spring.py.
 * Multi-target tracks are computed by linear superposition of individual step responses:
 *   value(t) = initial_value + sum_i (delta_target_i * spring_step(t - t_i)).
 * All calculations are pure functions of time without frame-to-frame mutable state.
 */

(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else if (typeof define === 'function' && define.amd) {
    define([], factory);
  } else {
    root.SpringMotion = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function springStep(t, omega, zeta) {
    if (t <= 0.0) {
      return 0.0;
    }
    const eps = 1e-7;
    if (Math.abs(zeta - 1.0) <= eps) {
      // Critically damped
      const decay = Math.exp(-omega * t);
      return 1.0 - decay * (1.0 + omega * t);
    } else if (zeta < 1.0) {
      // Underdamped
      const omegaD = omega * Math.sqrt(1.0 - zeta * zeta);
      const decay = Math.exp(-zeta * omega * t);
      const envelope = Math.cos(omegaD * t) + (zeta * omega / omegaD) * Math.sin(omegaD * t);
      return 1.0 - decay * envelope;
    } else {
      // Overdamped
      const omegaD = omega * Math.sqrt(zeta * zeta - 1.0);
      const decay = Math.exp(-zeta * omega * t);
      const envelope = Math.cosh(omegaD * t) + (zeta * omega / omegaD) * Math.sinh(omegaD * t);
      return 1.0 - decay * envelope;
    }
  }

  function springVelocity(t, omega, zeta) {
    if (t <= 0.0) {
      return 0.0;
    }
    const eps = 1e-7;
    if (Math.abs(zeta - 1.0) <= eps) {
      const decay = Math.exp(-omega * t);
      return (omega * omega) * t * decay;
    } else if (zeta < 1.0) {
      const omegaD = omega * Math.sqrt(1.0 - zeta * zeta);
      const decay = Math.exp(-zeta * omega * t);
      return ((omega * omega) / omegaD) * decay * Math.sin(omegaD * t);
    } else {
      const omegaD = omega * Math.sqrt(zeta * zeta - 1.0);
      const decay = Math.exp(-zeta * omega * t);
      return ((omega * omega) / omegaD) * decay * Math.sinh(omegaD * t);
    }
  }

  class Spring {
    constructor(options = {}) {
      const mass = options.mass !== undefined ? Number(options.mass) : 1.0;
      if (mass <= 0.0) {
        throw new Error(`mass must be positive, got ${mass}`);
      }
      this.mass = mass;

      if (options.omega !== undefined && options.zeta !== undefined) {
        const omega = Number(options.omega);
        const zeta = Number(options.zeta);
        if (omega <= 0.0) throw new Error(`omega must be positive, got ${omega}`);
        if (zeta < 0.0) throw new Error(`zeta must be non-negative, got ${zeta}`);
        this.omega = omega;
        this.zeta = zeta;
      } else if (options.stiffness !== undefined && options.damping !== undefined) {
        const stiffness = Number(options.stiffness);
        const damping = Number(options.damping);
        if (stiffness <= 0.0) throw new Error(`stiffness must be positive, got ${stiffness}`);
        if (damping < 0.0) throw new Error(`damping must be non-negative, got ${damping}`);
        this.omega = Math.sqrt(stiffness / mass);
        this.zeta = damping / (2.0 * Math.sqrt(mass * stiffness));
      } else {
        // Default snappy UI spring
        this.omega = 10.0;
        this.zeta = 0.75;
      }
    }

    get stiffness() {
      return this.mass * this.omega * this.omega;
    }

    get damping() {
      return 2.0 * this.mass * this.zeta * this.omega;
    }

    step(t) {
      return springStep(t, this.omega, this.zeta);
    }

    velocity(t) {
      return springVelocity(t, this.omega, this.zeta);
    }
  }

  class SpringTrack {
    constructor(keyframes = [], spring = null, options = {}) {
      this.spring = spring || new Spring();
      this.initialValue = options.initialValue !== undefined ? Number(options.initialValue) : 0.0;
      this._keyframes = [];
      if (Array.isArray(keyframes)) {
        for (const kf of keyframes) {
          const t = Array.isArray(kf) ? kf[0] : kf.t;
          const target = Array.isArray(kf) ? kf[1] : kf.target;
          this.addKeyframe(t, target);
        }
      }
    }

    addKeyframe(t, target) {
      this._keyframes.push([Number(t), Number(target)]);
      this._keyframes.sort((a, b) => a[0] - b[0]);
    }

    getKeyframes() {
      return this._keyframes.slice();
    }

    _getSteps() {
      if (this._keyframes.length === 0) {
        return [];
      }
      const steps = [];
      let prevTarget = this.initialValue;
      for (const [t, target] of this._keyframes) {
        const delta = target - prevTarget;
        steps.push([t, delta]);
        prevTarget = target;
      }
      return steps;
    }

    value(t) {
      const steps = this._getSteps();
      if (steps.length === 0) {
        return this.initialValue;
      }
      let res = this.initialValue;
      const omega = this.spring.omega;
      const zeta = this.spring.zeta;
      for (const [tK, delta] of steps) {
        if (t >= tK) {
          res += delta * springStep(t - tK, omega, zeta);
        }
      }
      return res;
    }

    velocity(t) {
      const steps = this._getSteps();
      if (steps.length === 0) {
        return 0.0;
      }
      let vel = 0.0;
      const omega = this.spring.omega;
      const zeta = this.spring.zeta;
      for (const [tK, delta] of steps) {
        if (t >= tK) {
          vel += delta * springVelocity(t - tK, omega, zeta);
        }
      }
      return vel;
    }

    values(ts) {
      return ts.map((t) => this.value(t));
    }
  }

  function createSpring(config) {
    return new Spring(config);
  }

  // CLI JSON evaluation helper when invoked directly from Node
  if (typeof process !== 'undefined' && process.argv && process.argv[1] && process.argv[1].endsWith('spring.js')) {
    if (process.argv.includes('--eval-json')) {
      let inputData = '';
      process.stdin.setEncoding('utf-8');
      process.stdin.on('data', (chunk) => { inputData += chunk; });
      process.stdin.on('end', () => {
        try {
          const req = JSON.parse(inputData);
          const spring = new Spring(req.spring || {});
          const track = new SpringTrack(req.keyframes || [], spring, { initialValue: req.initialValue || 0.0 });
          const times = req.sampleTimes || [];
          const values = track.values(times);
          const velocities = times.map((t) => track.velocity(t));
          process.stdout.write(JSON.stringify({ values, velocities }));
        } catch (err) {
          process.stderr.write(String(err));
          process.exit(1);
        }
      });
    }
  }

  return {
    Spring,
    SpringTrack,
    springStep,
    springVelocity,
    createSpring,
  };
});
