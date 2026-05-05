import $ from "jquery";

import render_navbar_recent_view_style_lab from "../templates/popovers/navbar/navbar_recent_view_style_lab_popover.hbs";

import {localstorage} from "./localstorage.ts";
import * as popover_menus from "./popover_menus.ts";
import {parse_html} from "./ui_util.ts";

// Designer-facing experiment surface. Each control writes to a single CSS
// custom property on the document root; we layer the active overrides
// inside one inline rule so a "Reset all" wipes them in one shot. Values
// also persist in localStorage so designers don't lose their tweaks
// across reloads.

type ColorKey =
    | "row_bg"
    | "row_bg_unread"
    | "row_bg_hover"
    | "link"
    | "link_unread";

type LabState = {
    // Each color value is a free-form CSS color string ("" = use default).
    [K in ColorKey as `${K}_light`]: string;
} & {
    [K in ColorKey as `${K}_dark`]: string;
} & {
    unread_font_weight: string;
    read_row_opacity: string;
};

type ColorEntryConfig = {
    key: ColorKey;
    label: string;
    variable: string;
    light_default: string;
    dark_default: string;
};

const LS_KEY = "recent_view_style_lab";
const STYLE_ELEMENT_ID = "recent-view-style-lab-overrides";

const COLOR_ENTRIES: ColorEntryConfig[] = [
    {
        key: "row_bg",
        label: "Read row background",
        variable: "--color-background-recent-view-row",
        light_default: "hsl(0deg 0% 100%)",
        dark_default: "hsl(0deg 0% 14%)",
    },
    {
        key: "row_bg_unread",
        label: "Unread row background",
        variable: "--color-background-recent-view-row-unread",
        light_default: "hsl(0deg 0% 100%)",
        dark_default: "hsl(0deg 0% 14%)",
    },
    {
        key: "row_bg_hover",
        label: "Row hover background",
        variable: "--color-background-recent-view-row-hover",
        light_default: "color-mix(in srgb, hsl(0deg 0% 0%) 5%, hsl(0deg 0% 100%))",
        dark_default: "color-mix(in srgb, hsl(0deg 0% 100%) 5%, hsl(0deg 0% 14%))",
    },
    {
        key: "link",
        label: "Read row text",
        variable: "--color-recent-view-link",
        light_default: "hsl(0deg 0% 20%)",
        dark_default: "hsl(0deg 0% 100% / 75%)",
    },
    {
        key: "link_unread",
        label: "Unread row text",
        variable: "--color-recent-view-link-unread",
        light_default: "hsl(0deg 0% 5%)",
        dark_default: "hsl(0deg 0% 100% / 83%)",
    },
];

function default_state(): LabState {
    return {
        row_bg_light: "",
        row_bg_dark: "",
        row_bg_unread_light: "",
        row_bg_unread_dark: "",
        row_bg_hover_light: "",
        row_bg_hover_dark: "",
        link_light: "",
        link_dark: "",
        link_unread_light: "",
        link_unread_dark: "",
        unread_font_weight: "",
        read_row_opacity: "",
    };
}

function load_state(): LabState {
    const ls = localstorage();
    const raw = ls.get(LS_KEY);
    const merged = default_state();
    if (raw && typeof raw === "object") {
        for (const key of Object.keys(merged) as (keyof LabState)[]) {
            const value = (raw as Record<string, unknown>)[key];
            if (typeof value === "string") {
                merged[key] = value;
            }
        }
    }
    return merged;
}

function save_state(state: LabState): void {
    const ls = localstorage();
    ls.set(LS_KEY, state);
}

function build_css_text(state: LabState): string {
    const lines: string[] = [];
    for (const entry of COLOR_ENTRIES) {
        const light = state[`${entry.key}_light`];
        const dark = state[`${entry.key}_dark`];
        if (!light && !dark) {
            continue;
        }
        const resolved_light = light || entry.light_default;
        const resolved_dark = dark || entry.dark_default;
        lines.push(`    ${entry.variable}: light-dark(${resolved_light}, ${resolved_dark});`);
    }
    if (state.unread_font_weight) {
        lines.push(`    --font-weight-recent-view-row-unread: ${state.unread_font_weight};`);
    }
    if (state.read_row_opacity && state.read_row_opacity !== "1") {
        lines.push(`    --opacity-recent-view-row-read: ${state.read_row_opacity};`);
    }
    if (lines.length === 0) {
        return "";
    }
    return `:root {\n${lines.join("\n")}\n}\n`;
}

function apply_overrides(state: LabState): void {
    let style_element = document.querySelector<HTMLStyleElement>(`#${STYLE_ELEMENT_ID}`);
    if (!style_element) {
        style_element = document.createElement("style");
        style_element.id = STYLE_ELEMENT_ID;
        document.head.append(style_element);
    }
    style_element.textContent = build_css_text(state);
}

// We translate any non-hex CSS color (hsl, color-mix, etc.) into a hex
// best-effort for the <input type=color> swatch by letting the browser
// resolve it via getComputedStyle on a probe element. Returns "#rrggbb".
function resolve_to_hex(css_color: string): string {
    if (/^#[\da-f]{6}$/i.test(css_color)) {
        return css_color.toLowerCase();
    }
    const probe = document.createElement("span");
    probe.style.color = css_color;
    probe.style.display = "none";
    document.body.append(probe);
    const computed = getComputedStyle(probe).color;
    probe.remove();
    const match = /rgba?\(([^)]+)\)/.exec(computed);
    if (!match) {
        return "#000000";
    }
    const parts = match[1]!.split(",").map((part) => Number.parseFloat(part.trim()));
    const [r = 0, g = 0, b = 0] = parts;
    const to_hex = (channel: number): string =>
        Math.max(0, Math.min(255, Math.round(channel))).toString(16).padStart(2, "0");
    return `#${to_hex(r)}${to_hex(g)}${to_hex(b)}`;
}

function build_template_context(state: LabState): unknown {
    const color_entries = COLOR_ENTRIES.map((entry) => {
        const light_value = state[`${entry.key}_light`];
        const dark_value = state[`${entry.key}_dark`];
        return {
            key: entry.key,
            label: entry.label,
            variable: entry.variable,
            light_default: entry.light_default,
            dark_default: entry.dark_default,
            light_value,
            dark_value,
            light_hex: resolve_to_hex(light_value || entry.light_default),
            dark_hex: resolve_to_hex(dark_value || entry.dark_default),
        };
    });
    return {
        color_entries,
        state: {
            unread_font_weight: state.unread_font_weight,
            read_row_opacity: state.read_row_opacity,
            read_row_opacity_or_default: state.read_row_opacity || "1",
        },
    };
}

function update_snippet($popper: JQuery, state: LabState): void {
    const css_text = build_css_text(state);
    $popper
        .find<HTMLTextAreaElement>(".recent-view-style-lab-snippet")
        .val(css_text || "/* No overrides yet — change a control above. */");
}

function bind_events($popper: JQuery, state: LabState): void {
    const handle_change = (): void => {
        save_state(state);
        apply_overrides(state);
        update_snippet($popper, state);
    };

    $popper.on("input change", ".recent-view-style-lab-text", function () {
        const $input = $(this);
        const key = $input.attr("data-key") as ColorKey | undefined;
        const mode = $input.attr("data-mode");
        if (!key || (mode !== "light" && mode !== "dark")) {
            return;
        }
        const value = String($input.val() ?? "").trim();
        state[`${key}_${mode}`] = value;
        // Sync the matching color picker swatch when the value parses.
        const entry = COLOR_ENTRIES.find((candidate) => candidate.key === key);
        if (entry) {
            const default_value = mode === "light" ? entry.light_default : entry.dark_default;
            const $swatch = $popper.find(
                `.recent-view-style-lab-color[data-key="${key}"][data-mode="${mode}"]`,
            );
            $swatch.val(resolve_to_hex(value || default_value));
        }
        handle_change();
    });

    $popper.on("input change", ".recent-view-style-lab-color", function () {
        const $input = $(this);
        const key = $input.attr("data-key") as ColorKey | undefined;
        const mode = $input.attr("data-mode");
        if (!key || (mode !== "light" && mode !== "dark")) {
            return;
        }
        const hex = String($input.val() ?? "");
        state[`${key}_${mode}`] = hex;
        $popper
            .find(`.recent-view-style-lab-text[data-key="${key}"][data-mode="${mode}"]`)
            .val(hex);
        handle_change();
    });

    $popper.on("change", ".recent-view-style-lab-select", function () {
        state.unread_font_weight = String($(this).val() ?? "");
        handle_change();
    });

    $popper.on("input change", ".recent-view-style-lab-range", function () {
        const value = String($(this).val() ?? "");
        state.read_row_opacity = value;
        $popper.find(".recent-view-style-lab-range-value").text(value);
        handle_change();
    });

    $popper.on("click", ".recent-view-style-lab-reset", () => {
        const fresh = default_state();
        for (const key of Object.keys(state) as (keyof LabState)[]) {
            state[key] = fresh[key];
        }
        save_state(state);
        apply_overrides(state);
        // Reset every input back to the default placeholder/swatch state.
        for (const entry of COLOR_ENTRIES) {
            for (const mode of ["light", "dark"] as const) {
                const default_value = mode === "light" ? entry.light_default : entry.dark_default;
                $popper
                    .find(`.recent-view-style-lab-text[data-key="${entry.key}"][data-mode="${mode}"]`)
                    .val("");
                $popper
                    .find(`.recent-view-style-lab-color[data-key="${entry.key}"][data-mode="${mode}"]`)
                    .val(resolve_to_hex(default_value));
            }
        }
        $popper.find(".recent-view-style-lab-select").val("");
        $popper.find(".recent-view-style-lab-range").val("1");
        $popper.find(".recent-view-style-lab-range-value").text("1");
        update_snippet($popper, state);
    });

    $popper.on("click", ".recent-view-style-lab-copy", function () {
        const text = String(
            $popper.find(".recent-view-style-lab-snippet").val() ?? "",
        );
        if (!text || text.startsWith("/*")) {
            return;
        }
        void navigator.clipboard.writeText(text);
        const $button = $(this);
        const original = $button.text();
        $button.text("Copied!");
        setTimeout(() => {
            $button.text(original);
        }, 1200);
    });
}

export function initialize(): void {
    // Apply any persisted overrides immediately on load, before the
    // popover ever opens, so reloads preserve the look the designer
    // last saw.
    const persisted = load_state();
    apply_overrides(persisted);

    popover_menus.register_popover_menu("#recent-view-style-lab", {
        theme: "popover-menu",
        placement: "bottom",
        offset: popover_menus.NAVBAR_POPOVER_OFFSET,
        popperOptions: {
            strategy: "fixed",
            modifiers: [
                {
                    name: "eventListeners",
                    options: {
                        scroll: false,
                    },
                },
            ],
        },
        onShow(instance) {
            const state = load_state();
            instance.setContent(
                parse_html(render_navbar_recent_view_style_lab(build_template_context(state))),
            );
            $("#recent-view-style-lab").addClass("active-navbar-menu");
            const $popper = $(instance.popper);
            bind_events($popper, state);
            update_snippet($popper, state);
        },
        onHidden(instance) {
            instance.destroy();
            $("#recent-view-style-lab").removeClass("active-navbar-menu");
        },
    });
}
