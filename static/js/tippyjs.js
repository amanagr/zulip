"use strict";

const tippy = require('tippy.js').default;
const delegate = require('tippy.js').delegate;
window.tippy = tippy;


tippy.setDefaultProps({
        maxWidth: 300,
        allowHTML: true,
        delay: [50, 100],
        placement: 'auto',
        animation: 'scale',
        inertia: true,
});

exports.initialize = function () {
    delegate('html', {
        // Add elements here which are not displayed on
        // initial load but are displayed later through
        // some means.
        //
        // Make all html elements having this class
        // show tippy styled tooltip on hover.
        target: '.tippy-zulip-tooltip',
    });
};

window.tippyjs = exports;
