"""
Pip Learn 2.0 - Centralized Navigation Service
Provides single authoritative navigation routing, deterministic resume policy,
canonical lesson resolution, and authenticated logout actions.
"""
from typing import Optional, Tuple
from urllib.parse import quote
from nicegui import ui
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import (
    LessonActivity,
    LessonCompletion,
    QuizAttempt,
    ProjectSubmission,
    ModuleProgress,
)
from app.database.crud import ACTIVE_CURRICULUM_VERSION
from app.curriculum.loader import get_all_modules, get_module
from app.auth.service import (
    get_current_user_and_learner,
    get_current_session_token,
    invalidate_session,
    clear_user_session_storage,
)
from app.auth.guards import is_safe_redirect_url


STAGES = ("read", "watch", "experiment", "practice", "check")


# ========================================================
# Core Navigation Methods
# ========================================================

def go_to_home():
    """Navigate to public home screen."""
    ui.navigate.to("/")


def go_to_login(redirect_path: Optional[str] = None):
    """Navigate to login, preserving safe redirect destination."""
    if redirect_path and is_safe_redirect_url(redirect_path):
        ui.navigate.to(f"/login?redirect={quote(redirect_path, safe='')}")
    else:
        ui.navigate.to("/login")


def go_to_register(redirect_path: Optional[str] = None):
    """Navigate to register page."""
    if redirect_path and is_safe_redirect_url(redirect_path):
        ui.navigate.to(f"/register?redirect={quote(redirect_path, safe='')}")
    else:
        ui.navigate.to("/register")


def go_to_setup():
    """Navigate to learner onboarding/setup."""
    ui.navigate.to("/setup")


def go_to_dashboard():
    """Navigate to Study Space Dashboard (enforces auth)."""
    with get_db() as db:
        auth = get_current_user_and_learner(db)
        if not auth:
            go_to_login(redirect_path="/dashboard")
            return
    ui.navigate.to("/dashboard")


def go_to_curriculum():
    """Navigate to curriculum explorer (enforces auth)."""
    with get_db() as db:
        auth = get_current_user_and_learner(db)
        if not auth:
            go_to_login(redirect_path="/curriculum")
            return
    ui.navigate.to("/curriculum")


def go_to_rewards():
    """Navigate to the public graduate rewards preview."""
    ui.navigate.to("/rewards")


def open_module(module_id: int):
    """Navigate to specific module overview (enforces auth)."""
    with get_db() as db:
        auth = get_current_user_and_learner(db)
        if not auth:
            go_to_login(redirect_path=f"/module/{module_id}")
            return
    ui.navigate.to(f"/module/{module_id}")


def open_lesson(
    module_id: int,
    lesson_id: str,
    stage: Optional[str] = None,
    *,
    resume: bool = False,
):
    """
    Open a lesson through the canonical access gate.

    Ordinary opens always use the clean lesson URL and therefore begin at
    Read section 1. Only the explicit Continue Learning path sets ``resume``;
    even then the workspace derives the destination from verified evidence.
    """
    valid_stages = {"read", "watch", "experiment", "practice", "check"}
    target = f"/module/{module_id}/lesson/{lesson_id}"
    if resume:
        target += "?resume=1"
    with get_db() as db:
        auth = get_current_user_and_learner(db)
        if not auth:
            go_to_login(redirect_path=target)
            return
        _, learner = auth
        from app.learning.progression import lesson_access
        access = lesson_access(db, learner.id, module_id, lesson_id)
        if not access.get("accessible"):
            ui.notify(access.get("reason") or "This lesson is still locked.", color="warning")
            prerequisite = access.get("prerequisite")
            if prerequisite:
                ui.navigate.to(
                    f"/module/{prerequisite['module_id']}/lesson/{prerequisite['lesson_id']}"
                )
            return
    ui.navigate.to(target)


def open_practice(module_id: int = 1):
    """Navigate to practice laboratory."""
    with get_db() as db:
        auth = get_current_user_and_learner(db)
        if not auth:
            go_to_login(redirect_path=f"/practice?module={module_id}")
            return
    ui.navigate.to(f"/practice?module={module_id}")


def open_quiz(module_id: int):
    """Navigate to module assessment quiz."""
    with get_db() as db:
        auth = get_current_user_and_learner(db)
        if not auth:
            go_to_login(redirect_path=f"/module/{module_id}/quiz")
            return
    ui.navigate.to(f"/module/{module_id}/quiz")


def open_projects(module_id: int = 1):
    """Navigate to practical project workshop."""
    with get_db() as db:
        auth = get_current_user_and_learner(db)
        if not auth:
            go_to_login(redirect_path=f"/projects?module={module_id}")
            return
    ui.navigate.to(f"/projects?module={module_id}")


def open_achievements():
    """Navigate to achievements screen."""
    with get_db() as db:
        auth = get_current_user_and_learner(db)
        if not auth:
            go_to_login(redirect_path="/achievements")
            return
    ui.navigate.to("/achievements")


def open_report():
    """Navigate to academic report."""
    with get_db() as db:
        auth = get_current_user_and_learner(db)
        if not auth:
            go_to_login(redirect_path="/report")
            return
    ui.navigate.to("/report")


def open_settings():
    """Navigate to profile & settings."""
    with get_db() as db:
        auth = get_current_user_and_learner(db)
        if not auth:
            go_to_login(redirect_path="/settings")
            return
    ui.navigate.to("/settings")


# ========================================================
# Phase 6 & Phase 7 Authoritative Resume Policy
# ========================================================

def resolve_resume_destination(db: Session, learner_id: int) -> dict:
    """
    Canonical, deterministic progress resolution for a learner.
    Determines exactly where the learner resumes based on durable SQLite state:
    - If overall course completed: route to /report
    - If latest active lesson is incomplete: resume at the exact saved stage & in-stage position
    - If latest active lesson was completed: advance to the first incomplete lesson in syllabus order at Read, section 0
    - If fresh learner: start at Module 1, Lesson 1, Read, section 0
    """
    all_modules = get_all_modules()

    # 1. Course completion check (all 8 modules completed)
    completed_modules = db.query(ModuleProgress).filter(
        ModuleProgress.learner_id == learner_id,
        ModuleProgress.curriculum_version == ACTIVE_CURRICULUM_VERSION,
        ModuleProgress.status == "completed"
    ).count()
    if completed_modules >= 8:
        return {
            "module_id": -1,
            "lesson_id": "completed",
            "stage": "report",
            "reading_section": 0,
            "challenge_idx": 0,
            "checkpoint_idx": 0,
            "route": "/report",
            "is_completed": True
        }

    # 2. Get set of completed lesson IDs
    completions = db.query(LessonCompletion.lesson_id).filter(
        LessonCompletion.learner_id == learner_id,
        LessonCompletion.curriculum_version == ACTIVE_CURRICULUM_VERSION,
    ).all()
    completed_ids = {c[0] for c in completions}

    from app.learning.progression import get_lesson_progress, lesson_access

    def destination(module_id: int, lesson_id: str) -> dict:
        progress = get_lesson_progress(db, learner_id, module_id, lesson_id)
        return {
            "module_id": module_id,
            "lesson_id": lesson_id,
            "stage": progress["resume_stage"],
            "reading_section": progress["resume_reading_section"],
            "challenge_idx": progress["resume_challenge_idx"],
            "checkpoint_idx": progress["resume_checkpoint_idx"],
            "route": f"/module/{module_id}/lesson/{lesson_id}?resume=1",
            "is_completed": progress["certified"],
        }

    # 3. Check most recent activity in SQLite. Navigation history chooses the
    # lesson only; verified evidence chooses the actual resumable position.
    latest_activity = db.query(LessonActivity).filter(
        LessonActivity.learner_id == learner_id,
        LessonActivity.curriculum_version == ACTIVE_CURRICULUM_VERSION,
    ).order_by(LessonActivity.updated_at.desc()).first()

    # If the learner has an active, unfinished lesson
    if latest_activity and latest_activity.lesson_id not in completed_ids:
        access = lesson_access(
            db, learner_id, latest_activity.module_id, latest_activity.lesson_id
        )
        if access.get("accessible"):
            return destination(latest_activity.module_id, latest_activity.lesson_id)

    # 4. If latest activity was finished or no activity: advance to first incomplete lesson in syllabus order
    for mod in all_modules:
        for les in mod.lessons:
            if les.id not in completed_ids:
                if lesson_access(db, learner_id, mod.id, les.id).get("accessible"):
                    return destination(mod.id, les.id)

    # 5. Default fallback: Module 1, Lesson 1, Read
    first_mod = all_modules[0]
    first_les = first_mod.lessons[0]
    return {
        "module_id": first_mod.id,
        "lesson_id": first_les.id,
        "stage": "read",
        "reading_section": 0,
        "challenge_idx": 0,
        "checkpoint_idx": 0,
        "route": f"/module/{first_mod.id}/lesson/{first_les.id}?resume=1",
        "is_completed": False
    }


def resolve_resume_target(db: Session, learner_id: int) -> Tuple[int, str, str]:
    """Compatibility tuple wrapper returning (module_id, lesson_id, stage)."""
    dest = resolve_resume_destination(db, learner_id)
    return dest["module_id"], dest["lesson_id"], dest["stage"]


def resume_learning(learner_id: Optional[int] = None):
    """
    Authoritative Continue Learning action:
    - If unauthenticated -> login
    - If authenticated -> restore latest valid unfinished lesson & stage,
      or next incomplete lesson, or report if complete.
    """
    with get_db() as db:
        auth = get_current_user_and_learner(db)
        if not auth:
            go_to_login(redirect_path="/dashboard")
            return

        user, learner = auth
        actual_learner_id = learner.id if learner else learner_id
        if not actual_learner_id:
            go_to_login()
            return

        m_id, l_id, stage = resolve_resume_target(db, actual_learner_id)
        if m_id == -1:
            ui.navigate.to("/report")
            return
        open_lesson(m_id, l_id, stage, resume=True)


def start_learning():
    """
    Authoritative Start Learning action:
    - If unauthenticated: redirect to login/register preserving /start.
    - If authenticated and no lessons started: open Module 1, Lesson 1, Read.
    - If authenticated with progress: resume learning.
    """
    with get_db() as db:
        auth = get_current_user_and_learner(db)
        if not auth:
            go_to_login(redirect_path="/start")
            return

        user, learner = auth
        has_completions = db.query(LessonCompletion).filter(
            LessonCompletion.learner_id == learner.id,
            LessonCompletion.curriculum_version == ACTIVE_CURRICULUM_VERSION,
        ).count() > 0

        has_activities = db.query(LessonActivity).filter(
            LessonActivity.learner_id == learner.id,
            LessonActivity.curriculum_version == ACTIVE_CURRICULUM_VERSION,
        ).count() > 0

        if not has_completions and not has_activities:
            first = get_all_modules()[0].lessons[0]
            open_lesson(1, first.id, "read")
        else:
            resume_learning(learner.id)


def logout():
    """
    Authoritative Logout action:
    - Invalidate database session
    - Clear client session storage
    - Redirect to public Home
    """
    with get_db() as db:
        token = get_current_session_token()
        if token:
            invalidate_session(db, token)
        clear_user_session_storage()
    ui.navigate.to("/")
