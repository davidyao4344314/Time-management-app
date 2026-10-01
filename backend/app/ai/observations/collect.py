"""Build only the observations selected by the context router."""

from backend.app.ai.observations.activities import build_activity_observation
from backend.app.ai.observations.exams import build_exam_observation
from backend.app.ai.observations.memory import build_memory_observation


def collect_agent_observations(
    connection, selection, *,
    activity_builder=build_activity_observation,
    exam_builder=build_exam_observation,
    session_id=None,
):
    """Keep factual app state separate from the current request and recent turns.

    Optional builders allow offline tests to supply observations without opening
    a database. Routing and recurrence are not calculated in this collector.
    """
    context = {}
    if selection["activities_scope"] is not None:
        context["activities"] = activity_builder(
            connection, scope=selection["activities_scope"],
        )
    if selection["include_exams"]:
        context["exams"] = exam_builder(
            connection, scope=selection["exam_scope"],
        )
    if selection.get("memory") is not None:
        context["memory"] = build_memory_observation(selection["memory"], session_id=session_id)
    return context
