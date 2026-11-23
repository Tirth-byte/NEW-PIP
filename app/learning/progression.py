"""Authoritative, evidence-based lesson progression.

All lesson UI and navigation code asks this module what is accessible.  Merely
viewing content or changing navigation history never grants completion.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from sqlalchemy.orm import Session

from app.curriculum.challenges import get_lesson_challenges
from app.curriculum.checkpoints import get_lesson_checkpoints
from app.curriculum.loader import get_all_modules, get_lesson, get_module
from app.curriculum.sections import get_lesson_reading_sections
from app.curriculum.videos import get_lesson_video
from app.database.crud import ACTIVE_CURRICULUM_VERSION, get_lesson_activity, update_lesson_activity
from app.database.models import LessonActivity, LessonCompletion


STAGES = ("read", "watch", "experiment", "practice", "check")


class ProgressionError(ValueError):
    """Raised when a learner attempts an activity before its prerequisite."""


def _json_dict(raw: str) -> Dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _reading_completed(activity: LessonActivity) -> set[int]:
    try:
        value = json.loads(activity.reading_completed_json or "[]")
    except (TypeError, ValueError):
        return set()
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, int) and item >= 0}


def _lesson_parts(module_id: int, lesson_id: str) -> Dict[str, Any]:
    module = get_module(module_id)
    lesson = get_lesson(module_id, lesson_id)
    if not module or not lesson:
        raise ProgressionError("The requested lesson does not exist.")
    sections = get_lesson_reading_sections(module, lesson)
    challenges = get_lesson_challenges(
        lesson.id, lesson.practice_tasks or module.practice_exercises
    )
    checkpoints = (
        lesson.checkpoint_questions
        or get_lesson_checkpoints(lesson.id, lesson.mini_checkpoint)
    )
    return {
        "module": module,
        "lesson": lesson,
        "sections": sections,
        "video": get_lesson_video(lesson.id),
        "challenges": challenges,
        "checkpoints": checkpoints,
    }


def lesson_access(
    db: Session, learner_id: int, module_id: int, lesson_id: str
) -> Dict[str, Any]:
    """Return whether the lesson itself is available in syllabus order."""
    ordered = [
        (module.id, lesson.id, lesson.title)
        for module in get_all_modules()
        for lesson in module.lessons
    ]
    try:
        index = next(
            i for i, item in enumerate(ordered)
            if item[0] == module_id and item[1] == lesson_id
        )
    except StopIteration:
        return {"accessible": False, "reason": "The requested lesson does not exist."}

    completed = {
        (row.module_id, row.lesson_id)
        for row in db.query(LessonCompletion).filter(
            LessonCompletion.learner_id == learner_id,
            LessonCompletion.curriculum_version == ACTIVE_CURRICULUM_VERSION,
        ).all()
    }
    if (module_id, lesson_id) in completed or index == 0:
        return {"accessible": True, "prerequisite": None}
    previous = ordered[index - 1]
    accessible = (previous[0], previous[1]) in completed
    return {
        "accessible": accessible,
        "prerequisite": {
            "module_id": previous[0],
            "lesson_id": previous[1],
            "title": previous[2],
        },
        "reason": None if accessible else (
            f"Complete “{previous[2]}” before starting this lesson."
        ),
    }


def get_lesson_progress(
    db: Session, learner_id: int, module_id: int, lesson_id: str
) -> Dict[str, Any]:
    """Build the canonical completion and unlock snapshot for one lesson."""
    parts = _lesson_parts(module_id, lesson_id)
    activity = get_lesson_activity(db, learner_id, module_id, lesson_id)
    completion = db.query(LessonCompletion).filter(
        LessonCompletion.learner_id == learner_id,
        LessonCompletion.module_id == module_id,
        LessonCompletion.lesson_id == lesson_id,
        LessonCompletion.curriculum_version == ACTIVE_CURRICULUM_VERSION,
    ).first()
    certified = completion is not None

    section_count = len(parts["sections"])
    reading_done = set(range(section_count)) if certified else _reading_completed(activity)
    reading_complete = section_count > 0 and all(i in reading_done for i in range(section_count))
    video_complete = certified or parts["video"] is None or activity.video_status == "completed"
    experiment_complete = certified or bool(activity.experiment_passed)

    practice = _json_dict(activity.practice_state_json)
    challenge_ids = [challenge.id for challenge in parts["challenges"]]
    practice_complete = certified or (
        bool(challenge_ids)
        and all(practice.get(challenge_id, {}).get("passed", False) for challenge_id in challenge_ids)
    )

    checkpoint = _json_dict(activity.checkpoint_state_json)
    checkpoint_count = len(parts["checkpoints"])
    check_complete = certified or (
        checkpoint_count > 0
        and all(checkpoint.get(f"q_{i}", {}).get("passed", False) for i in range(checkpoint_count))
    )

    complete = {
        "read": reading_complete,
        "watch": video_complete,
        "experiment": experiment_complete,
        "practice": practice_complete,
        "check": check_complete,
    }
    unlocked = {
        "read": True,
        "watch": reading_complete,
        "experiment": reading_complete and video_complete,
        "practice": reading_complete and video_complete and experiment_complete,
        "check": reading_complete and video_complete and experiment_complete and practice_complete,
    }
    if certified:
        unlocked = {stage: True for stage in STAGES}

    resume_stage = "check" if not certified and all(complete.values()) else "read"
    for candidate in STAGES:
        if not complete[candidate]:
            resume_stage = candidate
            break
    first_incomplete_section = next(
        (i for i in range(section_count) if i not in reading_done), 0
    )
    first_unpassed_challenge = next(
        (i for i, cid in enumerate(challenge_ids) if not practice.get(cid, {}).get("passed", False)),
        max(0, len(challenge_ids) - 1),
    )
    first_unpassed_checkpoint = next(
        (i for i in range(checkpoint_count) if not checkpoint.get(f"q_{i}", {}).get("passed", False)),
        max(0, checkpoint_count - 1),
    )
    return {
        "activity": activity,
        "parts": parts,
        "certified": certified,
        "complete": complete,
        "unlocked": unlocked,
        "reading_completed": reading_done,
        "practice": practice,
        "checkpoint": checkpoint,
        "resume_stage": "read" if certified else resume_stage,
        "resume_reading_section": 0 if certified else first_incomplete_section,
        "resume_challenge_idx": first_unpassed_challenge,
        "resume_checkpoint_idx": first_unpassed_checkpoint,
    }


def require_stage(progress: Dict[str, Any], stage: str) -> None:
    if stage not in STAGES:
        raise ProgressionError("That learning stage is not valid.")
    if progress["unlocked"][stage]:
        return
    prior = STAGES[STAGES.index(stage) - 1]
    labels = {
        "read": "all reading sections",
        "watch": "the video activity",
        "experiment": "the coding experiment",
        "practice": "all practice challenges",
    }
    raise ProgressionError(f"Complete {labels[prior]} before opening {stage.title()}.")


def complete_reading_section(
    db: Session, learner_id: int, module_id: int, lesson_id: str, section_idx: int
) -> Dict[str, Any]:
    progress = get_lesson_progress(db, learner_id, module_id, lesson_id)
    section_count = len(progress["parts"]["sections"])
    if section_idx < 0 or section_idx >= section_count:
        raise ProgressionError("That reading section does not exist.")
    done = progress["reading_completed"]
    if section_idx > 0 and section_idx - 1 not in done:
        raise ProgressionError("Complete the previous reading section first.")
    done.add(section_idx)
    update_lesson_activity(
        db,
        progress["activity"].id,
        reading_section=min(section_idx + 1, section_count - 1),
        reading_completed_json=json.dumps(sorted(done)),
        stage="read",
    )
    return get_lesson_progress(db, learner_id, module_id, lesson_id)


def mark_video_started(db: Session, learner_id: int, module_id: int, lesson_id: str) -> None:
    progress = get_lesson_progress(db, learner_id, module_id, lesson_id)
    require_stage(progress, "watch")
    if progress["activity"].video_status != "completed":
        update_lesson_activity(db, progress["activity"].id, video_status="started", stage="watch")


def complete_video(db: Session, learner_id: int, module_id: int, lesson_id: str) -> Dict[str, Any]:
    progress = get_lesson_progress(db, learner_id, module_id, lesson_id)
    require_stage(progress, "watch")
    if progress["parts"]["video"] is not None and progress["activity"].video_status not in {"started", "completed"}:
        raise ProgressionError("Start the lesson video before marking it complete.")
    update_lesson_activity(db, progress["activity"].id, video_status="completed", stage="watch")
    return get_lesson_progress(db, learner_id, module_id, lesson_id)


def run_experiment(
    db: Session,
    learner_id: int,
    module_id: int,
    lesson_id: str,
    code: str,
) -> Dict[str, Any]:
    """Execute the experiment server-side and record success monotonically."""
    progress = get_lesson_progress(db, learner_id, module_id, lesson_id)
    require_stage(progress, "experiment")
    from app.execution.runner import run_python_code

    result = run_python_code(code)
    update_lesson_activity(
        db,
        progress["activity"].id,
        stage="experiment",
        experiment_code=code,
        experiment_attempted=True,
        experiment_passed=bool(result["success"]) or bool(progress["activity"].experiment_passed),
    )
    return {
        "execution": result,
        "progress": get_lesson_progress(db, learner_id, module_id, lesson_id),
    }


def submit_practice_solution(
    db: Session,
    learner_id: int,
    module_id: int,
    lesson_id: str,
    challenge_idx: int,
    code: str,
) -> Dict[str, Any]:
    """Evaluate and persist a challenge; callers cannot assert their own pass."""
    progress = get_lesson_progress(db, learner_id, module_id, lesson_id)
    require_stage(progress, "practice")
    challenges = progress["parts"]["challenges"]
    if challenge_idx < 0 or challenge_idx >= len(challenges):
        raise ProgressionError("That practice challenge does not exist.")
    if challenge_idx > 0:
        previous_id = challenges[challenge_idx - 1].id
        if not progress["practice"].get(previous_id, {}).get("passed", False):
            raise ProgressionError("Pass the previous challenge before opening this one.")

    from app.execution.evaluator import evaluate_exercise
    from app.database.crud import record_practice_attempt

    challenge = challenges[challenge_idx]
    result = evaluate_exercise(code, challenge.test_cases, challenge.expected_substrings)
    state = progress["practice"]
    was_passed = bool(state.get(challenge.id, {}).get("passed", False))
    state[challenge.id] = {"code": code, "passed": was_passed or bool(result["passed"])}
    update_lesson_activity(
        db,
        progress["activity"].id,
        stage="practice",
        practice_state_json=json.dumps(state),
    )
    record_practice_attempt(
        db, learner_id, module_id, challenge.id, bool(result["passed"]), code, result["message"]
    )
    result["progress"] = get_lesson_progress(db, learner_id, module_id, lesson_id)
    return result


def submit_checkpoint_answer(
    db: Session,
    learner_id: int,
    module_id: int,
    lesson_id: str,
    question_idx: int,
    selected_index: int,
) -> Dict[str, Any]:
    """Validate an answer against curriculum data and persist verified evidence."""
    progress = get_lesson_progress(db, learner_id, module_id, lesson_id)
    require_stage(progress, "check")
    questions = progress["parts"]["checkpoints"]
    if question_idx < 0 or question_idx >= len(questions):
        raise ProgressionError("That checkpoint question does not exist.")
    if question_idx > 0 and not progress["checkpoint"].get(f"q_{question_idx - 1}", {}).get("passed", False):
        raise ProgressionError("Answer the previous checkpoint correctly first.")
    question = questions[question_idx]
    if selected_index < 0 or selected_index >= len(question.options):
        raise ProgressionError("Select one of the available answers.")
    key = f"q_{question_idx}"
    state = progress["checkpoint"]
    previous = state.get(key, {})
    passed = selected_index == question.correct_index
    state[key] = {
        "choice_index": selected_index,
        "choice_text": question.options[selected_index],
        "passed": bool(previous.get("passed", False)) or passed,
        "attempts": int(previous.get("attempts", 0)) + 1,
    }
    update_lesson_activity(
        db,
        progress["activity"].id,
        stage="check",
        checkpoint_state_json=json.dumps(state),
    )
    return {
        "passed": passed,
        "attempts": state[key]["attempts"],
        "progress": get_lesson_progress(db, learner_id, module_id, lesson_id),
    }


def can_certify(progress: Dict[str, Any]) -> bool:
    return all(progress["complete"][stage] for stage in STAGES)
