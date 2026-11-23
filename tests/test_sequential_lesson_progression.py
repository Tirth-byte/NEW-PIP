"""Regression tests for evidence-based, sequential lesson progression."""
import time

import pytest

from app.curriculum.loader import get_module
from app.database.connection import get_db, init_db
from app.database.crud import create_learner_for_user, mark_lesson_complete, update_lesson_activity
from app.database.models import User
from app.learning.progression import (
    ProgressionError,
    complete_reading_section,
    complete_video,
    get_lesson_progress,
    lesson_access,
    mark_video_started,
    run_experiment,
    submit_checkpoint_answer,
    submit_practice_solution,
)
from app.navigation.nav import resolve_resume_destination


def _learner(db):
    suffix = str(time.time_ns())
    user = User(
        username=f"sequence_{suffix}",
        email=f"sequence_{suffix}@example.test",
        password_hash="test-only",
    )
    db.add(user)
    db.commit()
    return user, create_learner_for_user(db, user.id, "Sequence Learner")


def test_strict_progression_and_certification_preserve_work():
    init_db()
    with get_db() as db:
        user, learner = _learner(db)
        module = get_module(1)
        lesson = module.lessons[0]
        next_lesson = module.lessons[1]

        progress = get_lesson_progress(db, learner.id, module.id, lesson.id)
        activity = progress["activity"]
        update_lesson_activity(
            db,
            activity.id,
            stage="check",              # navigation history must not grant access
            reading_section=4,
            notes="keep this note",
            experiment_code="print('saved')",
        )

        progress = get_lesson_progress(db, learner.id, module.id, lesson.id)
        assert progress["unlocked"] == {
            "read": True,
            "watch": False,
            "experiment": False,
            "practice": False,
            "check": False,
        }
        assert not lesson_access(db, learner.id, module.id, next_lesson.id)["accessible"]

        # Continue ignores forged/stale display history and resumes first evidence gap.
        destination = resolve_resume_destination(db, learner.id)
        assert destination["stage"] == "read"
        assert destination["reading_section"] == 0
        assert destination["route"].endswith("?resume=1")

        with pytest.raises(ProgressionError, match="previous reading"):
            complete_reading_section(db, learner.id, module.id, lesson.id, 2)

        for section_idx in range(len(progress["parts"]["sections"])):
            progress = complete_reading_section(
                db, learner.id, module.id, lesson.id, section_idx
            )
        assert progress["complete"]["read"]
        assert progress["unlocked"]["watch"]

        with pytest.raises(ProgressionError, match="Start the lesson video"):
            complete_video(db, learner.id, module.id, lesson.id)
        mark_video_started(db, learner.id, module.id, lesson.id)
        progress = complete_video(db, learner.id, module.id, lesson.id)
        assert progress["unlocked"]["experiment"]

        failed = run_experiment(db, learner.id, module.id, lesson.id, "raise RuntimeError('no')")
        assert not failed["execution"]["success"]
        assert not failed["progress"]["unlocked"]["practice"]
        passed = run_experiment(db, learner.id, module.id, lesson.id, "print('ok')")
        assert passed["execution"]["success"]
        assert passed["progress"]["unlocked"]["practice"]

        with pytest.raises(ProgressionError, match="previous challenge"):
            submit_practice_solution(
                db, learner.id, module.id, lesson.id, 1,
                progress["parts"]["challenges"][1].solution,
            )
        for challenge_idx, challenge in enumerate(progress["parts"]["challenges"]):
            result = submit_practice_solution(
                db, learner.id, module.id, lesson.id, challenge_idx, challenge.solution
            )
            assert result["passed"]
        assert result["progress"]["unlocked"]["check"]

        with pytest.raises(ProgressionError, match="previous checkpoint"):
            submit_checkpoint_answer(db, learner.id, module.id, lesson.id, 1, 0)
        questions = result["progress"]["parts"]["checkpoints"]
        for question_idx, question in enumerate(questions):
            answer = submit_checkpoint_answer(
                db,
                learner.id,
                module.id,
                lesson.id,
                question_idx,
                question.correct_index,
            )
            assert answer["passed"]

        assert mark_lesson_complete(
            db, learner.id, module.id, lesson.id, len(module.lessons)
        )
        assert lesson_access(db, learner.id, module.id, next_lesson.id)["accessible"]

        final = get_lesson_progress(db, learner.id, module.id, lesson.id)
        assert final["certified"]
        assert final["activity"].notes == "keep this note"
        assert final["activity"].experiment_code == "print('ok')"

        db.delete(user)
        db.commit()


def test_certification_rejects_navigation_only_state():
    init_db()
    with get_db() as db:
        user, learner = _learner(db)
        lesson = get_module(1).lessons[0]
        activity = get_lesson_progress(db, learner.id, 1, lesson.id)["activity"]
        update_lesson_activity(
            db,
            activity.id,
            stage="check",
            reading_section=4,
            experiment_attempted=True,
        )
        assert not mark_lesson_complete(db, learner.id, 1, lesson.id, len(get_module(1).lessons))
        assert not get_lesson_progress(db, learner.id, 1, lesson.id)["certified"]
        db.delete(user)
        db.commit()
