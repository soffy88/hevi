"""Orchestrate: solve a math problem then generate SVG visualisation.

Composes oprim kernel elements — no direct LLM call in this skill.
Selects the appropriate solver based on problem type, then generates
a 2D plot or diagram from the result.

Version: oskill v3.21.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ProblemType = Literal[
    "function", "conic", "derivative", "trig", "sequence", "probability", "geometry3d", "auto"
]


@dataclass(frozen=True)
class SolveAndVisualizeInput:
    """Input for solve-and-visualise.

    Attributes
    ----------
    expression : str
        The math expression or equation.
    problem_type : ProblemType
        Problem category (or "auto" to guess from expression).
    variable : str
        Primary variable.
    x_range : tuple[float, float]
        X-axis range for 2D plot.
    num_points : int
        Number of sample points for plot.
    generate_svg : bool
        Whether to generate an SVG diagram.
    """

    expression: str
    problem_type: ProblemType = "auto"
    variable: str = "x"
    x_range: tuple[float, float] = (-10.0, 10.0)
    num_points: int = 200
    generate_svg: bool = True


@dataclass
class SolveAndVisualizeResult:
    """Result of solve-and-visualise.

    Attributes
    ----------
    solve_answer : str
        The kernel's answer string.
    solve_steps : list[dict]
        Solution steps (from SolveResult).
    svg : str
        SVG diagram string (empty if generate_svg=False or plotting failed).
    problem_type_used : str
        Which problem type was actually used.
    solvable : bool
    error : str
    """

    solve_answer: str = ""
    solve_steps: list[dict] = field(default_factory=list)
    svg: str = ""
    problem_type_used: str = ""
    solvable: bool = False
    error: str = ""


def _guess_problem_type(expression: str) -> ProblemType:
    """Guess problem type from expression content."""
    expr_lower = expression.lower()
    if any(k in expr_lower for k in ["sin", "cos", "tan", "cot", "sec", "csc"]):
        return "trig"
    if any(k in expr_lower for k in ["x**2", "y**2", "ellipse", "circle", "conic", "x^2", "y^2"]):
        if "y" in expr_lower and ("x**2" in expr_lower or "x^2" in expr_lower):
            return "conic"
        return "function"
    if any(k in expr_lower for k in ["d/dx", "diff", "derivative", "tangent"]):
        return "derivative"
    return "function"


def solve_and_visualize(inp: SolveAndVisualizeInput) -> SolveAndVisualizeResult:
    """Solve a math problem and generate an SVG visualisation.

    Orchestrates:
    1. Selects the right oprim solver based on problem_type.
    2. Calls the solver to get SolveResult.
    3. If generate_svg, converts to Plot2DData and generates SVG.

    Parameters
    ----------
    inp : SolveAndVisualizeInput

    Returns
    -------
    SolveAndVisualizeResult
    """
    from oprim.generate_svg_diagram import generate_svg_diagram
    from oprim.kernel_to_plot2d import Plot2DRequest, kernel_to_plot2d
    from oprim.solve_conic import solve_conic
    from oprim.solve_derivative import DerivativeSolveInput, solve_derivative
    from oprim.solve_function import FunctionSolveInput, solve_function
    from oprim.solve_trig import TrigSolveInput, solve_trig

    problem_type = inp.problem_type
    if problem_type == "auto":
        problem_type = _guess_problem_type(inp.expression)

    solve_result = None
    error = ""

    try:
        if problem_type == "conic":
            solve_result = solve_conic(inp.expression)
        elif problem_type == "derivative":
            solve_result = solve_derivative(
                DerivativeSolveInput(
                    expression=inp.expression,
                    variable=inp.variable,
                    task="derivative",
                )
            )
        elif problem_type == "trig":
            solve_result = solve_trig(
                TrigSolveInput(
                    expression=inp.expression,
                    variable=inp.variable,
                    task="simplify",
                )
            )
        else:  # function or fallback
            solve_result = solve_function(
                FunctionSolveInput(
                    expression=inp.expression,
                    variable=inp.variable,
                    task="zeros",
                )
            )
    except Exception as exc:
        error = str(exc)

    if solve_result is None:
        return SolveAndVisualizeResult(
            solvable=False,
            error=error or "Solver returned None",
            problem_type_used=problem_type,
        )

    steps_dicts = [
        {
            "step_number": s.step_number,
            "description": s.description,
            "expression": s.expression,
            "result": s.result,
        }
        for s in solve_result.steps
    ]

    svg_str = ""
    if inp.generate_svg and problem_type not in ("conic", "geometry3d", "probability"):
        try:
            plot_req = Plot2DRequest(
                expression=inp.expression,
                variable=inp.variable,
                x_range=inp.x_range,
                num_points=inp.num_points,
                mark_zeros=True,
                solve_result=solve_result,
            )
            plot_data = kernel_to_plot2d(plot_req)
            svg_str = generate_svg_diagram(plot_data)
        except Exception as exc:
            error = f"SVG generation failed: {exc}"

    return SolveAndVisualizeResult(
        solve_answer=solve_result.answer,
        solve_steps=steps_dicts,
        svg=svg_str,
        problem_type_used=problem_type,
        solvable=solve_result.solvable,
        error=solve_result.error or error,
    )
