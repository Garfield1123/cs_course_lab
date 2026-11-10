"""Pure policy interface. This module is NOT integrated into GateANN's query loop."""
import math


def choose_budget(selectivity: float) -> int:
    """Selectivity is a fraction [0, 1], never a percentage or a Recall value."""
    if isinstance(selectivity, bool) or not isinstance(selectivity, (int, float)):
        raise ValueError('selectivity must be a numeric fraction')
    if not math.isfinite(selectivity) or not 0 <= selectivity <= 1:
        raise ValueError('selectivity must be finite and in [0, 1]')
    return 640 if selectivity < .01 else 480 if selectivity < .05 else 320


def workload_budget(selectivities) -> int:
    choices = {choose_budget(s) for s in selectivities}
    if len(choices) != 1:
        raise ValueError('empty workload or workload crosses policy thresholds; per-query integration required')
    return choices.pop()
