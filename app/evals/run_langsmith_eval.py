"""Runs the synthesizer-safety eval as a LangSmith experiment.

Target  = the real synthesizer (raw context -> brief).
Evaluator = the LLM judge (temperature 0), reusing the same RUBRIC as the local run.
Per-case scores and the aggregate are saved as an experiment under the dataset, so
the baseline stops being an ephemeral terminal print and becomes a versioned record.
"""
from datetime import date

from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import evaluate

import config  # noqa: F401  -> triggers load_dotenv so LANGSMITH_* + GEMINI_API_KEY are in the env
from app.conversation import build_synthesizer
from app.evals.score_synthesizer import RUBRIC, build_judge

DATASET = "tutor-synthesizer-safety"
VERSION = "v1"  # bump to "v2" when you change the synthesizer prompt, to compare in LangSmith

_synthesizer = build_synthesizer()
_judge = build_judge()


def target(inputs: dict) -> dict:
    """The system under test: the real synthesizer."""
    return {"brief": _synthesizer.synthesize(inputs["context"])}


def safety(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    """LLM-judge evaluator. Returns a 0/1 score under the key 'safety'."""
    message = (
        f"CONTEXT: {inputs['context']}\n\n"
        f"BRIEF:\n{outputs['brief']}\n\n"
        f"EXPECTED: {reference_outputs['expected']}"
    )
    verdict = _judge.invoke([SystemMessage(RUBRIC), HumanMessage(message)])
    return {"key": "safety", "score": int(verdict.passed), "comment": verdict.reasoning}


if __name__ == "__main__":
    evaluate(
        target,
        data=DATASET,
        evaluators=[safety],
        experiment_prefix=f"synthesizer-{VERSION}-{date.today().isoformat()}",
        metadata={"prompt_version": VERSION},
        max_concurrency=4,
    )
