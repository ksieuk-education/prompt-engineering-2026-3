"""Run the archive's keyboard workflow in an actual browser with optional Playwright."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def timestamp(seconds: int) -> str:
    minutes, remainder = divmod(seconds, 60)
    return f"{minutes:02d}:{remainder:02d}"


def check_session(browser, url: str) -> dict:
    page = browser.new_page(viewport={"width": 1280, "height": 850})
    page.goto(url)
    cases = page.locator(".case-button")
    expect(cases).to_have_count(3)
    cases.nth(1).press("Enter")
    expect(cases.nth(1)).to_be_focused()
    expect(cases.nth(1)).to_have_attribute("aria-current", "true")
    cases.first.press("Enter")
    for label in ("Метки для прослушивания", "Режим диалога"):
        expect(page.get_by_role("group", name=label)).to_be_visible()

    page.wait_for_function("document.getElementById('audio').readyState >= 1")
    slider = page.get_by_role("slider")
    duration = int(slider.get_attribute("aria-valuemax"))
    sequence = [
        ("Home", 0),
        ("ArrowDown", 0),
        ("ArrowUp", 1),
        ("ArrowRight", 2),
        ("ArrowDown", 1),
        ("ArrowLeft", 0),
        ("PageUp", 5),
        ("End", duration),
        ("ArrowUp", duration),
        ("PageDown", duration - 5),
    ]
    for key, second in sequence:
        slider.press(key)
        expect(slider).to_have_js_property("ariaValueNow", f"{second:.1f}")
        expect(slider).to_have_attribute(
            "aria-valuetext", f"{timestamp(second)} из {timestamp(duration)}"
        )

    document = page.locator("#documents .doc").first
    title = document.locator("strong").inner_text()
    document.press("Enter")
    reader = page.get_by_role("dialog", name=title)
    close = reader.get_by_role("button", name="Закрыть")
    expect(close).to_be_focused()
    for key in ("Tab", "Shift+Tab"):
        page.keyboard.press(key)
        expect(close).to_be_focused()
    page.keyboard.press("Escape")
    expect(document).to_be_focused()

    field_button = page.get_by_role("button", name="Сверка записей NASA")
    field_button.press("Enter")
    field = page.get_by_role("dialog", name="Сверка записей NASA")
    field_close = field.get_by_role("button", name="Закрыть")
    expect(field_close).to_be_focused()
    search_summary = field.locator("#transcript-search summary")
    page.keyboard.press("Shift+Tab")
    expect(search_summary).to_be_focused()
    page.keyboard.press("Tab")
    expect(field_close).to_be_focused()
    search_summary.press("Enter")
    field.locator("#transcript-words").press("Enter")
    citation = field.get_by_role("button", name="Открыть стр. 317").first
    citation.press("Enter")
    leaf = page.get_by_role("dialog", name="Стенограмма, стр. 317")
    expect(leaf.locator("mark").first).to_contain_text(
        "Eagle has landed", ignore_case=True
    )
    source = leaf.get_by_role("link", name="Оригинал стенограммы NASA")
    page.keyboard.press("Shift+Tab")
    expect(source).to_be_focused()
    page.keyboard.press("Tab")
    expect(leaf.get_by_role("button", name="Закрыть")).to_be_focused()
    page.keyboard.press("Escape")
    expect(citation).to_be_focused()
    page.keyboard.press("Escape")
    expect(field_button).to_be_focused()
    page.close()
    return {
        "browser_version": browser.version,
        "case_switch": True,
        "named_control_groups": 2,
        "slider_positions_checked": len(sequence),
        "document_title": title,
        "nested_transcript_page": 317,
        "tab_cycles_checked": 3,
        "focus_return_checked": 3,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument(
        "--browser",
        choices=["chrome", "chromium", "firefox", "webkit"],
        default="chrome",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    with sync_playwright() as pw:
        if args.browser == "chrome":
            browser = pw.chromium.launch(channel="chrome")
        else:
            browser = getattr(pw, args.browser).launch()
        try:
            result = {"browser": args.browser, **check_session(browser, args.url)}
        finally:
            browser.close()
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
