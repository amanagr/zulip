"use strict";

const {strict: assert} = require("assert");

const {mock_esm, set_global, zrequire} = require("./lib/namespace");
const {run_test} = require("./lib/test");
const $ = require("./lib/zjquery");

set_global("Image", class Image {});
mock_esm("../src/overlays", {
    close_overlay() {},

    close_active() {},
    open_overlay() {},
});
mock_esm("../src/popovers", {
    hide_all() {},
});
const rows = mock_esm("../src/rows");

const message_store = mock_esm("../src/message_store");

const lightbox = zrequire("lightbox");

function test(label, f) {
    run_test(label, (helpers) => {
        lightbox.clear_for_testing();
        f(helpers);
    });
}

test("pan_and_zoom", ({override}) => {
    const $img = $.create("img-stub");
    const $link = $.create("link-stub");

    $img.closest = () => [];

    $img.set_parent($link);

    override(rows, "get_message_id", ($row) => {
        assert.equal($row, $img);
        return 1234;
    });

    $img.attr("src", "example");

    let fetched_message_id;

    message_store.get = (message_id) => {
        fetched_message_id = message_id;
        return "message-stub";
    };

    $.create(
        ".focused-message-list .message_inline_image img, .focused-message-list .message_inline_video video",
        {children: []},
    );
    const open_image = lightbox.build_open_media_function();
    open_image($img);

    assert.equal(fetched_message_id, 1234);
});

test("youtube", ({override}) => {
    const href = "https://youtube.com/some-random-clip";
    const $img = $.create("img-stub");
    const $link = $.create("link-stub");

    override(rows, "get_message_id", ($row) => {
        assert.equal($row, $img);
        return 4321;
    });

    $img.attr("src", href);

    $img.closest = (sel) => {
        if (sel === ".youtube-video") {
            // We just need a nonempty array to
            // set is_youtube_video to true.
            return ["whatever"];
        }
        return [];
    };

    $img.set_parent($link);
    $link.attr("href", href);

    $.create(
        ".focused-message-list .message_inline_image img, .focused-message-list .message_inline_video video",
        {children: []},
    );

    const open_image = lightbox.build_open_media_function();
    open_image($img);
    assert.equal($(".media-actions .open").attr("href"), href);
});
