const render_recent_topics_body = require('../templates/recent_topics_list.hbs');

const topics = new Map(); // Key is stream-id:topic.
const MAX_AVATAR = 3;  // Number of avatars to display

exports.process_messages = function (messages) {
    messages.forEach(exports.process_message);
    exports.update_muted_topics();
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

exports.process_topic = function (stream_id, topic) {
    topics.delete(stream_id + ':' + topic);
    const msgs = message_list.all.all_messages().filter(x => {
        return x.type === 'stream' &&
               x.stream_id === stream_id &&
               x.topic === topic;
    });
    exports.process_messages(msgs);
};

exports.process_message = function (msg) {
    const is_ours = people.is_my_user_id(msg.sender_id);
    // only process stream msgs in which current user's msg is present.
    const is_relevant = is_ours && msg.type === 'stream';
    const key = msg.stream_id + ':' + msg.topic;
    const topic = topics.get(key);
    // Process msg if it's not user's but we are tracking the topic.
    if (topic === undefined && !is_relevant) {
        return false;
    }
    // Add new topic if msg is_relevant
    if (!topic) {
        topics.set(key, {
            our_last_msg: reduce_message(msg),
            last_msg: reduce_message(msg),
            senders: [msg.sender_id],
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
    // Maintain sender_ids in order of msgs
    const sender = msg.sender_id;
    if (topic.senders.indexOf(sender) !== -1) {
        topic.senders.splice(topic.senders.indexOf(sender), 1);
    }
    topic.senders.push(sender);

    topics.set(key, topic);
    return true;
};

function get_sorted_topics() {
    // Sort all recent topics by last message time.
    return new Map(Array.from(topics.entries()).sort(function (a, b) {
        if (a[1].last_msg.timestamp > b[1].last_msg.timestamp) {
            return -1;
        } else if (a[1].last_msg.timestamp < b[1].last_msg.timestamp) {
            return 1;
        }
        return 0;
    }));
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

        // Display in most recent sender first order
        const senders = [...elem.senders].reverse().slice(0, MAX_AVATAR);
        const senders_info = [];
        senders.forEach((id) => {
            senders_info.push(people.get_by_user_id(id));
        });
        let time_stamp = timerender.render_now(time).time_str;
        if (time_stamp === i18n.t("Today")) {
            time_stamp = timerender.stringify_time(time);
        }
        topics_array.push({
            stream_id: stream_id,
            stream_name: stream_name,
            topic: topic,
            unread_count: unread.unread_topic_counter.get(stream_id, topic),
            timestamp: time_stamp,
            stream_url: hash_util.by_stream_uri(stream_id),
            topic_url: hash_util.by_stream_topic_uri(stream_id, topic),
            senders: senders_info,
            count_senders: Math.max(0, elem.senders.length - MAX_AVATAR),
        });
    });
    return topics_array;
}

exports.update_muted_topics = function () {
    for (const tup of muting.get_muted_topics()) {
        const m_stream_id = tup[0];
        const m_topic = tup[1];
        topics.delete(m_stream_id + ':' + m_topic);
    }
    exports.update();
};

exports.update = function () {
    const rendered_body = render_recent_topics_body({
        recent_topics: format_values(),
    });
    $('#recent_topics_table').html(rendered_body);
};

exports.launch = function () {
    exports.update();

    overlays.open_overlay({
        name: 'recents',
        overlay: $('#recent_overlay'),
        on_close: function () {
            hashchange.exit_overlay();
        },
    });
};

window.recent_topics = exports;
