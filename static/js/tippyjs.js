"use strict";

import tippy from 'tippy.js';
import {delegate, hideAll} from 'tippy.js';
window.tippy = tippy;

tippy.setDefaultProps({
        maxWidth: 300,
        delay: [50, 50],
        placement: 'auto',
        animation: 'scale',
        inertia: true,
        allowHTML: true,
});

export function initialize () {
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

export function hide_all () {
    hideAll({duration: 0});
};
