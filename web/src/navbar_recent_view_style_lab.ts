import $ from "jquery";
import * as z from "zod/mini";

import render_navbar_recent_view_style_lab from "../templates/popovers/navbar/navbar_recent_view_style_lab_popover.hbs";

import {$t} from "./i18n.ts";
import {localstorage} from "./localstorage.ts";
import * as popover_menus from "./popover_menus.ts";
import {parse_html} from "./ui_util.ts";

// Designer-facing experiment surface. Each control writes to a single CSS
// custom property on the document root; we layer the active overrides
// inside one inline rule so a "Reset all" wipes them in one shot. Values
// also persist in localStorage so designers don't lose their tweaks
// across reloads.

const COLOR_KEYS = [
    "row_bg",
    "row_bg_unread",
    "row_bg_hover",
    "row_bg_unread_hover",
    "link",
    "link_unread",
] as const;
type ColorKey = (typeof COLOR_KEYS)[number];
const COLOR_KEY_SET: ReadonlySet<string> = new Set<string>(COLOR_KEYS);
function is_color_key(value: unknown): value is ColorKey {
    return typeof value === "string" && COLOR_KEY_SET.has(value);
}

const OPACITY_KEYS = [
    "read_row_opacity",
    "read_topic_opacity",
    "unread_topic_opacity",
    "read_channel_opacity",
    "unread_channel_opacity",
    "read_time_opacity",
    "unread_time_opacity",
] as const;
type OpacityKey = (typeof OPACITY_KEYS)[number];
const OPACITY_KEY_SET: ReadonlySet<string> = new Set<string>(OPACITY_KEYS);
function is_opacity_key(value: unknown): value is OpacityKey {
    return typeof value === "string" && OPACITY_KEY_SET.has(value);
}

type LabState = {
    [K in ColorKey as `${K}_light`]: string;
} & {
    [K in ColorKey as `${K}_dark`]: string;
} & Record<OpacityKey, string> & {
        read_font_weight: string;
        unread_font_weight: string;
    };

type ColorEntryConfig = {
    key: ColorKey;
    label: string;
    variable: string;
    light_default: string;
    dark_default: string;
};

type OpacityEntryConfig = {
    key: OpacityKey;
    label: string;
    variable: string;
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
        label: "Read row hover background",
        variable: "--color-background-recent-view-row-hover",
        light_default: "color-mix(in srgb, hsl(0deg 0% 0%) 5%, hsl(0deg 0% 100%))",
        dark_default: "color-mix(in srgb, hsl(0deg 0% 100%) 5%, hsl(0deg 0% 14%))",
    },
    {
        key: "row_bg_unread_hover",
        label: "Unread row hover background",
        variable: "--color-background-recent-view-row-unread-hover",
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

const OPACITY_ENTRIES: OpacityEntryConfig[] = [
    {
        key: "read_row_opacity",
        label: "Read row (whole)",
        variable: "--opacity-recent-view-row-read",
    },
    {
        key: "read_topic_opacity",
        label: "Read topic",
        variable: "--opacity-recent-view-row-read-topic",
    },
    {
        key: "unread_topic_opacity",
        label: "Unread topic",
        variable: "--opacity-recent-view-row-unread-topic",
    },
    {
        key: "read_channel_opacity",
        label: "Read channel",
        variable: "--opacity-recent-view-row-read-channel",
    },
    {
        key: "unread_channel_opacity",
        label: "Unread channel",
        variable: "--opacity-recent-view-row-unread-channel",
    },
    {
        key: "read_time_opacity",
        label: "Read time",
        variable: "--opacity-recent-view-row-read-time",
    },
    {
        key: "unread_time_opacity",
        label: "Unread time",
        variable: "--opacity-recent-view-row-unread-time",
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
        row_bg_unread_hover_light: "",
        row_bg_unread_hover_dark: "",
        link_light: "",
        link_dark: "",
        link_unread_light: "",
        link_unread_dark: "",
        read_font_weight: "",
        unread_font_weight: "",
        read_row_opacity: "",
        read_topic_opacity: "",
        unread_topic_opacity: "",
        read_channel_opacity: "",
        unread_channel_opacity: "",
        read_time_opacity: "",
        unread_time_opacity: "",
    };
}

const lab_state_schema = z.object({
    row_bg_light: z.string(),
    row_bg_dark: z.string(),
    row_bg_unread_light: z.string(),
    row_bg_unread_dark: z.string(),
    row_bg_hover_light: z.string(),
    row_bg_hover_dark: z.string(),
    row_bg_unread_hover_light: z.string(),
    row_bg_unread_hover_dark: z.string(),
    link_light: z.string(),
    link_dark: z.string(),
    link_unread_light: z.string(),
    link_unread_dark: z.string(),
    read_font_weight: z.string(),
    unread_font_weight: z.string(),
    read_row_opacity: z.string(),
    read_topic_opacity: z.string(),
    unread_topic_opacity: z.string(),
    read_channel_opacity: z.string(),
    unread_channel_opacity: z.string(),
    read_time_opacity: z.string(),
    unread_time_opacity: z.string(),
});

type Preset = {
    id: string;
    name: string;
    rationale: string;
    values: LabState;
};

// Six curated presets distilled from the recent-view design thread, each
// representing a distinct philosophical direction. Empty strings mean
// "leave the default alone" so the snippet output stays minimal.
function preset(partial: Partial<LabState>): LabState {
    return {...default_state(), ...partial};
}

const PRESETS: Preset[] = [
    {
        id: "default",
        name: "Default",
        rationale: "The current shipped values — useful as a reset.",
        values: preset({}),
    },
    {
        id: "snir-blue",
        name: "Snir's Blue",
        rationale: "Restore the old vibrant blue energy on unreads (Snir's custom-CSS override).",
        values: preset({
            row_bg_light: "hsl(0deg 0% 96%)",
            row_bg_dark: "hsl(0deg 0% 11%)",
            row_bg_unread_light: "hsl(212deg 60% 92%)",
            row_bg_unread_dark: "hsl(212deg 30% 22% / 40%)",
            row_bg_hover_light: "hsl(208deg 26% 88%)",
            row_bg_hover_dark: "hsl(208deg 26% 11% / 60%)",
            link_light: "hsl(206deg 60% 30%)",
            link_dark: "hsl(206deg 89% 74%)",
            link_unread_light: "hsl(206deg 89% 28%)",
            link_unread_dark: "hsl(206deg 89% 80%)",
            unread_font_weight: "500",
        }),
    },
    {
        id: "gmail-bold",
        name: "Gmail bold",
        rationale: "Keep neutral backgrounds, distinguish unreads purely by weight + darker text.",
        values: preset({
            link_light: "hsl(0deg 0% 38%)",
            link_dark: "hsl(0deg 0% 100% / 60%)",
            link_unread_light: "hsl(0deg 0% 0%)",
            link_unread_dark: "hsl(0deg 0% 100%)",
            unread_font_weight: "600",
        }),
    },
    {
        id: "calm-unreads",
        name: "Calm unreads",
        rationale:
            "Tim: bold + saturated unreads feel like being shouted at when filtered to unread-only. Lean on the left marker bar; text + bg stay calm at normal weight.",
        values: preset({
            link_unread_light: "hsl(0deg 0% 15%)",
            link_unread_dark: "hsl(0deg 0% 100% / 80%)",
            unread_font_weight: "400",
        }),
    },
    {
        id: "faded-reads",
        name: "Faded reads",
        rationale:
            "Read rows recede via opacity, no chromatic change; unreads pop without a 'gray wall'.",
        values: preset({
            link_unread_light: "hsl(0deg 0% 0%)",
            link_unread_dark: "hsl(0deg 0% 100% / 95%)",
            unread_font_weight: "500",
            read_row_opacity: "0.55",
        }),
    },
    {
        id: "inbox-inverted",
        name: "Inbox inverted",
        rationale:
            "Reads dim to sidebar gray; unreads stay clean white. Matches the Inbox-view metaphor.",
        values: preset({
            row_bg_light: "hsl(0deg 0% 94%)",
            row_bg_dark: "hsl(0deg 0% 11%)",
            row_bg_unread_light: "hsl(0deg 0% 100%)",
            row_bg_unread_dark: "hsl(0deg 0% 18%)",
            row_bg_hover_light: "hsl(0deg 0% 88%)",
            row_bg_hover_dark: "hsl(0deg 0% 22%)",
            link_light: "hsl(0deg 0% 35%)",
            link_dark: "hsl(0deg 0% 100% / 65%)",
            link_unread_light: "hsl(0deg 0% 5%)",
            link_unread_dark: "hsl(0deg 0% 100% / 95%)",
            unread_font_weight: "500",
        }),
    },
    {
        id: "subtle-greys",
        name: "Subtle greys",
        rationale: "The 'less blue, more grey, consistent with Zulip' calm direction.",
        values: preset({
            row_bg_light: "hsl(0deg 0% 100%)",
            row_bg_dark: "hsl(0deg 0% 14%)",
            row_bg_unread_light: "hsl(0deg 0% 96%)",
            row_bg_unread_dark: "hsl(0deg 0% 19%)",
            row_bg_hover_light: "hsl(0deg 0% 92%)",
            row_bg_hover_dark: "hsl(0deg 0% 23%)",
            link_dark: "hsl(0deg 0% 100% / 70%)",
            link_unread_dark: "hsl(0deg 0% 100% / 90%)",
            unread_font_weight: "500",
        }),
    },
    {
        id: "done-green",
        name: "Done green",
        rationale: "Tint reads with a soft 'success / you're done' green; unreads stay crisp.",
        values: preset({
            row_bg_light: "hsl(140deg 30% 95%)",
            row_bg_dark: "hsl(150deg 14% 13%)",
            row_bg_unread_light: "hsl(0deg 0% 100%)",
            row_bg_unread_dark: "hsl(0deg 0% 18%)",
            row_bg_hover_light: "hsl(140deg 30% 90%)",
            row_bg_hover_dark: "hsl(150deg 14% 18%)",
            link_light: "hsl(140deg 20% 28%)",
            link_dark: "hsl(140deg 12% 75%)",
            link_unread_light: "hsl(0deg 0% 5%)",
            link_unread_dark: "hsl(0deg 0% 100% / 95%)",
            unread_font_weight: "500",
        }),
    },
];

function load_state(): LabState {
    const ls = localstorage();
    const raw = ls.get(LS_KEY);
    if (raw === undefined) {
        return default_state();
    }
    const parsed = lab_state_schema.safeParse(raw);
    if (!parsed.success) {
        // Stored value doesn't match the current schema (older version,
        // tampered, or corrupt). Drop it so we don't keep parsing the
        // same garbage on every load.
        ls.remove(LS_KEY);
        return default_state();
    }
    return parsed.data;
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
    if (state.read_font_weight) {
        lines.push(`    --font-weight-recent-view-row-read: ${state.read_font_weight};`);
    }
    if (state.unread_font_weight) {
        lines.push(`    --font-weight-recent-view-row-unread: ${state.unread_font_weight};`);
    }
    for (const entry of OPACITY_ENTRIES) {
        const value = state[entry.key];
        if (value && value !== "1") {
            lines.push(`    ${entry.variable}: ${value};`);
        }
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
        Math.max(0, Math.min(255, Math.round(channel)))
            .toString(16)
            .padStart(2, "0");
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
    const opacity_entries = OPACITY_ENTRIES.map((entry) => ({
        key: entry.key,
        label: entry.label,
        variable: entry.variable,
        value: state[entry.key] || "1",
    }));
    return {
        presets: PRESETS.map(({id, name, rationale}) => ({id, name, rationale})),
        color_entries,
        opacity_entries,
        state: {
            read_font_weight: state.read_font_weight,
            unread_font_weight: state.unread_font_weight,
        },
    };
}

function update_snippet($popper: JQuery, state: LabState): void {
    const css_text = build_css_text(state);
    $popper
        .find<HTMLTextAreaElement>(".recent-view-style-lab-snippet")
        .val(css_text || "/* No overrides yet — change a control above. */");
}

function sync_inputs($popper: JQuery, state: LabState): void {
    for (const entry of COLOR_ENTRIES) {
        for (const mode of ["light", "dark"] as const) {
            const default_value = mode === "light" ? entry.light_default : entry.dark_default;
            const value = state[`${entry.key}_${mode}`];
            $popper
                .find(`.recent-view-style-lab-text[data-key="${entry.key}"][data-mode="${mode}"]`)
                .val(value);
            $popper
                .find(`.recent-view-style-lab-color[data-key="${entry.key}"][data-mode="${mode}"]`)
                .val(resolve_to_hex(value || default_value));
        }
    }
    $popper
        .find('.recent-view-style-lab-select[data-key="read_font_weight"]')
        .val(state.read_font_weight);
    $popper
        .find('.recent-view-style-lab-select[data-key="unread_font_weight"]')
        .val(state.unread_font_weight);
    for (const entry of OPACITY_ENTRIES) {
        const value = state[entry.key] || "1";
        $popper.find(`.recent-view-style-lab-range[data-key="${entry.key}"]`).val(value);
        $popper.find(`.recent-view-style-lab-range-value[data-key="${entry.key}"]`).text(value);
    }
}

function bind_events($popper: JQuery, state: LabState): void {
    const handle_change = (): void => {
        save_state(state);
        apply_overrides(state);
        update_snippet($popper, state);
    };

    $popper.on("input change", ".recent-view-style-lab-text", function () {
        const $input = $(this);
        const key = $input.attr("data-key");
        const mode = $input.attr("data-mode");
        if (!is_color_key(key) || (mode !== "light" && mode !== "dark")) {
            return;
        }
        const value = String($input.val() ?? "").trim();
        state[`${key}_${mode}`] = value;
        const entry = COLOR_ENTRIES.find((candidate) => candidate.key === key);
        if (entry) {
            const default_value = mode === "light" ? entry.light_default : entry.dark_default;
            $popper
                .find(`.recent-view-style-lab-color[data-key="${key}"][data-mode="${mode}"]`)
                .val(resolve_to_hex(value || default_value));
        }
        handle_change();
    });

    $popper.on("input change", ".recent-view-style-lab-color", function () {
        const $input = $(this);
        const key = $input.attr("data-key");
        const mode = $input.attr("data-mode");
        if (!is_color_key(key) || (mode !== "light" && mode !== "dark")) {
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
        const $input = $(this);
        const key = $input.attr("data-key");
        if (key === "read_font_weight" || key === "unread_font_weight") {
            state[key] = String($input.val() ?? "");
            handle_change();
        }
    });

    $popper.on("input change", ".recent-view-style-lab-range", function () {
        const $input = $(this);
        const key = $input.attr("data-key");
        if (!is_opacity_key(key)) {
            return;
        }
        const value = String($input.val() ?? "");
        state[key] = value;
        $popper.find(`.recent-view-style-lab-range-value[data-key="${key}"]`).text(value);
        handle_change();
    });

    $popper.on("click", ".recent-view-style-lab-preset", function () {
        const preset_id = $(this).attr("data-preset-id");
        const matching_preset = PRESETS.find((candidate) => candidate.id === preset_id);
        if (!matching_preset) {
            return;
        }
        Object.assign(state, matching_preset.values);
        save_state(state);
        apply_overrides(state);
        sync_inputs($popper, state);
        $popper
            .find(".recent-view-style-lab-preset")
            .removeClass("recent-view-style-lab-preset-active");
        $(this).addClass("recent-view-style-lab-preset-active");
        update_snippet($popper, state);
    });

    $popper.on("click", ".recent-view-style-lab-reset", () => {
        Object.assign(state, default_state());
        save_state(state);
        apply_overrides(state);
        sync_inputs($popper, state);
        $popper
            .find(".recent-view-style-lab-preset")
            .removeClass("recent-view-style-lab-preset-active");
        update_snippet($popper, state);
    });

    $popper.on("click", ".recent-view-style-lab-copy", function () {
        const text = String($popper.find(".recent-view-style-lab-snippet").val() ?? "");
        if (!text || text.startsWith("/*")) {
            return;
        }
        void navigator.clipboard.writeText(text);
        const $button = $(this);
        const original = $button.text();
        $button.text($t({defaultMessage: "Copied!"}));
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
