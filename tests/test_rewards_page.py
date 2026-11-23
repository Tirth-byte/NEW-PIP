"""Browser regression coverage for the public graduate rewards preview."""

from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = "http://localhost:8080"


def test_rewards_page_public_responsive_and_auth_aware():
    asset_dir = Path("assets/rewards")
    expected_assets = {
        "rewards-hero.webp",
        "signature-tshirt.webp",
        "black-nfc-card.webp",
        "goodies-box.webp",
    }
    assert expected_assets <= {path.name for path in asset_dir.glob("*.webp")}
    assert all((asset_dir / name).stat().st_size < 250_000 for name in expected_assets)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        for viewport in ({"width": 1440, "height": 900}, {"width": 390, "height": 844}):
            page = browser.new_page(viewport=viewport)
            errors = []
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            page.on("pageerror", lambda error: errors.append(str(error)))
            response = page.goto(f"{BASE_URL}/rewards", wait_until="networkidle")

            assert response is not None and response.status == 200
            assert page.get_by_text("Finish the course. Earn something worth keeping.", exact=True).is_visible()
            assert page.get_by_text("PLANNED GRADUATE OFFERING", exact=True).is_visible()
            assert page.get_by_text("Not everyone finishes. That's what makes it special.", exact=True).is_visible()
            assert page.get_by_role("button", name="Start Learning", exact=True).count() >= 1
            assert page.locator("img.reward-product-image").count() == 4
            if viewport["width"] >= 768:
                assert page.get_by_role("button", name="Rewards", exact=True).is_visible()

            # Trigger lazy images and confirm every local asset decodes.
            page.locator("img.reward-product-image").last.scroll_into_view_if_needed()
            page.wait_for_timeout(250)
            for index in range(4):
                assert page.locator("img.reward-product-image").nth(index).evaluate(
                    "image => image.complete && image.naturalWidth > 0"
                )

            assert page.evaluate("document.documentElement.scrollWidth") <= viewport["width"] + 1
            assert not errors
            page.close()

        # Authenticated visitors receive Continue Learning instead of a guest CTA.
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.locator("input[placeholder*='priya']").fill("priya")
        page.locator("input[type='password']").fill("Priya123!")
        page.get_by_role("button", name="Sign In →").click()
        page.wait_for_url("**/dashboard")
        page.goto(f"{BASE_URL}/rewards", wait_until="networkidle")
        assert page.get_by_role("button", name="Continue Learning", exact=True).count() >= 1
        assert page.get_by_role("button", name="Start Learning", exact=True).count() == 0
        browser.close()
