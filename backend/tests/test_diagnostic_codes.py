"""Every diagnostic code the engine can emit is listed for the UI, which explains each with a cause and a fix."""

import json

from opticore.tools.diagnostic_codes import FIXTURE, collect_codes


def test_ui_fixture_lists_every_engine_diagnostic_code():
    codes = collect_codes()
    assert len(codes) >= 40
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == codes, "regenerate: python -m opticore.tools.diagnostic_codes --write"
    for code, levels in codes.items():
        assert code.isupper() and set(levels) <= {"info", "warning", "error"}, code
