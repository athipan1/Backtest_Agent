import importlib.util
from pathlib import Path
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "diagnose_nested_oos_stability.py"
spec = importlib.util.spec_from_file_location("stability_diagnostics", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_three_of_six_fails_without_trade_approval():
    report = module.diagnose([{"net_return": x} for x in [1, -1, 2, -2, 3, 0]])
    assert report["positive_windows"] == 3
    assert report["required_positive_windows"] == 4
    assert report["shortfall"] == 1
    assert report["trading_eligible"] is False


def test_four_of_six_diagnostic_pass_is_not_trade_approval():
    report = module.diagnose([{"net_return": x} for x in [1, 2, 3, 4, -1, -2]])
    assert report["passes_positive_fraction_diagnostic"] is True
    assert report["trading_eligible"] is False


@pytest.mark.parametrize("windows", [[], [{"net_return": float("nan")}], [{"net_return": True}], [{}]])
def test_invalid_inputs_fail_closed(windows):
    with pytest.raises(ValueError):
        module.diagnose(windows)
