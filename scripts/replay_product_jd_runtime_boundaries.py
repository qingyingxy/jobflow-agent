"""Replay saved final outputs with no model calls; optionally prepare a dev subset."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from scripts.run_product_jd_paired_acceptance import (
    DATASET,
    EDUCATION_LABELS,
    qualifications,
)
from src.domain.job import RawJobDocument
from src.infrastructure.llm_client import FakeModelClient
from src.services.product_jd_execution import ProductJDExecutionParser

DEV_IDS = {
    "campus-ai-003",
    "campus-ai-012",
    "campus-ai-060",
    "campus-ai-074",
    "campus-ai-101",
    "campus-ai-174",
}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("previous_dir", type=Path)
    cli.add_argument("--output", required=True, type=Path)
    cli.add_argument("--prepare-dev-dir", type=Path)
    args = cli.parse_args()
    if args.output.exists():
        cli.error("Use a fresh output path")
    rows = json.loads(
        (args.previous_dir / "predictions.json").read_text(encoding="utf-8")
    )["results"]
    cases = json.loads((args.previous_dir / "cases.json").read_text(encoding="utf-8"))[
        "cases"
    ]
    by_id = {c["id"]: c for c in cases}
    replay = []
    for row in rows:
        case = by_id[row["case_id"]]
        record = {
            "case_id": row["case_id"],
            "mode": row["mode"],
            "previously_parsed": row["output"] is not None,
        }
        job = None
        if row["output"] is None:
            record.update(status="no_saved_final_output")
        else:
            parser = ProductJDExecutionParser(FakeModelClient(), mode=row["mode"])
            doc = RawJobDocument(raw_content=case["raw_content"])
            try:
                extraction = parser._extraction(row["raw_extraction"], doc)
                relations = parser._relations(
                    row["raw_relation_judgment"], extraction, doc
                )
                job = parser.compile_result(
                    doc, parser._result(extraction, relations, [])
                ).structured_jd
            except (TypeError, ValueError) as error:
                record.update(
                    status="rejected", errors=parser._validation_errors(error)
                )
            else:
                record.update(status="accepted")
        record["qualifications"] = qualifications(
            job, case.get("qualification_labels", [])
        )
        replay.append(record)
    write_json(
        args.output,
        {
            "model_calls": 0,
            "purpose": "Compatibility/contradiction replay of saved outputs, not new model accuracy; rejected outputs are not repaired.",
            "counts": dict(Counter((r["mode"] + ":" + r["status"]) for r in replay)),
            "results": replay,
        },
    )
    if args.prepare_dev_dir:
        if args.prepare_dev_dir.exists():
            cli.error("Use a fresh dev directory")
        dataset = json.loads(DATASET.read_text(encoding="utf-8"))
        labels = json.loads(EDUCATION_LABELS.read_text(encoding="utf-8"))
        dataset["cases"] = [c for c in dataset["cases"] if c["id"] in DEV_IDS]
        labels["real_annotations"] = [
            c for c in labels["real_annotations"] if c["case_id"] in DEV_IDS
        ]
        args.prepare_dev_dir.mkdir(parents=True)
        write_json(args.prepare_dev_dir / "dataset.json", dataset)
        write_json(args.prepare_dev_dir / "education_labels.json", labels)
        write_json(
            args.prepare_dev_dir / "selection.json",
            {
                "purpose": "Known failures/development; not independent evaluation",
                "real_ids": sorted(DEV_IDS),
                "synthetic_count": len(labels["synthetic_cases"]),
            },
        )
    print(
        json.dumps(
            {
                "model_calls": 0,
                "counts": dict(Counter(r["mode"] + ":" + r["status"] for r in replay)),
            }
        )
    )


if __name__ == "__main__":
    main()
