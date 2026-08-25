import pytest

from ida_runner.sweeps import SWEEPS, main


@pytest.mark.parametrize("name", sorted(SWEEPS))
def test_each_sweep_runs(name):
    # Each CronJob manifest names one of these. A typo in a schedule would
    # otherwise only surface at 02:00 as a CrashLoopBackOff nobody is watching.
    assert main([name, "--dry-run"]) == 0


def test_unknown_sweep_is_rejected():
    with pytest.raises(SystemExit):
        main(["not-a-sweep"])
