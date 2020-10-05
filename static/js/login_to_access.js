import $ from "jquery";

import render_login_to_access_modal from "../templates/login_to_access.hbs";

export function show() {
    // Hide all overlays, popover and go back to the previous hash if the
    // hash has changed.
    $("#login-to-access-modal-holder").html(render_login_to_access_modal);
    $("#login_to_access_modal").modal("show");
}
