import pytest

from oskill._exceptions import OskillError
from oskill.render_template import TemplateVariableSpec, render_template


def test_render_template_fixed():
    spec = [TemplateVariableSpec(name="foo", source="fixed", fixed_value="bar")]
    res = render_template("value: {{foo}}", spec)
    assert res == "value: bar"


def test_render_template_user_provided():
    spec = [TemplateVariableSpec(name="name", source="user")]
    res = render_template("Hello {{name}}", spec, {"name": "Alice"})
    assert res == "Hello Alice"


def test_render_template_user_missing():
    spec = [TemplateVariableSpec(name="name", source="user")]
    with pytest.raises(OskillError, match="Missing required user input: name"):
        render_template("Hello {{name}}", spec, {})


def test_render_template_auto_date():
    spec = [TemplateVariableSpec(name="date", source="auto")]
    res = render_template("Today is {{date}}", spec)
    import re

    assert re.search(r"Today is \d{4}-\d{2}-\d{2}", res)


def test_render_template_auto_unsupported():
    spec = [TemplateVariableSpec(name="unsupported", source="auto")]
    with pytest.raises(OskillError, match="Unsupported auto variable: unsupported"):
        render_template("{{unsupported}}", spec)


def test_render_template_unknown_source():
    spec = [TemplateVariableSpec(name="foo", source="magic")]
    with pytest.raises(OskillError, match="Unknown source: magic"):
        render_template("{{foo}}", spec)


def test_render_template_multiple():
    spec = [
        TemplateVariableSpec(name="date", source="auto"),
        TemplateVariableSpec(name="user", source="user"),
        TemplateVariableSpec(name="greeting", source="fixed", fixed_value="Hi"),
    ]
    res = render_template("{{greeting}} {{user}}, today: {{date}}", spec, {"user": "Bob"})
    assert "Hi Bob, today: " in res


def test_render_template_no_vars():
    res = render_template("Plain text", [])
    assert res == "Plain text"


def test_render_template_auto_vars_all():
    for name in ["datetime", "time", "weekday", "year", "month", "day"]:
        spec = [TemplateVariableSpec(name=name, source="auto")]
        res = render_template(f"{{{{{name}}}}}", spec)
        assert res != f"{{{{{name}}}}}"
