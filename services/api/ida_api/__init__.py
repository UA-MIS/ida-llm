"""``ida_api`` -- the FastAPI service.

Responsibilities, and deliberately nothing else:

* serve the **model registry** (parsed ``models.yaml``) and the **task catalog**
* **enqueue** runs (mint ids, insert ``queued`` rows, push queue messages)
* **read** runs and results for the UI

It never calls a model.  It never scores anything.  That is the runner's job,
and keeping the split sharp is what lets the runner scale independently (D-5).
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
