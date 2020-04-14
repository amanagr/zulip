const render_recent_topics_body = require('../templates/recent_topics_list.hbs');

const topics = new Map(); // Key is stream-id:topic.

exports.process_messages = function (messages) {
    messages.forEach(exports.process_message);
};

function reduce_message(msg) {
    return {
        id: msg.id,
        timestamp: msg.timestamp,
        stream_id: msg.stream_id,
        stream_name: msg.stream,
        topic: msg.topic,
        sender_id: msg.sender_id,
        type: msg.type,
    };
}

exports.process_message = function (msg) {
    const is_ours = people.is_my_user_id(msg.sender_id);
    const is_relevant = is_ours && msg.type === 'stream';
    const key = msg.stream_id + ':' + msg.topic;
    const topic = topics.get(key);
    if (topic === undefined && !is_relevant) {
        return false;
    }
    if (!topic) {
        topics.set(key, {
            our_last_msg: reduce_message(msg),
            last_msg: reduce_message(msg),
        });
        return true;
    }
    // Update last messages sent to topic.
    if (is_ours && topic.our_last_msg.timestamp <= msg.timestamp) {
        topic.our_last_msg = reduce_message(msg);
    }
    if (topic.last_msg.timestamp <= msg.timestamp) {
        topic.last_msg = reduce_message(msg);
    }
    topics.set(key, topic);
    return true;
};

function get_sorted_topics() {
    // Sort all recent topics by last message time.
    return new Map([...topics.entries()].sort(function (a, b) {
        if (a[1].last_msg.timestamp > b[1].last_msg.timestamp) {
            return 1;
        } else if (a[1].last_msg.timestamp < b[1].last_msg.timestamp) {
            return -1;
        }
        return 0;
    })[0]);
}

exports.get = function () {
    return get_sorted_topics();
};

function format_values() {
    const topics_array = [];
    exports.get().forEach(function (elem, key) {
        const stream_name = elem.last_msg.stream_name;
        const stream_id = parseInt(key.split(':')[0], 10);
        const topic = key.split(':')[1];
        const time = new XDate(elem.last_msg.timestamp * 1000);
        let time_stamp = timerender.render_now(time).time_str;
        if (time_stamp === i18n.t("Today")) {
            time_stamp = timerender.stringify_time(time);
        }
        topics_array.push({
            stream_id: stream_id,
            stream_name: stream_name,
            topic: topic,
            unread_count: unread.unread_topic_counter.get(stream_id, topic),
            stream_color: stream_data.get_color(stream_name),
            timestamp: time_stamp,
            stream_url: hash_util.by_stream_uri(stream_id),
            topic_url: hash_util.by_stream_topic_uri(stream_id, topic),
        });
    });
    return topics_array;
}

exports.update = function () {
    const rendered = render_recent_topics_body({
        recent_topics: format_values(),
    });
    $('#recent_topics_table').html(rendered);
};

exports.launch = function () {
    const rendered = render_recent_topics_body({
        recent_topics: format_values(),
    });
    $('#recent_topics_table').html(rendered);

    overlays.open_overlay({
        name: 'recents',
        overlay: $('#recent_overlay'),
        on_close: function () {
            hashchange.exit_overlay();
        },
    });
};

window.recent_topics = exports;
