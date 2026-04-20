from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.async_api import Locator, Page, async_playwright


REPO_ROOT = Path(__file__).resolve().parent
OUTPUT_PATH = REPO_ROOT / "docs" / "enums" / "traininghub-live-builder-catalog.json"
SCHEDULE_URL = "https://training.coros.com/admin/views/schedule"
LOGIN_URL = "https://training.coros.com/login?lastUrl=%2Fadmin%2Fviews%2Fschedule"

SPORT_SELECTOR = ".sport-type-select"
EXERCISE_SELECTOR = ".exercise-type"
TARGET_SELECTOR = ".target-type"
INTENSITY_SELECTOR = ".program-intensity-type-select"
INTENSITY_ZONE_SELECTOR = ".intensity-zone"
POPUP_SELECTOR = ".arco-trigger-popup"
OPTION_SELECTOR = ".arco-select-option"
SELECT_VALUE_SELECTOR = ".arco-select-view-value"


@dataclass
class CaptureBuffer:
    payloads: list[dict[str, Any]]

    def latest(self) -> dict[str, Any]:
        if not self.payloads:
            raise RuntimeError("No training/program/calculate payloads captured yet.")
        return self.payloads[-1]


def normalize_sport_key(label: str) -> str:
    return label.strip().lower().replace(" ", "_")


def _read_keychain_secret(service: str) -> str:
    return subprocess.check_output(
        [
            "security",
            "find-generic-password",
            "-a",
            os.environ.get("USER", ""),
            "-s",
            service,
            "-w",
        ],
        text=True,
    ).strip()


def get_login_credentials() -> tuple[str, str]:
    email = os.environ.get("COROS_EMAIL") or _read_keychain_secret("coros-mcp-email")
    password = os.environ.get("COROS_PASSWORD") or _read_keychain_secret("coros-mcp-password")
    return email, password


def resolve_browser_executable() -> str | None:
    env_override = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    if env_override:
        return env_override

    candidates = sorted(
        (REPO_ROOT / ".playwright-browsers").glob(
            "chromium-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
        )
    )
    if candidates:
        return str(candidates[-1])
    return None


def _trimmed_texts(values: list[str]) -> list[str]:
    return [value.strip() for value in values if value and value.strip()]


async def login(page: Page) -> None:
    email, password = get_login_credentials()
    await page.goto(LOGIN_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(4_000)

    if "/login" not in page.url:
        return

    await page.get_by_placeholder("E-mail").fill(email)
    await page.get_by_placeholder("Please enter password with 6-20 characters").fill(password)

    checkboxes = page.locator(".arco-checkbox")
    for index in range(await checkboxes.count()):
        await checkboxes.nth(index).click()

    await page.get_by_role("button", name="Login").click()
    await page.wait_for_timeout(8_000)

    if "/login" in page.url:
        raise RuntimeError("Training Hub login did not complete.")


async def open_builder(page: Page) -> None:
    await page.goto(SCHEDULE_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(4_000)
    if "/login" in page.url:
        await login(page)
        await page.goto(SCHEDULE_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(4_000)

    await page.get_by_text("Workouts", exact=True).last.click()
    await page.wait_for_timeout(1_500)
    await page.get_by_text("Create Workouts", exact=True).click()
    await page.wait_for_timeout(3_000)
    await page.locator(SPORT_SELECTOR).wait_for(timeout=15_000)


async def active_popup(page: Page) -> Locator:
    for _ in range(10):
        popups = page.locator(POPUP_SELECTOR)
        count = await popups.count()
        for index in range(count - 1, -1, -1):
            popup = popups.nth(index)
            if await popup.is_visible() and await popup.locator(OPTION_SELECTOR).count():
                return popup
        await page.wait_for_timeout(150)
    raise RuntimeError("Could not find an active dropdown popup.")


async def safe_dropdown_options(page: Page, trigger: Locator) -> list[str]:
    try:
        return await dropdown_options(page, trigger)
    except Exception:
        return []


async def dropdown_options(page: Page, trigger: Locator) -> list[str]:
    await trigger.click(force=True)
    await page.wait_for_timeout(500)
    popup = await active_popup(page)
    options = _trimmed_texts(await popup.locator(OPTION_SELECTOR).all_inner_texts())
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(250)
    return options


async def maybe_confirm_sport_switch(page: Page) -> None:
    modal = page.locator(".arco-modal").filter(has_text=re.compile(r"Switching activity type", re.I))
    if not await modal.count():
        return
    active_modal = modal.last
    try:
        await active_modal.locator("button", has_text=re.compile(r"^OK$", re.I)).click(force=True)
        await page.wait_for_timeout(800)
    except Exception:
        pass


async def selected_label(trigger: Locator) -> str:
    texts = _trimmed_texts(await trigger.locator(SELECT_VALUE_SELECTOR).all_inner_texts())
    return texts[0] if texts else ""


async def wait_for_new_capture(
    page: Page,
    captures: CaptureBuffer,
    previous_count: int,
    timeout_ms: int = 8_000,
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    while asyncio.get_running_loop().time() < deadline:
        if len(captures.payloads) > previous_count:
            return captures.payloads[-1]
        await page.wait_for_timeout(200)
    raise TimeoutError("Timed out waiting for training/program/calculate request.")


async def choose_option(
    page: Page,
    trigger: Locator,
    label: str,
    captures: CaptureBuffer | None = None,
    require_capture: bool = True,
) -> dict[str, Any] | None:
    current = await selected_label(trigger)
    if current == label:
        return captures.latest() if captures and captures.payloads else None

    previous_count = len(captures.payloads) if captures else 0
    await trigger.click(force=True)
    await page.wait_for_timeout(500)
    popup = await active_popup(page)
    exact_pattern = re.compile(rf"^{re.escape(label)}$")
    await popup.locator(OPTION_SELECTOR).filter(has_text=exact_pattern).first.click(force=True)
    await maybe_confirm_sport_switch(page)
    await page.wait_for_timeout(500)

    if captures is None:
        return None
    if not require_capture:
        try:
            return await wait_for_new_capture(page, captures, previous_count, timeout_ms=2_000)
        except TimeoutError:
            return captures.latest() if captures.payloads else None
    return await wait_for_new_capture(page, captures, previous_count)


def extract_first_exercise(payload: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    exercise = ((payload.get("exercises") or [{}])[0]) if payload else {}
    return {key: exercise.get(key) for key in keys}


async def capture_initial_payload(page: Page, captures: CaptureBuffer) -> dict[str, Any]:
    if captures.payloads:
        return captures.latest()
    return await wait_for_new_capture(page, captures, 0, timeout_ms=10_000)


async def collect_sport_overview(page: Page) -> dict[str, Any]:
    captures = CaptureBuffer(payloads=[])

    def on_request(request) -> None:
        if "training/program/calculate" not in request.url or request.method != "POST":
            return
        try:
            captures.payloads.append(json.loads(request.post_data or "{}"))
        except json.JSONDecodeError:
            captures.payloads.append({"raw_post_data": request.post_data})

    page.on("request", on_request)
    await open_builder(page)
    await capture_initial_payload(page, captures)

    sport_trigger = page.locator(SPORT_SELECTOR)
    sport_labels = await dropdown_options(page, sport_trigger)
    await choose_option(page, page.locator(SPORT_SELECTOR), "Run", captures, require_capture=False)
    await page.wait_for_timeout(1_500)

    sports: dict[str, Any] = {
        "run": {
            "label": "Run",
            "exercise_options": await safe_dropdown_options(page, page.locator(EXERCISE_SELECTOR).nth(0))
            if await page.locator(EXERCISE_SELECTOR).count()
            else [],
            "target_options": await safe_dropdown_options(page, page.locator(TARGET_SELECTOR).nth(0))
            if await page.locator(TARGET_SELECTOR).count()
            else [],
            "intensity_options": await safe_dropdown_options(page, page.locator(INTENSITY_SELECTOR).nth(0))
            if await page.locator(INTENSITY_SELECTOR).count()
            else [],
        }
    }

    page.remove_listener("request", on_request)
    return {
        "available_sports": sport_labels,
        "sports": sports,
    }


async def collect_sport_builder_details(page: Page, sport_label: str) -> dict[str, Any]:
    captures = CaptureBuffer(payloads=[])

    def on_request(request) -> None:
        if "training/program/calculate" not in request.url or request.method != "POST":
            return
        try:
            captures.payloads.append(json.loads(request.post_data or "{}"))
        except json.JSONDecodeError:
            captures.payloads.append({"raw_post_data": request.post_data})

    page.on("request", on_request)
    await open_builder(page)
    baseline = await capture_initial_payload(page, captures)
    before_select = len(captures.payloads)
    payload = await choose_option(page, page.locator(SPORT_SELECTOR), sport_label, captures, require_capture=False)
    captured_after_select = len(captures.payloads) > before_select
    await page.wait_for_timeout(1_500)

    entry: dict[str, Any] = {
        "label": sport_label,
        "selected_sport_label": await selected_label(page.locator(SPORT_SELECTOR)),
        "exercise_options": [],
        "target_options": [],
        "intensity_options": [],
        "intensity_zone_options": [],
    }
    if await page.locator(EXERCISE_SELECTOR).count():
        entry["selected_exercise"] = await selected_label(page.locator(EXERCISE_SELECTOR).nth(0))
        entry["exercise_options"] = await safe_dropdown_options(page, page.locator(EXERCISE_SELECTOR).nth(0))
    if await page.locator(TARGET_SELECTOR).count():
        entry["selected_target"] = await selected_label(page.locator(TARGET_SELECTOR).nth(0))
        entry["target_options"] = await safe_dropdown_options(page, page.locator(TARGET_SELECTOR).nth(0))
    if await page.locator(INTENSITY_SELECTOR).count():
        entry["selected_intensity"] = await selected_label(page.locator(INTENSITY_SELECTOR).nth(0))
        entry["intensity_options"] = await safe_dropdown_options(page, page.locator(INTENSITY_SELECTOR).nth(0))
    if await page.locator(INTENSITY_ZONE_SELECTOR).count():
        entry["selected_intensity_zone"] = await selected_label(page.locator(INTENSITY_ZONE_SELECTOR).nth(0))
        entry["intensity_zone_options"] = await safe_dropdown_options(page, page.locator(INTENSITY_ZONE_SELECTOR).nth(0))

    if sport_label == "Run":
        entry["baseline_first_exercise"] = extract_first_exercise(
            baseline,
            [
                "exerciseType",
                "targetType",
                "targetValue",
                "intensityType",
                "hrType",
                "isIntensityPercent",
                "intensityPercent",
                "intensityPercentExtend",
                "intensityValue",
                "intensityValueExtend",
                "intensityDisplayUnit",
                "overview",
            ],
        )
    elif captured_after_select and payload:
        entry["baseline_first_exercise"] = extract_first_exercise(
            payload,
            [
                "exerciseType",
                "targetType",
                "targetValue",
                "intensityType",
                "hrType",
                "isIntensityPercent",
                "intensityPercent",
                "intensityPercentExtend",
                "intensityValue",
                "intensityValueExtend",
                "intensityDisplayUnit",
                "overview",
            ],
        )

    page.remove_listener("request", on_request)
    return entry


async def collect_run_correlations(page: Page) -> dict[str, Any]:
    captures = CaptureBuffer(payloads=[])

    def on_request(request) -> None:
        if "training/program/calculate" not in request.url or request.method != "POST":
            return
        try:
            captures.payloads.append(json.loads(request.post_data or "{}"))
        except json.JSONDecodeError:
            captures.payloads.append({"raw_post_data": request.post_data})

    page.on("request", on_request)
    await open_builder(page)
    baseline = await capture_initial_payload(page, captures)
    await choose_option(page, page.locator(SPORT_SELECTOR), "Run", captures)
    await page.wait_for_timeout(1_500)

    exercise_trigger = page.locator(EXERCISE_SELECTOR).nth(0)
    target_trigger = page.locator(TARGET_SELECTOR).nth(0)
    intensity_trigger = page.locator(INTENSITY_SELECTOR).nth(0)

    run_details = {
        "baseline_first_exercise": extract_first_exercise(
            baseline,
            [
                "exerciseType",
                "targetType",
                "targetValue",
                "intensityType",
                "hrType",
                "isIntensityPercent",
                "intensityPercent",
                "intensityPercentExtend",
                "intensityValue",
                "intensityValueExtend",
                "intensityDisplayUnit",
                "overview",
            ],
        ),
        "exercise_type_details": [],
        "target_type_details": [],
        "intensity_type_details": [],
    }

    for label in await dropdown_options(page, exercise_trigger):
        payload = await choose_option(page, exercise_trigger, label, captures, require_capture=False)
        run_details["exercise_type_details"].append(
            {
                "label": label,
                "selected_label": await selected_label(exercise_trigger),
                "payload": extract_first_exercise(
                    payload or captures.latest(),
                    ["exerciseType", "overview", "targetType", "targetValue"],
                ),
            }
        )

    await choose_option(page, exercise_trigger, "Warm Up", captures)
    await page.wait_for_timeout(1_000)

    for label in await dropdown_options(page, target_trigger):
        payload = await choose_option(page, target_trigger, label, captures, require_capture=False)
        run_details["target_type_details"].append(
            {
                "label": label,
                "selected_label": await selected_label(target_trigger),
                "payload": extract_first_exercise(
                    payload or captures.latest(),
                    ["targetType", "targetValue", "targetDisplayUnit", "overview"],
                ),
            }
        )

    await choose_option(page, target_trigger, "Time", captures)
    await page.wait_for_timeout(1_000)

    for label in await dropdown_options(page, intensity_trigger):
        payload = await choose_option(page, intensity_trigger, label, captures, require_capture=False)
        detail: dict[str, Any] = {
            "label": label,
            "selected_label": await selected_label(intensity_trigger),
            "payload": extract_first_exercise(
                payload or captures.latest(),
                [
                    "intensityType",
                    "hrType",
                    "isIntensityPercent",
                    "intensityPercent",
                    "intensityPercentExtend",
                    "intensityValue",
                    "intensityValueExtend",
                    "intensityDisplayUnit",
                ],
            ),
        }
        if await page.locator(INTENSITY_ZONE_SELECTOR).count():
            try:
                detail["zone_options"] = await dropdown_options(page, page.locator(INTENSITY_ZONE_SELECTOR).nth(0))
            except Exception:
                detail["zone_options"] = []
        run_details["intensity_type_details"].append(detail)

    page.remove_listener("request", on_request)
    return run_details


async def build_catalog(headless: bool = True) -> dict[str, Any]:
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(REPO_ROOT / ".playwright-browsers"))
    browser_executable = resolve_browser_executable()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=headless,
            executable_path=browser_executable,
        )

        overview_page = await browser.new_page(viewport={"width": 1600, "height": 1200})
        await login(overview_page)
        overview = await collect_sport_overview(overview_page)
        await overview_page.close()

        sports: dict[str, Any] = {}
        for sport_label in overview["available_sports"]:
            sport_page = await browser.new_page(viewport={"width": 1600, "height": 1200})
            try:
                await login(sport_page)
                sports[normalize_sport_key(sport_label)] = await asyncio.wait_for(
                    collect_sport_builder_details(sport_page, sport_label),
                    timeout=45,
                )
            except Exception as exc:
                sports[normalize_sport_key(sport_label)] = {
                    "label": sport_label,
                    "error": str(exc),
                }
            finally:
                await sport_page.close()

        run_page = await browser.new_page(viewport={"width": 1600, "height": 1200})
        try:
            await login(run_page)
            run_details = await asyncio.wait_for(collect_run_correlations(run_page), timeout=75)
        finally:
            await run_page.close()

        await browser.close()

    catalog = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": {
            "schedule_url": SCHEDULE_URL,
            "derived_from": "Training Hub builder UI plus training/program/calculate draft payloads",
            "auth": "Training Hub login via COROS credentials from env or macOS Keychain",
        },
        "available_sports": overview["available_sports"],
        "sports": sports,
        "correlations": {
            "run": run_details,
        },
        "notes": [
            "This catalog is generated by automating the live Training Hub builder and intercepting draft calculate requests.",
            "The checked-in JSON is intended to keep builder labels and raw payload fragments statically available to agents.",
            "Run intensity labels are composite in COROS, so the captured payload includes supporting fields like hrType and percent flags.",
            "Builder option lists are captured for every available sport; deeper composite correlation is currently run-specific.",
        ],
    }
    return catalog


def write_catalog(catalog: dict[str, Any], output_path: Path = OUTPUT_PATH) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract live COROS Training Hub builder enums into a checked-in JSON catalog.")
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help=f"Output JSON path (default: {OUTPUT_PATH})",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Run with a visible browser window instead of headless Chromium.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    catalog = asyncio.run(build_catalog(headless=not args.headful))
    path = write_catalog(catalog, args.output)
    print(path)


if __name__ == "__main__":
    main()
