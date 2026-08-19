"""Syncs the synthesizer-safety dataset in LangSmith from CASES.
CASES is the source of truth: if the dataset already exists it is deleted and
recreated so LangSmith always matches the local file. Safe for now (no experiments
to lose yet); once experiments exist, prefer updating examples in place instead."""
from langsmith import Client

import config  # noqa: F401  -> triggers load_dotenv so LANGSMITH_* are in the env
from app.evals.cases_synthesizer import CASES

DATASET = "tutor-synthesizer-safety"


def upload() -> None:
    client = Client()
    if client.has_dataset(dataset_name=DATASET):
        client.delete_dataset(dataset_name=DATASET)
        print(f"Dataset '{DATASET}' existed — deleted to re-sync from CASES.")
    ds = client.create_dataset(
        dataset_name=DATASET,
        description="Raw learner contexts (safe/normal) to test the synthesizer guardrail.",
    )
    client.create_examples(
        dataset_id=ds.id,
        inputs=[{"context": c["context"]} for c in CASES],
        outputs=[{"expected": c["expected"]} for c in CASES],
        metadata=[{"category": c["category"], "lang": c["lang"]} for c in CASES],
    )
    print(f"Uploaded {len(CASES)} examples to dataset '{DATASET}'.")


if __name__ == "__main__":
    upload()
