"use strict";

const {media_breakpoints, font_sizes} = require("./static/js/css_variables.js");

module.exports = {
    plugins: {
        // Warning: despite appearances, order is significant
        "postcss-nested": {},
        "postcss-extend-rule": {},
        "postcss-simple-vars": {
            variables: { ...media_breakpoints, ...font_sizes},
        },
        "postcss-calc": {},
        autoprefixer: {},
    },
};
