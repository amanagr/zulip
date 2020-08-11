"use strict";

const util = require("./util");
// Miscellaneous early setup.

$(() => {
    if (util.is_mobile()) {
        // Disable the tutorial; it's ugly on mobile.
        page_params.needs_tutorial = false;
    }

    page_params.page_load_time = new Date().getTime();

    // Display loading indicator.  This disappears after the first
    // get_events completes.
    if (!page_params.needs_tutorial) {
        loading.make_indicator($("#page_loading_indicator"), {
            text: "Loading...",
            abs_positioned: true,
        });
    }

    // This is an issue fix where in jQuery v3 the result of outerHeight on a node
    // that doesn’t exist is now “undefined” rather than “null”, which means it
    // will no longer cast to a Number but rather NaN. For this, we create the
    // `safeOuterHeight` and `safeOuterWidth` functions to safely return a result
    // (or 0).
    $.fn.safeOuterHeight = function (...args) {
        return this.outerHeight(...args) || 0;
    };

    $.fn.safeOuterWidth = function (...args) {
        return this.outerWidth(...args) || 0;
    };

    // For some reason, jQuery wants this to be attached to an element.
    $(document).ajaxError((event, xhr) => {
        if (xhr.status === 401) {
            if (page_params.is_web_public_guest) {
                // If a web public guest (by default in logged out mode) wants to
                // access a feature which is only allowed for logged in users, we ask
                // user to login.
                // TODO: Add a server setting to control this. Some realms might want to
                // just show that this feature is not accessible to web-public guests.
                console.log("401", event);
                alert("LOGIN");
            } else {
                // We got logged out somehow, perhaps from another window or a session timeout.
                // We could display an error message, but jumping right to the login page seems
                // smoother and conveys the same information.
                window.location.replace(page_params.login_page);
            }
        }
    });

    if (typeof $ !== "undefined") {
        $.fn.expectOne = function () {
            if (blueslip && this.length !== 1) {
                blueslip.error("Expected one element in jQuery set, " + this.length + " found");
            }
            return this;
        };

        $.fn.within = function (sel) {
            return $(this).is(sel) || $(this).closest(sel).length;
        };
    }
});
