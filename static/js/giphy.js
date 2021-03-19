import {renderGrid} from "@giphy/js-components";
import {GiphyFetch} from "@giphy/js-fetch-api";
import $ from "jquery";
import {throttle} from "throttle-debounce";

import render_giphy_picker from "../templates/giphy_picker.hbs";

import * as compose_ui from "./compose_ui";

const gf = new GiphyFetch(page_params.giphy_api_key);
let search_term = "";

function fetchGifs(offset) {
    const config = {
        offset,
        limit: 25,
    };
    if (search_term === "") {
        // Get the trending gifs by default.
        return gf.trending(config);
    }
    return gf.search(search_term, config);
}

export function renderGIPHYGrid(targetEl) {
    const render = () =>
        // See https://github.com/Giphy/giphy-js/blob/master/packages/components/README.md#grid
        // for detailed documentation.
        renderGrid(
            {
                width: 300,
                fetchGifs,
                columns: 3,
                gutter: 6,
                noLink: true,
                // Hide the user attribution that appears over a GIF
                hideAttribution: true,
                onGifClick: (props) => {
                    $("#compose_box_giphy_grid").popover("hide");
                    // TODO: Decide whether to include the search term here or not based on
                    // feedback.
                    compose_ui.insert_syntax_and_focus(`[](${props.images.downsized_medium.url})`);
                },
            },
            targetEl,
        );

    // This basically limits the rate at which render
    // can be called to only one call every 500ms unless
    // it is the last call.
    // See https://www.npmjs.com/package/throttle-debounce#throttledelay-notrailing-callback-debouncemode
    const resizeRender = throttle(500, render);
    window.addEventListener("resize", resizeRender, false);
    const remove = render();
    return {
        remove: () => {
            remove();
            window.removeEventListener("resize", resizeRender, false);
        },
    };
}

let template = render_giphy_picker();

if (window.innerWidth <= 768) {
    // Show as modal in the center for small screens.
    template = "<div class='popover-flex'>" + template + "</div>";
}

$("#compose_box_giphy_grid").popover({
    animation: true,
    placement: "top",
    html: true,
    trigger: "manual",
    template,
});

export function update_grid_with_search_term() {
    search_term = $("#giphy-search-query")[0].value;
    return renderGIPHYGrid($("#giphy_grid_in_popover .popover-content")[0]);
}
