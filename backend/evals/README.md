# Blogify evaluation suite

The evals are organized around one shared golden dataset and one module per
evaluation question. `full_eval.py` runs each golden through the real ADK
workflow phases, captures the ADK events, then runs the applicable metrics.

| Module | Question | DeepEval metric |
| --- | --- | --- |
| `metrics/answer_correctness.py` | Does the final blog meet the reference requirements? | `GEval` |
| `metrics/groundedness.py` | Are factual claims supported by research evidence? | `FaithfulnessMetric` |
| `metrics/argument_correctness.py` | Were research tool arguments appropriate for the request? | `ArgumentCorrectnessMetric` |
| `metrics/tool_correctness.py` | Did research select the expected tool? | `ToolCorrectnessMetric` |
| `metrics/task_completion.py` | Did the run deliver the requested blog? | `TaskCompletionMetric` |
| `metrics/step_efficiency.py` | Were the run's steps useful and necessary? | `StepEfficiencyMetric` |

The dataset currently has two evidence-backed generation cases and one blocked
intent case. Fixed research payloads remove search-provider variance while the
configured app models still generate the outline and blog. Blocked requests
are checked deterministically because this workflow phase returns a gate
decision; it does not generate the user-facing refusal text.

## Run

From `backend/`, install the optional dependencies and configure the app model
credentials and DeepEval judge model:

```bash
pip install -e '.[dev,evals]'
RUN_DEEPEVAL_EVALS=1 DEEPEVAL_JUDGE_MODEL=gpt-4.1 python -m evals.full_eval
```

Task completion and step efficiency use a DeepEval root trace. The trace adapter
maps ordered ADK events to nested spans because ADK does not emit DeepEval
spans directly. Tool choice and argument checks use the same captured events in
DeepEval `LLMTestCase` objects. Treat initial judge thresholds as calibration
values; review score reasons and a human-checked baseline before using them as
release gates.
