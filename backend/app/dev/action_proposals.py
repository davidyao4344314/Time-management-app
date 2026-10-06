"""Manual pending proposal fixture, never a model call or activity insertion."""

from backend.app.ai.actions.contracts import ActionProposal, AddActivityArguments
from backend.app.infrastructure.clock import local_now


def create_test_activity_proposal():
    arguments = AddActivityArguments(
        name="Study Maths (approval test)", category="Study", subject="MATHS 102",
        activity_type="one_time", date=local_now().date().isoformat(), weekday=None,
        start_time="19:00", end_time="20:00",
    ).model_dump(mode="json")
    return ActionProposal(
        tool_name="add_activity", arguments=arguments,
        display_title="Add Activity",
        display_description=(
            f"Study Maths (approval test)\n{arguments['date']} · 19:00–20:00\n"
            "Category: Study · Subject: MATHS 102\n"
            "Confirm will save this test activity to your local database."
        ),
    )
