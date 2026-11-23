"""Public graduate rewards preview for Pip Learn."""

from nicegui import ui

from app.auth.service import get_current_user_and_learner
from app.components.layout import page_shell
from app.database.connection import get_db
import app.navigation.nav as nav


def _product_image(src: str, alt: str, *, eager: bool = False, classes: str = ""):
    loading = "eager" if eager else "lazy"
    return (
        ui.element("img")
        .props(
            f'src="{src}" alt="{alt}" loading="{loading}" '
            f'decoding="async" {"fetchpriority=high" if eager else ""}'
        )
        .classes(f"reward-product-image {classes}")
    )


def _planned_badge():
    with ui.row().classes("reward-planned-badge items-center gap-2"):
        ui.element("span").classes("reward-planned-dot")
        ui.label("PLANNED GRADUATE OFFERING")


def render_rewards_screen():
    with get_db() as db:
        is_authenticated = get_current_user_and_learner(db) is not None

    learning_action = nav.resume_learning if is_authenticated else nav.start_learning
    learning_label = "Continue Learning" if is_authenticated else "Start Learning"

    ui.add_css("""
    html { scroll-behavior: smooth; }
    .rewards-page { color: #161616; overflow: hidden; }
    .rewards-page * { box-sizing: border-box; }
    .reward-section { padding: clamp(4.5rem, 9vw, 8.5rem) 1.25rem; }
    .reward-wrap { width: 100%; max-width: 1180px; margin: 0 auto; }
    .reward-kicker { font: 600 .69rem/1.2 var(--font-mono); letter-spacing: .16em; color: #4F83BC; }
    .reward-display { font-family: var(--font-serif); font-size: clamp(2.65rem, 6.2vw, 6.1rem); line-height: .97; letter-spacing: -.045em; }
    .reward-h2 { font-family: var(--font-serif); font-size: clamp(2.25rem, 4.6vw, 4.75rem); line-height: 1.02; letter-spacing: -.035em; }
    .reward-body { color: #5E5A55; font-size: clamp(.98rem, 1.35vw, 1.15rem); line-height: 1.75; }
    .reward-planned-badge { width: fit-content; padding: .52rem .8rem; border: 1px solid #D6CFC5; border-radius: 999px; color: #5E5A55; background: rgba(255,255,255,.68); font: 600 .66rem/1 var(--font-mono); letter-spacing: .11em; }
    .reward-planned-dot { width: 6px; height: 6px; border-radius: 50%; background: #4F83BC; }
    .reward-hero { min-height: calc(100vh - 64px); display: flex; align-items: center; background: #F5F2EC; }
    .reward-hero-grid { display: grid; grid-template-columns: minmax(0,.88fr) minmax(520px,1.12fr); align-items: center; gap: clamp(2rem,5vw,5rem); }
    .reward-hero-copy { position: relative; z-index: 2; }
    .reward-hero-media { position: relative; }
    .reward-hero-media:before { content: ''; position: absolute; inset: 8% -6% -8% 11%; border: 1px solid #D9D1C6; border-radius: 52% 48% 44% 56%; transform: rotate(-3deg); }
    .reward-product-image { display: block; width: 100%; height: 100%; object-fit: cover; }
    .reward-hero-image { position: relative; z-index: 1; aspect-ratio: 16/9; border-radius: 1.5rem; box-shadow: 0 35px 80px rgba(43,37,31,.16); }
    .reward-media-frame { overflow: hidden; border-radius: 1.35rem; border: 1px solid #D9D1C6; background: #EAE4DC; box-shadow: 0 22px 60px rgba(43,37,31,.1); }
    .reward-media-frame .reward-product-image { transition: transform .8s cubic-bezier(.2,.7,.2,1); }
    .reward-media-frame:hover .reward-product-image { transform: scale(1.018); }
    .reward-disclosure { border-left: 2px solid #7FA5CB; padding-left: 1rem; color: #6F6962; font-size: .78rem; line-height: 1.55; max-width: 34rem; }
    .reward-split { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); align-items: center; gap: clamp(3rem,8vw,8rem); }
    .reward-dark { background: #151719; color: #F8F4ED; }
    .reward-dark .reward-body { color: #BDB8B0; }
    .reward-dark .reward-kicker { color: #8EB6DE; }
    .reward-card-frame { border-color: #36393C; background: #090A0B; box-shadow: 0 30px 80px rgba(0,0,0,.35); }
    .reward-feature-list { display: grid; gap: .8rem; margin-top: .75rem; }
    .reward-feature { display: grid; grid-template-columns: 25px 1fr; gap: .7rem; color: #BDB8B0; font-size: .86rem; line-height: 1.45; }
    .reward-feature-index { color: #8EB6DE; font: 600 .65rem/1.8 var(--font-mono); }
    .reward-steps { position: relative; display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 0; margin-top: 4rem; }
    .reward-steps:before { content: ''; position: absolute; left: 4%; right: 4%; top: 17px; height: 1px; background: #CFC7BC; }
    .reward-step { position: relative; padding: 3.65rem 2rem 0 0; }
    .reward-step-marker { position: absolute; top: 0; left: 0; width: 35px; height: 35px; border-radius: 50%; display: grid; place-items: center; background: #F5F2EC; border: 1px solid #9DB6CE; color: #396DAB; font: 600 .7rem/1 var(--font-mono); z-index: 1; }
    .reward-story { background: #EAE4DB; }
    .reward-quote-line { width: 72px; height: 2px; background: #4F83BC; }
    .reward-final { background: #23342B; color: #FBF8F3; text-align: center; }
    .reward-final .reward-body { color: #D1D5D0; }
    .reward-reveal { animation: reward-rise .75s cubic-bezier(.2,.75,.25,1) both; }
    .reward-delay-1 { animation-delay: .1s; } .reward-delay-2 { animation-delay: .2s; }
    @keyframes reward-rise { from { opacity: 0; transform: translateY(18px); } to { opacity: 1; transform: none; } }
    @media (max-width: 900px) {
      .reward-hero { min-height: auto; }
      .reward-hero-grid, .reward-split { grid-template-columns: 1fr; }
      .reward-hero-grid { gap: 3rem; }
      .reward-hero-media { order: -1; }
      .reward-hero-image { aspect-ratio: 16/10; }
      .reward-steps { grid-template-columns: repeat(2,minmax(0,1fr)); gap: 2.5rem 1rem; }
      .reward-steps:before { display: none; }
      .reward-step { padding-top: 3rem; }
      .reward-split.reward-reverse .reward-media-frame { order: -1; }
    }
    @media (max-width: 560px) {
      .reward-section { padding: 4rem 1rem; }
      .reward-hero-grid { display: flex; flex-direction: column; }
      .reward-hero-media { order: 1; }
      .reward-hero-image { aspect-ratio: 4/3; border-radius: 1rem; }
      .reward-steps { grid-template-columns: 1fr; gap: 1.5rem; }
      .reward-step { padding-right: 0; padding-left: 3.25rem; padding-top: 0; min-height: 3.2rem; }
      .reward-step-marker { top: 1px; }
      .reward-media-frame { border-radius: 1rem; }
    }
    @media (prefers-reduced-motion: reduce) {
      html { scroll-behavior: auto; }
      .reward-reveal { animation: none; }
      .reward-media-frame .reward-product-image { transition: none; }
    }
    """)

    with page_shell(active_route="/rewards"):
        with ui.element("div").classes("rewards-page w-full"):
            # A. Hero
            with ui.element("section").classes("reward-section reward-hero"):
                with ui.element("div").classes("reward-wrap reward-hero-grid"):
                    with ui.column().classes("reward-hero-copy gap-6 items-start reward-reveal"):
                        _planned_badge()
                        ui.label("Finish the course. Earn something worth keeping.").classes("reward-display")
                        ui.label(
                            "Learning Python is an achievement. Finishing what you started deserves something special. "
                            "Discover the exclusive rewards we're preparing for PIP Learn graduates."
                        ).classes("reward-body max-w-xl")
                        with ui.row().classes("gap-3 flex-wrap pt-1"):
                            ui.button(
                                "Explore the Rewards",
                                on_click=lambda: ui.run_javascript(
                                    'document.getElementById("signature-reward")?.scrollIntoView({behavior:"smooth"})'
                                ),
                            ).classes("btn-blue px-6 py-3 rounded-xl normal-case")
                            ui.button(learning_label, on_click=learning_action).classes(
                                "btn-blue-outline px-6 py-3 rounded-xl normal-case"
                            )
                        ui.label(
                            "Concept preview only. Eligibility, availability, shipping regions, and fulfillment details will be announced separately."
                        ).classes("reward-disclosure mt-2")
                    with ui.element("div").classes("reward-hero-media reward-reveal reward-delay-1"):
                        _product_image(
                            "/assets/rewards/rewards-hero.webp",
                            "Concept arrangement of a Pip Learn T-shirt, developer card, notebook, stickers, and presentation box",
                            eager=True,
                            classes="reward-hero-image",
                        )

            # B. T-shirt
            with ui.element("section").props('id="signature-reward"').classes("reward-section bg-[#FAF7F2]"):
                with ui.element("div").classes("reward-wrap reward-split"):
                    with ui.column().classes("gap-5 items-start reward-reveal"):
                        ui.label("THE SIGNATURE T-SHIRT").classes("reward-kicker")
                        ui.label("Built for those who build.").classes("reward-h2")
                        ui.label(
                            "A considered heavyweight tee with the quiet confidence of good code: restrained branding, "
                            "thoughtful details, and a silhouette designed to be worn well beyond the classroom."
                        ).classes("reward-body max-w-xl")
                        with ui.row().classes("gap-2 flex-wrap"):
                            for label in ("Heavyweight cotton concept", "Front + back study", "Graduate edition"):
                                ui.label(label).classes("px-3 py-1.5 rounded-full border border-[#D6CFC5] text-[11px] text-[#6A645D] font-mono")
                        ui.label("Final garment, sizing, colorways, and production details remain subject to availability.").classes("reward-disclosure")
                    with ui.element("div").classes("reward-media-frame aspect-[3/2] reward-reveal reward-delay-1"):
                        _product_image(
                            "/assets/rewards/signature-tshirt.webp",
                            "Front and back concept views of a charcoal Pip Learn heavyweight T-shirt",
                        )

            # C. NFC card
            with ui.element("section").classes("reward-section reward-dark"):
                with ui.element("div").classes("reward-wrap reward-split reward-reverse"):
                    with ui.element("div").classes("reward-media-frame reward-card-frame aspect-[3/2] reward-reveal"):
                        _product_image(
                            "/assets/rewards/black-nfc-card.webp",
                            "Concept matte-black brushed-metal Pip Learn NFC developer identity card",
                        )
                    with ui.column().classes("gap-5 items-start reward-reveal reward-delay-1"):
                        ui.label("PIP BLACK / NFC CONCEPT").classes("reward-kicker")
                        ui.label("A developer identity, made tangible.").classes("reward-h2")
                        ui.label(
                            "A proposed matte-black metal card designed to represent verified learning—not payment. "
                            "The future concept could connect to a public developer profile and selected achievements."
                        ).classes("reward-body")
                        with ui.column().classes("reward-feature-list"):
                            for idx, text in enumerate((
                                "A verified graduate profile and completed learning milestones.",
                                "Selected portfolio projects and a learner-provided GitHub profile.",
                                "A durable, minimal keepsake for the work behind the achievement.",
                            ), 1):
                                with ui.element("div").classes("reward-feature"):
                                    ui.label(f"0{idx}").classes("reward-feature-index")
                                    ui.label(text)
                        ui.label("The NFC profile experience is a planned concept and is not currently part of the platform.").classes("reward-disclosure border-[#55799C]")

            # D. Goodies box
            with ui.element("section").classes("reward-section bg-[#F5F2EC]"):
                with ui.element("div").classes("reward-wrap reward-split"):
                    with ui.column().classes("gap-5 items-start reward-reveal"):
                        ui.label("THE GOODIES BOX").classes("reward-kicker")
                        ui.label("A little something for the journey.").classes("reward-h2")
                        ui.label(
                            "A proposed collection of small, useful reminders of the path you completed: a developer notebook, "
                            "Pip stickers, branded accessories, collectible pieces, and the occasional surprise item."
                        ).classes("reward-body")
                        ui.label(
                            "Contents shown are design concepts. The final selection may change and no item is guaranteed until program details are formally announced."
                        ).classes("reward-disclosure")
                    with ui.element("div").classes("reward-media-frame aspect-[3/2] reward-reveal reward-delay-1"):
                        _product_image(
                            "/assets/rewards/goodies-box.webp",
                            "Concept Pip Learn presentation box with notebook, sticker sheet, pin, pencil, and developer accessories",
                        )

            # E. How to earn
            with ui.element("section").classes("reward-section bg-[#F5F2EC] border-t border-[#DCD5CB]"):
                with ui.column().classes("reward-wrap gap-3 reward-reveal"):
                    ui.label("THE PATH").classes("reward-kicker")
                    ui.label("Earned through the work.").classes("reward-h2 max-w-3xl")
                    ui.label(
                        "The intended eligibility path follows genuine course completion. Formal program rules and fulfillment requirements have not yet been published."
                    ).classes("reward-body max-w-3xl")
                    with ui.element("div").classes("reward-steps"):
                        steps = (
                            ("01", "Begin your Python journey", "Build the foundations one concept at a time."),
                            ("02", "Complete all eight modules", "Finish every required learning sequence."),
                            ("03", "Pass the required work", "Complete assessments and final practical work."),
                            ("04", "Become eligible", "Await the announced rewards-program terms."),
                        )
                        for num, title, desc in steps:
                            with ui.column().classes("reward-step gap-2"):
                                ui.label(num).classes("reward-step-marker")
                                ui.label(title).classes("font-serif text-xl text-[#161616]")
                                ui.label(desc).classes("text-sm text-[#6A645D] leading-relaxed")

            # F. Story
            with ui.element("section").classes("reward-section reward-story"):
                with ui.column().classes("reward-wrap max-w-4xl items-center text-center gap-7 reward-reveal"):
                    ui.element("div").classes("reward-quote-line")
                    ui.label("Not everyone finishes. That's what makes it special.").classes("reward-h2")
                    ui.label(
                        "The reward is not for racing through the material. It represents the quiet persistence of returning, "
                        "practising, getting things wrong, building again, and finishing with understanding. Every learner's pace "
                        "is different. What matters is the decision to keep going."
                    ).classes("reward-body max-w-3xl")
                    ui.label("You didn't just learn Python. You earned something real.").classes(
                        "font-serif italic text-xl sm:text-2xl text-[#314A5F]"
                    )

            # G. Final CTA
            with ui.element("section").classes("reward-section reward-final"):
                with ui.column().classes("reward-wrap max-w-4xl items-center text-center gap-6 reward-reveal"):
                    ui.label("FINISH STRONG").classes("reward-kicker text-[#9AC1E6]")
                    ui.label("Your journey deserves a better ending.").classes("reward-h2")
                    ui.label(
                        "Learn. Build. Finish strong. Something special is waiting on the other side."
                    ).classes("reward-body max-w-2xl")
                    ui.button(
                        learning_label,
                        on_click=learning_action,
                    ).classes("bg-[#FBF8F3] text-[#23342B] hover:bg-white px-8 py-3.5 rounded-xl normal-case font-semibold shadow-sm")
                    if not is_authenticated:
                        ui.label("Already learning with Pip? Sign in to continue from your saved progress.").classes(
                            "text-xs text-[#B9C5BF]"
                        )
                        ui.button(
                            "Sign In",
                            on_click=lambda: nav.go_to_login("/rewards"),
                        ).props("flat dense").classes("text-[#D6E5DE] normal-case underline")
                    ui.label(
                        "Rewards remain a planned offering. Availability, eligibility, and fulfillment are not guaranteed until officially announced."
                    ).classes("text-[11px] text-[#9DA8A3] max-w-2xl leading-relaxed mt-3")
