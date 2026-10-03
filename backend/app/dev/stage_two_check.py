"""Preview routing cases offline; --llm explicitly enables paid Stage 2 calls.

Calls the classifier directly, bypassing Stage 1 and Stage 3. Does not build
observations, read chat history, retrieve memory, or call the main agent.
"""

import argparse
import json
import os

from openai import OpenAI

from backend.app.ai.agent.service import PROPOSAL_MODEL
from backend.app.ai.config import is_openai_api_key_configured
from backend.app.ai.context.contracts import ContextSelection
from backend.app.ai.context.intent import classify_agent_intent, context_from_classification


def _case(message, *, activities=None, exams=None, memory_time=None):
    return {
        "message": message,
        "expected": {
            "activities_scope": activities,
            "include_exams": exams is not None,
            "exam_scope": exams,
            "memory_scope": "global" if memory_time is not None else None,
            "memory_time_reference": memory_time,
        },
    }


CASES = {
    "A": _case("What time should I set my alarm tomorrow?", activities="tomorrow"),
    "B": _case("What time should I wake up tomorrow?", activities="tomorrow"),
    "C": _case("When should I leave home tomorrow?", activities="tomorrow"),
    "D": _case("What should I study tonight?", activities="today", exams="upcoming"),
    "E": _case("What exams do I have this week?", exams="this_week"),
    "F": _case("Tell me a joke about alarm clocks."),
    "G": _case("How does an alarm clock work?"),
    "H": _case("Don't use my calendar. What are some general tips for waking up earlier?"),
    "I": _case("Don't show me exams, just tell me my schedule tomorrow.", activities="tomorrow"),
    "J": _case("What did we decide last month about my study plan?", memory_time="last_month"),
}


def check_case(client, label):
    case = CASES[label]
    classification = classify_agent_intent(client, case["message"], [], PROPOSAL_MODEL)
    selection = context_from_classification(classification)
    ContextSelection.model_validate(selection)
    memory = selection.get("memory")
    actual = {
        "activities_scope": selection["activities_scope"],
        "include_exams": selection["include_exams"],
        "exam_scope": selection["exam_scope"],
        "memory_scope": memory.get("scope") if memory else None,
        "memory_time_reference": memory["query"]["time_reference"] if memory else None,
    }
    # Intent labels need not be identical when the information dependencies agree.
    # A selected memory source still counts as unexpected even if its scope is null.
    expected_memory = case["expected"]["memory_scope"] is not None
    passed = (classification.confidence == "high" and actual == case["expected"]
              and (memory is not None) == expected_memory)
    return {
        "case": label, "message": case["message"], "expected": case["expected"],
        "classification": classification.model_dump(), "selection": selection,
        "passed": passed,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=tuple(CASES), action="append",
                        help="Check a named case; repeat to select several. Default: A-J.")
    parser.add_argument("--llm", action="store_true",
                        help="Make paid classifier calls using the backend's configured API key.")
    args = parser.parse_args(argv)
    labels = list(dict.fromkeys(args.case or CASES))

    if not args.llm:
        print(json.dumps({
            "mode": "offline preview; no model calls or semantic verification",
            "cases": [{"case": label, **CASES[label]} for label in labels],
        }, indent=2))
        return 0

    if not is_openai_api_key_configured():
        parser.error("OPENAI_API_KEY is not configured in the backend environment.")
    print(f"Paid Stage 2 evaluation: {len(labels)} classifier request(s); model={PROPOSAL_MODEL}.")
    failures = 0
    try:
        with OpenAI(api_key=os.environ["OPENAI_API_KEY"].strip(), timeout=30, max_retries=0) as client:
            for label in labels:
                try:
                    result = check_case(client, label)
                except Exception:
                    # SDK exceptions may contain request details; do not echo them.
                    result = {"case": label, "passed": False,
                              "error": "Classifier request failed or returned an invalid result."}
                print(json.dumps(result, indent=2))
                failures += not result["passed"]
    except Exception:
        print("Could not initialize or close the classifier client.")
        return 1
    print(f"Passed {len(labels) - failures}/{len(labels)} cases.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
