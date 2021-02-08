"use strict";

const tippy = require('tippy.js').default;
const delegate = require('tippy.js').delegate;
const hideAll = require('tippy.js').hideAll;
window.tippy = tippy;

tippy.setDefaultProps({
        maxWidth: 300,
        delay: [50, 50],
        placement: 'auto',
        animation: 'scale',
        inertia: true,
        allowHTML: true,
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

exports.hide_all = function () {
    hideAll({duration: 0});
};

window.tippyjs = exports;
