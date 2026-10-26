"""Revision workflow.

A revision is the same work as a resume-from-outline::

    START
      -> Research
      -> Writer
      -> Editor
      -> Normalize Editor
      -> route_after_editor --revise--> Writer
                          --approve--> end

The approved outline carries over unchanged, research is redone against the
reviewer's feedback, and the writer/editor cycle runs again to produce a new
version.

The revision and continuation builders share one graph definition because they have
the same execution path. They retain distinct workflow names so lifecycle
identity stays visible in tracing and can diverge later if requirements change.
Creating the extra blog version remains the repository's job; this module only
decides what executes.
"""

from __future__ import annotations

from google.adk.workflow import Workflow

from src.workflows.common import build_post_outline_workflow

WORKFLOW_NAME = "blog_revision"


def build_revision_workflow() -> Workflow:
    """Build the graph used to regenerate a blog after a revision request."""
    return build_post_outline_workflow(WORKFLOW_NAME)
