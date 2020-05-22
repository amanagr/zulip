exports.ids = new Set();

exports.initialize = function () {
    exports.ids.clear();

    for (const id of page_params.starred_messages) {
        exports.ids.add(id);
    }

    exports.rerender_ui();
};

exports.add = function (ids) {
    for (const id of ids) {
        exports.ids.add(id);
    }

    exports.rerender_ui();
};

exports.remove = function (ids) {
    for (const id of ids) {
        exports.ids.delete(id);
    }

    exports.rerender_ui();
};

exports.count = function () {
    return exports.ids.size;
};

exports.get_starred_msg_ids = function () {
    return Array.from(exports.ids);
};

exports.unstar_topic = function (stream_id, topic) {
    for (const msg_id of exports.get_starred_msg_ids()) {
        const message = message_store.get(msg_id);
        if (message.stream_id === stream_id &&
                message.topic.toLowerCase() === topic.toLowerCase()) {
            message_flags.toggle_starred_and_update_server(message);
        }
    }
};

exports.is_topic_starred = function (stream_id, topic) {
    for (const msg_id of exports.get_starred_msg_ids()) {
        const message = message_store.get(msg_id);
        if (message.stream_id === stream_id &&
                message.topic.toLowerCase() === topic.toLowerCase()) {
            return true;
        }
    }
    return false;
};

exports.rerender_ui = function () {
    let count = exports.count();

    if (!page_params.starred_message_counts) {
        // This essentially hides the count
        count = 0;
    }

    top_left_corner.update_starred_count(count);
};

window.starred_messages = exports;
