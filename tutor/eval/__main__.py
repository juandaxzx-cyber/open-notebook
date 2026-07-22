"""CLI: ``uv run python -m tutor.eval`` (or ``make eval-tutor``).

Needs only TUTOR_LLM_* (+ provider API key) in the environment — no
SurrealDB, no OpenNotebook. Judge defaults to the tutor's provider/model;
set TUTOR_JUDGE_PROVIDER / TUTOR_JUDGE_MODEL to a DIFFERENT family for
unbiased scores (the run warns otherwise). Writes eval_runs/<timestamp>.json.
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from tutor.app import _verifier_from_env
from tutor.config import TutorSettings
from tutor.eval.personas import load_personas
from tutor.eval.rubric import CRITERIA
from tutor.eval.runner import run_eval
from tutor.llm.esperanto import EsperantoProvider
from tutor.llm.factory import provider_from_env

OUT_DIR = Path("eval_runs")


async def _main() -> int:
    load_dotenv()
    settings = TutorSettings.from_env()
    tutor_llm = provider_from_env(settings)
    tutor_desc = f"{settings.llm_provider}/{settings.llm_model}"

    judge_provider = settings.judge_provider or settings.llm_provider
    judge_model = settings.judge_model or settings.llm_model
    judge_desc = f"{judge_provider}/{judge_model}"
    if judge_provider == settings.llm_provider:
        print(
            "WARNING: judge provider == tutor provider "
            f"({judge_provider}). Same-family judging inflates scores "
            "(self-preference bias); set TUTOR_JUDGE_PROVIDER/MODEL.",
            file=sys.stderr,
        )
    judge_llm = EsperantoProvider(
        provider=str(judge_provider), model_name=str(judge_model)
    )

    # W1-eval addendum: the escalation-ladder verifier is resolved exactly
    # like the live service (`tutor.app._verifier_from_env` — reused here
    # rather than re-implemented, since `tutor.app` has no dependency on
    # `tutor.eval` so the import can't cycle). `settings.verify_turns`
    # ("off" by default, matching the pre-addendum runner byte-for-byte) is
    # the before/after lever the merge gate dispatches on.
    verifier_llm = _verifier_from_env(settings, tutor_llm)

    personas = load_personas()
    print(
        f"tutor={tutor_desc} judge={judge_desc} personas={len(personas)} "
        f"verify_turns={settings.verify_turns} verify_profile={settings.verify_profile}"
    )
    report = await run_eval(
        personas,
        tutor_llm,
        judge_llm,
        tutor_desc=tutor_desc,
        judge_desc=judge_desc,
        verifier_llm=verifier_llm,
        verify_turns=settings.verify_turns,
        verify_profile=settings.verify_profile,
        grounding_budget_tokens=settings.grounding_budget_tokens,
    )

    OUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = OUT_DIR / f"{stamp}.json"
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # console table: criteria x personas
    ids = [c.id for c in CRITERIA]
    width = max(len(i) for i in ids)
    header = (
        " " * width
        + "  "
        + "  ".join(f"{r['persona'][:12]:>12}" for r in report["personas"])
    )
    print("\n" + header)
    for cid in ids:
        row = f"{cid:<{width}}  " + "  ".join(
            f"{str(r['scores'][cid]['score']):>12}" for r in report["personas"]
        )
        print(row + f"   mean={report['criteria_means'][cid]}")
    print(f"\noverall mean: {report['overall_mean']}  →  {out_path}")

    # W1-eval addendum: surface the grounded-persona-only measurements
    # (outside criteria_means by design) so a dispatch's console log alone
    # is enough to eyeball the merge gate without opening the JSON.
    for r in report["personas"]:
        if r.get("citation_check") is None:
            continue
        cc = r["citation_check"]
        v = r["verification"]
        print(
            f"grounded persona {r['persona']}: "
            f"invented_citations={r['metrics'].get('invented_citations')} "
            f"citation_check={cc['score']} "
            f"verification_gated_turns={v['gated_turns']} "
            f"outcomes={v['outcomes']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
