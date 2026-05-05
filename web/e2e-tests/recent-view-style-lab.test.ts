import assert from "node:assert/strict";

import type {Page} from "puppeteer";

import * as common from "./lib/common.ts";

const VARIABLE = "--color-background-recent-view-row-unread";
const TEST_LIGHT_COLOR = "hsl(60deg 90% 75%)";

async function open_lab(page: Page): Promise<void> {
    await page.click("#recent-view-style-lab .zulip-icon-tool");
    await page.waitForSelector(".recent-view-style-lab", {visible: true});
}

async function close_lab(page: Page): Promise<void> {
    await page.click("#recent-view-style-lab .zulip-icon-tool");
    await page.waitForSelector(".recent-view-style-lab", {hidden: true});
}

async function get_snippet(page: Page): Promise<string> {
    return await page.$eval(
        ".recent-view-style-lab-snippet",
        (element) => (element as HTMLTextAreaElement).value,
    );
}

async function get_root_variable(page: Page, name: string): Promise<string> {
    return await page.evaluate(
        (variable) => getComputedStyle(document.documentElement).getPropertyValue(variable).trim(),
        name,
    );
}

async function recent_view_style_lab_test(page: Page): Promise<void> {
    await common.log_in(page);

    await page.goto("http://zulip.zulipdev.com:9981/#recent");
    await page.waitForSelector("#recent_view_table", {visible: true});

    // The wrench icon is rendered in the navbar.
    await page.waitForSelector("#recent-view-style-lab .zulip-icon-tool", {visible: true});
    await common.screenshot(page, "recent-view-style-lab-navbar");

    // Open the popover and confirm the expected controls are present.
    await open_lab(page);

    const variable_targets = await page.$$eval(".recent-view-style-lab-row-target", (elements) =>
        elements.map((element) => element.textContent?.trim() ?? ""),
    );
    for (const expected of [
        "--color-background-recent-view-row",
        "--color-background-recent-view-row-unread",
        "--color-background-recent-view-row-hover",
        "--color-recent-view-link",
        "--color-recent-view-link-unread",
        "--font-weight-recent-view-row-unread",
        "--opacity-recent-view-row-read",
    ]) {
        assert.ok(
            variable_targets.includes(expected),
            `Expected popover to label control with ${expected}, saw: ${variable_targets.join(", ")}`,
        );
    }

    // The snippet starts with a placeholder comment (no overrides yet).
    assert.match(
        await get_snippet(page),
        /^\/\*/,
        "Snippet should start with a placeholder comment when no overrides are active.",
    );
    await common.screenshot(page, "recent-view-style-lab-open");

    // Type a vivid yellow into the unread row light input. Use Tab to commit
    // the value so the change handler runs.
    await page.click(
        '.recent-view-style-lab-text[data-key="row_bg_unread"][data-mode="light"]',
    );
    await page.type(
        '.recent-view-style-lab-text[data-key="row_bg_unread"][data-mode="light"]',
        TEST_LIGHT_COLOR,
    );
    await page.keyboard.press("Tab");

    await page.waitForFunction((variable_name: string) => {
        const snippet = document.querySelector<HTMLTextAreaElement>(
            ".recent-view-style-lab-snippet",
        );
        return snippet !== null && snippet.value.includes(variable_name);
    }, {}, VARIABLE);

    const snippet = await get_snippet(page);
    assert.ok(
        snippet.includes(`${VARIABLE}: light-dark(${TEST_LIGHT_COLOR},`),
        `Expected snippet to override ${VARIABLE} with light-dark(${TEST_LIGHT_COLOR}, ...), got:\n${snippet}`,
    );

    const computed = await get_root_variable(page, VARIABLE);
    assert.ok(
        computed.includes(TEST_LIGHT_COLOR),
        `Expected ${VARIABLE} computed value to include ${TEST_LIGHT_COLOR}, got: ${computed}`,
    );

    await common.screenshot(page, "recent-view-style-lab-with-override");

    // Reload and confirm the persisted override is reapplied before the
    // popover ever opens.
    await close_lab(page);
    await page.reload({waitUntil: "networkidle2"});
    await page.waitForSelector("#recent_view_table", {visible: true});
    const reloaded_value = await get_root_variable(page, VARIABLE);
    assert.ok(
        reloaded_value.includes(TEST_LIGHT_COLOR),
        `Expected ${VARIABLE} to persist across reload, got: ${reloaded_value}`,
    );

    // Reset clears overrides and the snippet returns to its placeholder.
    await open_lab(page);
    await page.click(".recent-view-style-lab-reset");
    await page.waitForFunction(() => {
        const snippet_element = document.querySelector<HTMLTextAreaElement>(
            ".recent-view-style-lab-snippet",
        );
        return snippet_element !== null && snippet_element.value.startsWith("/*");
    });

    const cleared_value = await get_root_variable(page, VARIABLE);
    assert.ok(
        !cleared_value.includes(TEST_LIGHT_COLOR),
        `Expected ${VARIABLE} to clear after reset, got: ${cleared_value}`,
    );
}

await common.run_test(recent_view_style_lab_test);
