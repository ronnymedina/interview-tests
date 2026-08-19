"""Runs the real synthesizer over the seed cases and prints each brief.
No judging yet: this only captures what the synthesizer produces today.
"""
from app.conversation import build_synthesizer
from app.evals.cases_synthesizer import CASES


def run() -> list[dict]:
    synthesizer = build_synthesizer()
    results = []
    for case in CASES:
        brief = synthesizer.synthesize(case["context"])
        results.append({**case, "brief": brief})

    return results


if __name__ == "__main__":
    for r in run():
        print("=" * 60)
        print(f"[{r['category']} / {r['lang']}] expected={r['expected']}")
        print(f"context: {r['context']}")
        print(f"brief:\n{r['brief']}")
