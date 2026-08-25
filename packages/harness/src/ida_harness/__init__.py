"""ida_harness -- the standalone benchmark harness.

This package is the starred deliverable: it must remain installable and runnable
OUTSIDE this repo. That constraint is why it depends on nothing from services/
and why the task suite is passed in as a path rather than discovered from a
hard-coded location.

SCAFFOLDING BOUNDARY, stated plainly:
  * `tasks.py` (loading) and `scoring.py` (exact/contains/numeric) are REAL --
    they are the contract tools/validate_tasks.py enforces, and CI tests them.
  * `clients.py` provider implementations are STUBS that raise. Filling them in
    is the project's own work; the protocol they must satisfy is fixed here so
    the runner, the mock and the real providers stay interchangeable.
"""

from ida_harness.scoring import score_response
from ida_harness.tasks import Task, load_tasks

__all__ = ["Task", "load_tasks", "score_response"]
__version__ = "0.1.0"
