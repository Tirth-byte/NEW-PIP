"""
Production Lesson Workspace: Read → Watch → Experiment → Practice → Check.
Authoritative Pip Learn implementation adhering to:
- Unified, stable learning workspace
- Five-stage linear educational journey
- Real embedded Corey Schafer YouTube videos with fallback
- Two-column balanced experiment workbench with high-contrast editor
- Three meaningful coding challenges per lesson with real tests
- Focused, one-question-at-a-time checkpoint assessment with retry behavior
- Complete state persistence to SQLite database
"""
import json

from nicegui import ui

from app.components.layout import page_shell
from app.components.video_player import render_video_player
from app.curriculum.challenges import get_lesson_challenges
from app.curriculum.checkpoints import get_lesson_checkpoints
from app.curriculum.loader import get_lesson, get_module
from app.curriculum.videos import get_lesson_video
from app.database.connection import get_db
from app.database.crud import (
    get_lesson_activity,
    mark_lesson_complete,
    update_lesson_activity,
)
from app.learning.progression import (
    ProgressionError,
    complete_reading_section,
    complete_video,
    get_lesson_progress,
    lesson_access,
    mark_video_started,
    run_experiment,
    require_stage,
    submit_checkpoint_answer,
    submit_practice_solution,
)
from app.auth.guards import require_auth
import app.navigation.nav as nav


STAGES = ["read", "watch", "experiment", "practice", "check"]


from app.curriculum.sections import get_lesson_reading_sections

_reading_sections = get_lesson_reading_sections


def render_lesson_screen(
    module_id: int, lesson_id: str, stage: str = None, resume: bool = False
):
    with get_db() as db:
        auth = require_auth(db, active_route=f"/module/{module_id}/lesson/{lesson_id}")
        if not auth:
            return
        user, learner = auth
        learner_id = learner.id

    module = get_module(module_id)
    lesson = get_lesson(module_id, lesson_id)

    with page_shell(active_route="/curriculum", compact=True, show_footer=False):
        if not module or not lesson:
            with ui.column().classes("w-full max-w-xl mx-auto py-16 text-center gap-4"):
                ui.label("Lesson Not Found").classes("font-serif text-3xl")
                ui.label("The requested lesson does not exist in the curriculum.").classes("text-sm text-[#5E5A55]")
                ui.button("← Return to Curriculum", on_click=nav.go_to_curriculum).classes("btn-blue mx-auto")
            return

        with get_db() as db:
            access = lesson_access(db, learner_id, module.id, lesson.id)
        if not access.get("accessible"):
            prerequisite = access.get("prerequisite")
            with ui.column().classes("w-full max-w-xl mx-auto py-16 text-center items-center gap-4"):
                ui.icon("lock", size="3rem", color="#8C857D")
                ui.label("Lesson Locked").classes("font-serif text-3xl")
                ui.label(access.get("reason") or "Complete the prerequisite lesson first.").classes(
                    "text-sm text-[#5E5A55]"
                )
                if prerequisite:
                    ui.button(
                        f"Open prerequisite: {prerequisite['title']}",
                        on_click=lambda: nav.open_lesson(
                            prerequisite["module_id"], prerequisite["lesson_id"]
                        ),
                    ).classes("btn-blue")
            return

        lesson_ids = [item.id for item in module.lessons]
        lesson_index = lesson_ids.index(lesson.id)
        previous_id = lesson_ids[lesson_index - 1] if lesson_index > 0 else None
        next_id = lesson_ids[lesson_index + 1] if lesson_index + 1 < len(lesson_ids) else None

        # Preload curriculum components
        sections = _reading_sections(module, lesson)
        video_info = get_lesson_video(lesson.id)
        challenges = get_lesson_challenges(lesson.id, lesson.practice_tasks or module.practice_exercises)
        checkpoints = lesson.checkpoint_questions or get_lesson_checkpoints(lesson.id, lesson.mini_checkpoint)

        # Fetch persisted activity and completion from SQLite
        with get_db() as db:
            activity = get_lesson_activity(db, learner_id, module.id, lesson.id)
            activity_id = activity.id

            progress = get_lesson_progress(db, learner_id, module.id, lesson.id)

            # Normal entry and refresh are deterministic: Read, section 1.
            # Explicit Continue Learning resumes the first incomplete activity;
            # arbitrary URL stage values never override prerequisite checks.
            init_stage = progress["resume_stage"] if resume else "read"
            if resume and stage in STAGES and progress["unlocked"].get(stage, False):
                init_stage = stage

            saved_state = {
                "stage": init_stage,
                "reading_section": progress["resume_reading_section"] if resume else 0,
                "reading_completed": set(progress["reading_completed"]),
                "video_status": activity.video_status or "not_started",
                "notes": activity.notes or "",
                "experiment_code": activity.experiment_code or lesson.executable_code,
                "experiment_attempted": activity.experiment_attempted or False,
                "experiment_passed": activity.experiment_passed or False,
                "practice": dict(progress["practice"]),
                "checkpoint": dict(progress["checkpoint"]),
            }

        def persist_activity(**kwargs):
            """Persist lesson activity state to SQLite database."""
            with get_db() as db:
                update_lesson_activity(db, activity_id, **kwargs)

        # State containers
        current_read_idx = {"value": max(0, min(saved_state["reading_section"], len(sections) - 1))}

        # Active challenge points to the first unpassed challenge in practice
        first_unpassed_challenge_idx = 0
        for c_idx, ch in enumerate(challenges):
            if not saved_state["practice"].get(ch.id, {}).get("passed", False):
                first_unpassed_challenge_idx = c_idx
                break
        else:
            first_unpassed_challenge_idx = max(0, len(challenges) - 1)
        active_challenge_idx = {"value": first_unpassed_challenge_idx}

        # Active checkpoint points to the first unpassed question
        checkpoint_answers = dict(saved_state["checkpoint"])  # e.g. {"q_0": {"choice": 1, "passed": True}}
        first_unpassed_ckpt_idx = 0
        for q_idx in range(len(checkpoints)):
            if not checkpoint_answers.get(f"q_{q_idx}", {}).get("passed", False):
                first_unpassed_ckpt_idx = q_idx
                break
        else:
            first_unpassed_ckpt_idx = max(0, len(checkpoints) - 1)
        active_checkpoint_idx = {"value": first_unpassed_ckpt_idx}

        def current_progress():
            with get_db() as db:
                return get_lesson_progress(db, learner_id, module.id, lesson.id)

        def explain_locked(message: str):
            ui.notify(message, color="warning", position="top")

        # Main Workspace Container
        with ui.column().classes("lesson-shell"):

            # 1. Lesson Context Header Card
            with ui.row().classes("lesson-header-card w-full items-center justify-between gap-4 flex-wrap"):
                with ui.row().classes("items-center gap-3 min-w-0"):
                    ui.button(f"← {module.code}: {module.title}", on_click=lambda: nav.open_module(module.id)).props("flat dense").classes(
                        "text-xs text-[#396DAB] hover:underline font-semibold normal-case p-0"
                    )
                    ui.label("·").classes("text-xs text-[#8C857D]")
                    ui.label(f"LESSON {lesson_index + 1} OF {len(module.lessons)}").classes("editorial-eyebrow")
                    ui.label("—").classes("text-xs text-[#8C857D]")
                    ui.label(lesson.title).classes("font-serif text-2xl leading-none text-[#161616]")
                ui.label(lesson.subtitle).classes("hidden lg:block text-xs text-[#5E5A55] max-w-md truncate")

            # 2. Stage Navigation Tabs
            stage_tabs_list = [
                ("01", "read", "Read"),
                ("02", "watch", "Watch"),
                ("03", "experiment", "Experiment"),
                ("04", "practice", "Practice"),
                ("05", "check", "Check"),
            ]
            stage_tab_elements = {}

            with ui.tabs(value=saved_state["stage"]).props("dense no-caps align=justify").classes("lesson-tabs w-full") as tabs:
                for num, key, label in stage_tabs_list:
                    marker = "✓" if progress["complete"][key] else ("🔒" if not progress["unlocked"][key] else "")
                    stage_tab_elements[key] = ui.tab(
                        key, label=f"{num} · {label}{' · ' + marker if marker else ''}"
                    ).classes("stage-locked" if not progress["unlocked"][key] else "")

            def refresh_stage_tabs():
                snapshot = current_progress()
                for num, key, label in stage_tabs_list:
                    marker = "✓" if snapshot["complete"][key] else ("🔒" if not snapshot["unlocked"][key] else "")
                    stage_tab_elements[key].set_label(
                        f"{num} · {label}{' · ' + marker if marker else ''}"
                    )
                    if snapshot["unlocked"][key]:
                        stage_tab_elements[key].classes(remove="stage-locked")
                    else:
                        stage_tab_elements[key].classes(add="stage-locked")

            def advance_to_stage(target_stage: str):
                if target_stage not in STAGES or saved_state.get("stage") == target_stage:
                    return
                snapshot = current_progress()
                try:
                    require_stage(snapshot, target_stage)
                except ProgressionError as exc:
                    explain_locked(str(exc))
                    tabs.set_value(saved_state["stage"])
                    return
                saved_state["stage"] = target_stage
                tabs.set_value(target_stage)
                persist_activity(stage=target_stage)
                if target_stage != "watch":
                    ui.run_javascript(
                        "document.querySelectorAll('iframe.youtube-frame').forEach(function(f) {"
                        "  try { f.contentWindow.postMessage('{\"event\":\"command\",\"func\":\"pauseVideo\",\"args\":\"\"}', '*'); } catch(e) {}"
                        "});"
                    )
                render_lesson_navigation.refresh()

            def on_stage_change(event):
                if event.value in STAGES and saved_state.get("stage") != event.value:
                    snapshot = current_progress()
                    try:
                        require_stage(snapshot, event.value)
                    except ProgressionError as exc:
                        explain_locked(str(exc))
                        tabs.set_value(saved_state["stage"])
                        return
                    saved_state["stage"] = event.value
                    persist_activity(stage=event.value)
                    if event.value != "watch":
                        ui.run_javascript(
                            "document.querySelectorAll('iframe.youtube-frame').forEach(function(f) {"
                            "  try { f.contentWindow.postMessage('{\"event\":\"command\",\"func\":\"pauseVideo\",\"args\":\"\"}', '*'); } catch(e) {}"
                            "});"
                        )
                    render_lesson_navigation.refresh()

            tabs.on_value_change(on_stage_change)

            # 3. Tab Panels Container (Read, Watch, Experiment, Practice, Check)
            with ui.tab_panels(tabs, value=saved_state["stage"]).props("animated=false keep-alive").classes("lesson-panels w-full"):

                # =========================================================
                # STAGE 01: READ
                # =========================================================
                with ui.tab_panel(stage_tab_elements["read"]).classes("lesson-panel"):
                    @ui.refreshable
                    def render_reading_view():
                        pos = current_read_idx["value"]
                        title, eyebrow, body_md = sections[pos]

                        with ui.column().classes("reading-container"):
                            # Section Progress Tracker
                            with ui.row().classes("w-full items-center justify-between gap-2"):
                                ui.label(eyebrow).classes("editorial-eyebrow")
                                ui.label(f"SECTION {pos + 1} OF {len(sections)}").classes("text-xs font-mono text-[#8C857D]")

                            with ui.element("div").classes("reading-progress-track"):
                                ui.element("div").classes("reading-progress-fill").style(
                                    f"width: {((pos + 1) / len(sections)) * 100}%"
                                )

                            # Section Stepper Pills
                            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                                for s_idx, (s_title, _, _) in enumerate(sections):
                                    is_cur = s_idx == pos
                                    is_done = s_idx in saved_state["reading_completed"]
                                    is_unlocked = s_idx == 0 or (s_idx - 1) in saved_state["reading_completed"]
                                    marker = " ✓" if is_done else (" 🔒" if not is_unlocked else "")
                                    pill = ui.button(
                                        f"{s_idx + 1}. {s_title}{marker}",
                                        on_click=lambda idx=s_idx: jump_to_section(idx)
                                    ).props("flat dense").classes(
                                        f"reading-pill {'active' if is_cur else ''} {'passed' if is_done else ''} {'locked' if not is_unlocked else ''}"
                                    )

                            # Section Content Card
                            with ui.column().classes("workbench-card w-full py-6 px-7"):
                                ui.markdown(body_md).classes("lesson-prose w-full")

                            # Bottom Section Navigation Controls
                            with ui.row().classes("w-full items-center justify-between pt-2 pb-6"):
                                if pos > 0:
                                    ui.button("← Previous Section", on_click=lambda: step_section(-1)).props("outline").classes("btn-subtle")
                                else:
                                    ui.element("div")

                                section_done = pos in saved_state["reading_completed"]
                                if pos < len(sections) - 1:
                                    label = "Next Section →" if section_done else "Complete Section & Continue →"
                                    ui.button(label, on_click=lambda: complete_or_continue_section()).classes("btn-blue")
                                else:
                                    next_label = "Continue to Watch Stage →" if video_info else "Continue to Experiment Stage →"
                                    if section_done:
                                        ui.button(next_label, on_click=lambda: advance_to_stage("watch" if video_info else "experiment")).classes("btn-blue")
                                    else:
                                        ui.button("Complete Reading Stage →", on_click=lambda: complete_or_continue_section()).classes("btn-blue")

                    def step_section(delta: int):
                        new_pos = current_read_idx["value"] + delta
                        if 0 <= new_pos < len(sections):
                            current_read_idx["value"] = new_pos
                            persist_activity(reading_section=new_pos, stage="read")
                            render_reading_view.refresh()

                    def complete_or_continue_section():
                        pos = current_read_idx["value"]
                        if pos not in saved_state["reading_completed"]:
                            try:
                                with get_db() as db:
                                    snapshot = complete_reading_section(
                                        db, learner_id, module.id, lesson.id, pos
                                    )
                            except ProgressionError as exc:
                                explain_locked(str(exc))
                                return
                            saved_state["reading_completed"] = set(snapshot["reading_completed"])
                        if pos < len(sections) - 1:
                            current_read_idx["value"] = pos + 1
                            persist_activity(reading_section=pos + 1, stage="read")
                            render_reading_view.refresh()
                        else:
                            refresh_stage_tabs()
                            advance_to_stage("watch" if video_info else "experiment")
                        render_lesson_navigation.refresh()

                    def jump_to_section(idx: int):
                        unlocked = idx == 0 or (idx - 1) in saved_state["reading_completed"]
                        if 0 <= idx < len(sections) and unlocked:
                            current_read_idx["value"] = idx
                            persist_activity(reading_section=idx, stage="read")
                            render_reading_view.refresh()
                        elif 0 <= idx < len(sections):
                            explain_locked("Complete the previous reading section first.")

                    render_reading_view()

                # =========================================================
                # STAGE 02: WATCH
                # =========================================================
                with ui.tab_panel(stage_tab_elements["watch"]).classes("lesson-panel"):
                    with ui.row().classes("workspace-grid"):
                        # Video Player Column
                        with ui.column().classes("workspace-pane-left"):
                            with ui.column().classes("workbench-card w-full gap-3"):
                                ui.label("VIDEO TUTORIAL EMBED").classes("editorial-eyebrow")

                                status_label = None
                                video_complete_btn = None

                                def handle_playback_start():
                                    saved_state["video_status"] = "started"
                                    with get_db() as db:
                                        mark_video_started(db, learner_id, module.id, lesson.id)
                                    if status_label:
                                        status_label.set_text("Status: Video active in embedded YouTube player")
                                    if video_complete_btn:
                                        video_complete_btn.enable()

                                render_video_player(
                                    video_info=video_info,
                                    saved_video_status=saved_state["video_status"],
                                    on_playback_started=handle_playback_start,
                                    on_status_change=lambda msg: status_label.set_text(msg) if status_label else None,
                                )

                                with ui.row().classes("w-full items-center justify-between text-xs pt-1"):
                                    status_label = ui.label(
                                        "Status: Ready to play" if saved_state["video_status"] == "not_started" else "Status: Playback initialized"
                                    ).classes("text-xs text-[#5E5A55]")
                                    with ui.row().classes("items-center gap-3"):
                                        if video_info:
                                            ui.label(f"Duration: {video_info.duration}").classes("font-mono text-[#8C857D]")
                                            ui.link(
                                                "Open on YouTube ↗",
                                                f"https://www.youtube.com/watch?v={video_info.video_id}",
                                                new_tab=True,
                                            ).classes("text-[#396DAB] hover:underline font-medium")

                                def finish_video_activity():
                                    try:
                                        with get_db() as db:
                                            snapshot = complete_video(
                                                db, learner_id, module.id, lesson.id
                                            )
                                    except ProgressionError as exc:
                                        explain_locked(str(exc))
                                        return
                                    saved_state["video_status"] = "completed"
                                    status_label.set_text("✓ Video activity completed")
                                    video_complete_btn.disable()
                                    video_complete_btn.set_text("✓ Video Completed")
                                    refresh_stage_tabs()
                                    render_lesson_navigation.refresh()

                                if video_info:
                                    video_complete_btn = ui.button(
                                        "✓ I Finished the Video",
                                        on_click=finish_video_activity,
                                    ).classes("btn-blue text-xs")
                                    if saved_state["video_status"] == "completed":
                                        video_complete_btn.set_text("✓ Video Completed")
                                        video_complete_btn.disable()
                                    elif saved_state["video_status"] != "started":
                                        video_complete_btn.disable()

                        # Video Study Notes Column
                        with ui.column().classes("workspace-pane-right"):
                            with ui.column().classes("workbench-card w-full gap-4"):
                                with ui.column().classes("gap-1"):
                                    ui.label("STUDY COMPANION & NOTES").classes("editorial-eyebrow")
                                    ui.label(video_info.title if video_info else "Continue with Hands-on Experiment").classes("font-serif text-2xl text-[#161616]")
                                    ui.label(f"Creator: {video_info.instructor}" if video_info else "Self-Paced Guided Flow").classes("text-xs font-semibold text-[#396DAB]")

                                if video_info:
                                    ui.label(video_info.relevance).classes("text-sm text-[#5E5A55] leading-relaxed")
                                    with ui.column().classes("gap-1 bg-[#E9F1F9] p-3 rounded-md border-l-4 border-[#4F83BC]"):
                                        ui.label("What to observe in the video:").classes("text-xs font-semibold text-[#161616]")
                                        ui.markdown("- Notice how syntax is entered and executed directly.\n- Observe the terminal output and common mistakes demonstrated.\n- Compare the video examples with your written lesson code.").classes("text-xs text-[#5E5A55]")

                                with ui.row().classes("w-full items-center justify-between mt-2"):
                                    ui.label("Your Study Notes").classes("text-xs font-semibold text-[#161616]")
                                    save_indicator = ui.label("Autosaved to SQLite").classes("text-[11px] font-mono text-[#8C857D]")

                                notes_input = ui.textarea(
                                    placeholder="Take notes on key ideas, syntax tricks, or questions...",
                                    value=saved_state["notes"],
                                ).props("outlined rows=6 spellcheck=false").classes("w-full text-sm font-sans")

                                def on_notes_change(e):
                                    val = e.value if hasattr(e, "value") else str(e)
                                    saved_state["notes"] = val
                                    persist_activity(notes=val)
                                    save_indicator.set_text("✓ Notes saved")

                                notes_input.on_value_change(on_notes_change)

                # =========================================================
                # STAGE 03: EXPERIMENT
                # =========================================================
                with ui.tab_panel(stage_tab_elements["experiment"]).classes("lesson-panel"):
                    with ui.row().classes("workspace-grid"):
                        # Experiment Instructions
                        with ui.column().classes("workspace-pane-left"):
                            with ui.column().classes("workbench-card w-full gap-4"):
                                ui.label("GUIDED LIVE EXPERIMENT").classes("editorial-eyebrow")
                                experiment = lesson.experiment
                                ui.label(experiment.title if experiment else "Predict, Modify, Then Execute").classes("font-serif text-2xl text-[#161616]")
                                ui.label(
                                    experiment.prediction_prompt if experiment else "Modify values in the program to test your mental model. Before clicking Run, predict what the Python interpreter will print."
                                ).classes("text-sm text-[#5E5A55] leading-relaxed")

                                ui.label("Your Output Prediction:").classes("text-xs font-semibold text-[#161616]")
                                prediction_box = ui.input(
                                    placeholder="e.g. I predict line 2 will output...",
                                ).props("outlined dense").classes("w-full text-sm")

                                with ui.column().classes("bg-[#E9F1F9] border-l-4 border-[#4F83BC] p-4 rounded-r gap-1.5"):
                                    ui.label("Suggested Experiments to Try:").classes("font-semibold text-xs text-[#161616]")
                                    instructions = experiment.instructions if experiment else [
                                        "Predict the output", "Run unchanged code", "Observe the result",
                                        "Modify one value", "Run again and explain the difference",
                                    ]
                                    ui.markdown("\n".join(f"{i}. {item}" for i, item in enumerate(instructions, 1))).classes("text-xs text-[#5E5A55]")
                                if experiment:
                                    ui.label(f"Reference behavior: {experiment.expected_output}").classes("text-xs font-mono text-[#5E5A55] whitespace-pre-wrap")


                        # Code Editor & Terminal Pane
                        with ui.column().classes("workspace-pane-right"):
                            with ui.column().classes("workbench-card w-full gap-3"):
                                with ui.row().classes("w-full items-center justify-between"):
                                    ui.label("EXPERIMENT.PY").classes("terminal-header")
                                    with ui.row().classes("items-center gap-2"):
                                        reset_exp_btn = ui.button("Reset Code").props("outline dense").classes("btn-subtle text-xs")
                                        run_exp_btn = ui.button("Run Code ▶").classes("btn-blue text-xs")

                                exp_editor = ui.textarea(
                                    value=saved_state["experiment_code"]
                                ).props("outlined rows=11 spellcheck=false").classes("python-editor w-full")

                                def on_exp_code_change(e):
                                    saved_state["experiment_code"] = e.value
                                    persist_activity(experiment_code=e.value)

                                exp_editor.on_value_change(on_exp_code_change)

                                reset_exp_btn.on_click(lambda: exp_editor.set_value(lesson.experiment.starter_code if lesson.experiment else lesson.executable_code))

                                ui.label("TERMINAL OUTPUT (ISOLATED EXECUTION)").classes("terminal-header mt-1")
                                exp_output = ui.label("Click 'Run Code ▶' to execute this script in an isolated Python subprocess.").classes(
                                    "code-output w-full whitespace-pre-wrap"
                                )
                                exp_diagnostic = ui.label("").classes("text-xs text-[#9D3A3A] hidden")

                                def execute_experiment():
                                    if not (prediction_box.value or "").strip():
                                        ui.notify("Write your output prediction before running the experiment.", color="warning")
                                        return
                                    run_exp_btn.disable()
                                    run_exp_btn.set_text("Running…")
                                    try:
                                        with get_db() as db:
                                            experiment_result = run_experiment(
                                                db,
                                                learner_id,
                                                module.id,
                                                lesson.id,
                                                exp_editor.value,
                                            )
                                    except ProgressionError as exc:
                                        run_exp_btn.enable()
                                        run_exp_btn.set_text("Run Code ▶")
                                        explain_locked(str(exc))
                                        return
                                    res = experiment_result["execution"]
                                    if res["success"]:
                                        exp_output.set_text(res["stdout"].strip() if res["stdout"].strip() else "(Execution completed with no output to stdout)")
                                        exp_output.classes(replace="code-output w-full whitespace-pre-wrap is-success")
                                        exp_diagnostic.set_visibility(False)
                                    else:
                                        exp_output.set_text(res["stderr"].strip())
                                        exp_output.classes(replace="code-output w-full whitespace-pre-wrap is-error")
                                        if res.get("explanation"):
                                            exp_diagnostic.set_text(f"Diagnostic Insight: {res['explanation']}")
                                            exp_diagnostic.set_visibility(True)

                                    snapshot = experiment_result["progress"]
                                    saved_state["experiment_attempted"] = True
                                    saved_state["experiment_passed"] = snapshot["complete"]["experiment"]
                                    if res["success"]:
                                        ui.notify("Experiment completed successfully. Practice is now unlocked.", color="positive")
                                        refresh_stage_tabs()
                                        render_lesson_navigation.refresh()
                                    run_exp_btn.enable()
                                    run_exp_btn.set_text("Run Code ▶")

                                run_exp_btn.on_click(execute_experiment)

                # =========================================================
                # STAGE 04: PRACTICE
                # =========================================================
                with ui.tab_panel(stage_tab_elements["practice"]).classes("lesson-panel"):
                    @ui.refreshable
                    def render_practice_view():
                        active_idx = active_challenge_idx["value"]
                        current_ex = challenges[active_idx]
                        current_ex_saved = saved_state["practice"].get(current_ex.id, {})

                        with ui.column().classes("w-full gap-4"):
                            # Challenge Stepper Selector (Separately Refreshable)
                            @ui.refreshable
                            def challenge_selector():
                                with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                                    for c_idx, ch in enumerate(challenges):
                                        is_active = c_idx == active_challenge_idx["value"]
                                        ch_state = saved_state["practice"].get(ch.id, {})
                                        has_passed = ch_state.get("passed", False)
                                        is_unlocked = c_idx == 0 or saved_state["practice"].get(
                                            challenges[c_idx - 1].id, {}
                                        ).get("passed", False)
                                        check_badge = " ✓" if has_passed else (" 🔒" if not is_unlocked else "")
                                        ui.button(
                                            f"Challenge {c_idx + 1}: {ch.difficulty}{check_badge}",
                                            on_click=lambda i=c_idx: switch_challenge(i)
                                        ).props("dense flat").classes(
                                            f"challenge-tab-btn {'active' if is_active else ''} {'passed' if has_passed else ''} {'locked' if not is_unlocked else ''}"
                                        )

                            challenge_selector()

                            with ui.row().classes("workspace-grid"):
                                # Left Column: Challenge Description & Hints
                                with ui.column().classes("workspace-pane-left"):
                                    with ui.column().classes("workbench-card w-full gap-3"):
                                        with ui.row().classes("items-center justify-between"):
                                            ui.label(f"{current_ex.difficulty.upper()} CHALLENGE").classes("editorial-eyebrow")
                                            if current_ex_saved.get("passed"):
                                                ui.label("✓ VERIFIED PASSED").classes("text-xs font-semibold text-[#2D6A4F]")

                                        ui.label(current_ex.title).classes("font-serif text-2xl text-[#161616]")
                                        ui.markdown(current_ex.problem_statement).classes("text-sm text-[#5E5A55] leading-relaxed")

                                        with ui.column().classes("gap-1 bg-[#EFEAE2] p-3 rounded"):
                                            ui.label("Expected Behavior & Output:").classes("text-xs font-semibold text-[#161616]")
                                            ui.label(current_ex.input_output_expectations).classes("text-xs font-mono text-[#5E5A55] whitespace-pre-wrap")

                                        if current_ex.hints:
                                            ui.label("Progressive Hints").classes("text-xs font-semibold text-[#161616] mt-1")
                                            for h_idx, hint_text in enumerate(current_ex.hints, 1):
                                                with ui.expansion(f"Hint {h_idx}").classes("w-full text-xs border border-[#E2DCD2] rounded"):
                                                    ui.label(hint_text).classes("p-3 text-xs text-[#5E5A55]")


                                # Right Column: Code Editor & Automated Test Evaluator
                                with ui.column().classes("workspace-pane-right"):
                                    with ui.column().classes("workbench-card w-full gap-3"):
                                        with ui.row().classes("w-full items-center justify-between"):
                                            ui.label("SOLUTION.PY").classes("terminal-header")
                                            with ui.row().classes("items-center gap-2"):
                                                reset_prac_btn = ui.button("Reset").props("outline dense").classes("btn-subtle text-xs")
                                                test_prac_btn = ui.button("Run Tests ▶").classes("btn-blue text-xs")

                                        starter = current_ex_saved.get("code", current_ex.starter_code)
                                        prac_editor = ui.textarea(value=starter).props("outlined rows=11 spellcheck=false").classes("python-editor w-full")

                                        def on_prac_code_change(e):
                                            saved_state["practice"].setdefault(current_ex.id, {})["code"] = e.value
                                            persist_activity(practice_state_json=json.dumps(saved_state["practice"]))

                                        prac_editor.on_value_change(on_prac_code_change)
                                        reset_prac_btn.on_click(lambda: prac_editor.set_value(current_ex.starter_code))

                                        ui.label("AUTOMATED TEST RESULTS").classes("terminal-header mt-1")
                                        results_container = ui.column().classes("w-full gap-2")

                                        with results_container:
                                            if current_ex_saved.get("passed"):
                                                ui.label("✓ All tests passed for this challenge.").classes("text-xs text-[#2D6A4F] font-semibold")
                                            else:
                                                ui.label("Click 'Run Tests ▶' to evaluate your solution against test assertions.").classes("text-xs text-[#5E5A55]")

                                        def execute_practice_tests():
                                            test_prac_btn.disable()
                                            test_prac_btn.set_text("Evaluating…")
                                            try:
                                                with get_db() as db:
                                                    eval_res = submit_practice_solution(
                                                        db,
                                                        learner_id,
                                                        module.id,
                                                        lesson.id,
                                                        active_idx,
                                                        prac_editor.value,
                                                    )
                                            except ProgressionError as exc:
                                                test_prac_btn.enable()
                                                test_prac_btn.set_text("Run Tests ▶")
                                                explain_locked(str(exc))
                                                return
                                            saved_state["practice"] = dict(eval_res["progress"]["practice"])

                                            results_container.clear()
                                            with results_container:
                                                passed_cases = sum(1 for c in eval_res.get("test_results", []) if c["passed"])
                                                total_cases = len(eval_res.get("test_results", [])) or 1

                                                if eval_res["passed"]:
                                                    with ui.column().classes("w-full bg-[#F0FDF4] border border-[#86EFAC] p-3 rounded gap-1"):
                                                        ui.label(f"✓ {passed_cases} of {total_cases} Tests Passed!").classes("font-semibold text-sm text-[#2D6A4F]")
                                                        ui.label(eval_res["message"]).classes("text-xs text-[#2D6A4F]")
                                                else:
                                                    with ui.column().classes("w-full bg-[#FEF2F2] border border-[#FECACA] p-3 rounded gap-1"):
                                                        ui.label(f"✗ Test Verification Failed ({passed_cases}/{total_cases} passed)").classes("font-semibold text-sm text-[#9D3A3A]")
                                                        ui.label(eval_res["message"]).classes("text-xs text-[#9D3A3A]")

                                                for t_row in eval_res.get("test_results", []):
                                                    icon = "✓" if t_row["passed"] else "✗"
                                                    color = "text-[#2D6A4F]" if t_row["passed"] else "text-[#9D3A3A]"
                                                    with ui.row().classes(f"items-center gap-2 text-xs {color}"):
                                                        ui.label(f"{icon} {t_row['description']}")
                                                    if t_row.get("error"):
                                                        ui.label(t_row["error"]).classes("text-[11px] font-mono text-[#9D3A3A] whitespace-pre-wrap ml-4")

                                            test_prac_btn.enable()
                                            test_prac_btn.set_text("Run Tests ▶")
                                            # Refresh challenge selector to display the checkmark
                                            challenge_selector.refresh()
                                            if eval_res["passed"]:
                                                refresh_stage_tabs()
                                                render_lesson_navigation.refresh()

                                        test_prac_btn.on_click(execute_practice_tests)

                    def switch_challenge(idx: int):
                        unlocked = idx == 0 or saved_state["practice"].get(
                            challenges[idx - 1].id, {}
                        ).get("passed", False)
                        if unlocked:
                            active_challenge_idx["value"] = idx
                            render_practice_view.refresh()
                        else:
                            explain_locked("Pass the previous challenge before opening this one.")

                    render_practice_view()

                # =========================================================
                # STAGE 05: CHECK (FOCUSED ONE-QUESTION ASSESSMENT)
                # =========================================================
                with ui.tab_panel(stage_tab_elements["check"]).classes("lesson-panel"):
                    @ui.refreshable
                    def render_check_view():
                        q_idx = active_checkpoint_idx["value"]
                        total_q = len(checkpoints)

                        # Check if learner has completed all checkpoint questions
                        questions_passed = total_q > 0 and all(
                            checkpoint_answers.get(f"q_{i}", {}).get("passed", False)
                            for i in range(total_q)
                        )
                        practice_passed = all(
                            saved_state["practice"].get(challenge.id, {}).get("passed", False)
                            for challenge in challenges
                        )
                        snapshot = current_progress()
                        all_passed = snapshot["certified"]

                        with ui.column().classes("check-card"):
                            if all_passed:
                                # Celebratory Completion State
                                with ui.column().classes("w-full text-center items-center py-6 gap-4"):
                                    ui.icon("check_circle", size="4rem", color="positive")
                                    ui.label("LESSON CERTIFIED COMPLETE").classes("editorial-eyebrow")
                                    ui.label("Conceptual Mastery Confirmed!").classes("font-serif text-3xl text-[#161616]")
                                    ui.label(
                                        f"You have verified your understanding across Read, Watch, Experiment, Practice, and Check for {lesson.title}."
                                    ).classes("text-sm text-[#5E5A55] max-w-lg leading-relaxed")

                                    with ui.row().classes("gap-3 pt-4"):
                                        ui.button(
                                            "Review Questions",
                                            on_click=lambda: restart_checkpoint()
                                        ).props("outline").classes("btn-subtle")

                                        ui.button(
                                            "Return to Module Overview",
                                            on_click=lambda: nav.open_module(module.id)
                                        ).props("outline").classes("btn-subtle")
                                return

                            # Active Question Assessment Flow
                            curr_q = checkpoints[q_idx]
                            q_key = f"q_{q_idx}"
                            current_saved_ans = checkpoint_answers.get(q_key, {})

                            # Question Header & Progress
                            with ui.row().classes("w-full items-center justify-between"):
                                ui.label(f"QUESTION {q_idx + 1} OF {total_q}").classes("editorial-eyebrow")
                                ui.label(f"Mastery Checkpoint").classes("text-xs text-[#8C857D] font-mono")

                            ui.label(curr_q.question).classes("font-serif text-2xl text-[#161616] leading-snug")

                            # Options Radio Group
                            radio_group = ui.radio(
                                curr_q.options,
                                value=current_saved_ans.get("choice_text"),
                            ).props("dense").classes("w-full gap-2")

                            # Feedback Banner (Hidden initially unless previously attempted)
                            feedback_box = ui.column().classes("w-full hidden")

                            # Bottom Action Row
                            with ui.row().classes("w-full items-center justify-between pt-4"):
                                with ui.row().classes("items-center gap-2"):
                                    if q_idx > 0:
                                        ui.button("← Previous Question", on_click=lambda: switch_question(q_idx - 1)).props("outline dense").classes("btn-subtle text-xs")

                                check_action_btn = ui.button("Check Answer").classes("btn-blue")
                                continue_action_btn = ui.button(
                                    "Next Question →" if q_idx < total_q - 1 else "Complete & Certify Lesson →"
                                ).classes("btn-blue hidden")

                            def on_check():
                                if not radio_group.value:
                                    ui.notify("Please select an answer first.", color="warning")
                                    return
                                selected_index = curr_q.options.index(radio_group.value)
                                try:
                                    with get_db() as db:
                                        answer_result = submit_checkpoint_answer(
                                            db,
                                            learner_id,
                                            module.id,
                                            lesson.id,
                                            q_idx,
                                            selected_index,
                                        )
                                except ProgressionError as exc:
                                    explain_locked(str(exc))
                                    return
                                is_correct = answer_result["passed"]
                                attempts = answer_result["attempts"]
                                checkpoint_answers.clear()
                                checkpoint_answers.update(answer_result["progress"]["checkpoint"])

                                feedback_box.clear()
                                feedback_box.classes(remove="hidden")

                                with feedback_box:
                                    if is_correct:
                                        with ui.column().classes("check-feedback-banner is-correct w-full"):
                                            ui.label("✓ Correct!").classes("font-semibold text-sm text-[#2D6A4F]")
                                            ui.label(curr_q.explanation).classes("text-xs text-[#2D6A4F] leading-relaxed")
                                        check_action_btn.classes(add="hidden")
                                        continue_action_btn.classes(remove="hidden")
                                        refresh_stage_tabs()
                                        render_lesson_navigation.refresh()
                                    else:
                                        with ui.column().classes("check-feedback-banner is-incorrect w-full"):
                                            ui.label("Not quite yet — Try again").classes("font-semibold text-sm text-[#9D3A3A]")
                                            ui.label(curr_q.explanation).classes("text-xs text-[#9D3A3A] leading-relaxed")
                                            ui.label(f"Attempt {attempts}. Review the relevant Read section, retry its Practice activity, then answer again.").classes("text-[11px] text-[#5E5A55]")

                            def on_continue():
                                if q_idx < total_q - 1:
                                    switch_question(q_idx + 1)
                                else:
                                    with get_db() as db:
                                        certified = mark_lesson_complete(
                                            db, learner_id, module.id, lesson.id, len(module.lessons)
                                        )
                                    if not certified:
                                        ui.notify(
                                            "Complete every required activity before certification.",
                                            color="warning",
                                        )
                                        return
                                    render_check_view.refresh()
                                    render_lesson_navigation.refresh()

                            check_action_btn.on_click(on_check)
                            continue_action_btn.on_click(on_continue)

                            # If already passed this question previously, reveal continue
                            if current_saved_ans.get("passed"):
                                feedback_box.clear()
                                feedback_box.classes(remove="hidden")
                                with feedback_box:
                                    with ui.column().classes("check-feedback-banner is-correct w-full"):
                                        ui.label("✓ Answer Verified").classes("font-semibold text-sm text-[#2D6A4F]")
                                        ui.label(curr_q.explanation).classes("text-xs text-[#2D6A4F]")
                                check_action_btn.classes(add="hidden")
                                continue_action_btn.classes(remove="hidden")

                    def switch_question(idx: int):
                        unlocked = idx == 0 or checkpoint_answers.get(
                            f"q_{idx - 1}", {}
                        ).get("passed", False)
                        if 0 <= idx < len(checkpoints) and unlocked:
                            active_checkpoint_idx["value"] = idx
                            render_check_view.refresh()
                        elif 0 <= idx < len(checkpoints):
                            explain_locked("Answer the previous checkpoint correctly first.")

                    def restart_checkpoint():
                        active_checkpoint_idx["value"] = 0
                        render_check_view.refresh()

                    render_check_view()

            # 4. Bottom Shared Lesson Navigation Footer (Left: Back, Center: Progress, Right: Next)
            @ui.refreshable
            def render_lesson_navigation():
                snapshot = current_progress()
                cur_stage = saved_state.get("stage") if saved_state.get("stage") in STAGES else (tabs.value if tabs.value in STAGES else "read")
                if cur_stage not in STAGES:
                    cur_stage = "read"
                cur_idx = STAGES.index(cur_stage)
                stage_titles = {
                    "read": "Read",
                    "watch": "Watch",
                    "experiment": "Experiment",
                    "practice": "Practice",
                    "check": "Check",
                }

                with ui.row().classes("lesson-nav-footer w-full items-center justify-between gap-4"):
                    # Left: Back / Previous Stage
                    if cur_idx > 0:
                        prev_stage = STAGES[cur_idx - 1]
                        if prev_stage == "watch" and not video_info:
                            prev_stage = "read"
                        ui.button(
                            f"← Back: {stage_titles[prev_stage]}",
                            on_click=lambda _, s=prev_stage: advance_to_stage(s),
                        ).props("outline no-caps").classes("btn-subtle text-xs font-semibold px-4 py-2")
                    else:
                        if previous_id:
                            ui.button(
                                "← Previous Lesson",
                                on_click=lambda: nav.open_lesson(module.id, previous_id, "read"),
                            ).props("outline no-caps").classes("btn-subtle text-xs font-semibold px-4 py-2")
                        else:
                            ui.button(
                                f"← {module.code} Overview",
                                on_click=lambda: nav.open_module(module.id),
                            ).props("outline no-caps").classes("btn-subtle text-xs font-semibold px-4 py-2")

                    # Center: Current stage & learning progress
                    with ui.row().classes("items-center gap-2 flex-wrap justify-center"):
                        ui.label(f"STAGE 0{cur_idx + 1} OF 05").classes("editorial-eyebrow")
                        ui.label("·").classes("text-xs text-[#8C857D]")
                        ui.label(stage_titles[cur_stage].upper()).classes("text-xs font-semibold text-[#161616]")
                        ui.label("·").classes("text-xs text-[#8C857D]")
                        ui.label("Autosaved to SQLite").classes("text-[11px] font-mono text-[#8C857D]")

                    # Right: Next Stage / Continue
                    if cur_idx < len(STAGES) - 1:
                        next_stage = STAGES[cur_idx + 1]
                        if next_stage == "watch" and not video_info:
                            next_stage = "experiment"

                        def handle_next(target: str):
                            if cur_stage == "watch":
                                persist_activity(notes=saved_state["notes"])
                            elif cur_stage == "experiment":
                                persist_activity(experiment_code=saved_state["experiment_code"])
                            advance_to_stage(target)

                        next_button = ui.button(
                            f"Next Stage: {stage_titles[next_stage]} →",
                            on_click=lambda _, t=next_stage: handle_next(t),
                        ).classes("btn-blue text-xs font-semibold px-4 py-2")
                        if not snapshot["unlocked"][next_stage]:
                            next_button.props("disabled").classes(
                                add="opacity-50 cursor-not-allowed"
                            ).tooltip(
                                f"Complete the required {stage_titles[cur_stage]} activity first."
                            )
                    else:
                        # Final stage: Check
                        if snapshot["certified"]:
                            if next_id:
                                ui.button(
                                    "Next Lesson →",
                                    on_click=lambda: nav.open_lesson(module.id, next_id, "read"),
                                ).classes("btn-blue text-xs font-semibold px-4 py-2")
                            else:
                                ui.button(
                                    "Module Assessment & Quiz →",
                                    on_click=lambda: nav.open_quiz(module.id),
                                ).classes("btn-blue text-xs font-semibold px-4 py-2")
                        else:
                            ui.button(
                                "Next Lesson →",
                            ).props("disabled").classes("btn-subtle text-xs font-semibold px-4 py-2 opacity-50 cursor-not-allowed").tooltip(
                                "Complete all check questions to certify this lesson."
                            )

            render_lesson_navigation()
