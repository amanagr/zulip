const render_recent_topics_body = require('../templates/recent_topics_list.hbs');


let topics = new Map(); // Key is stream-id:subject.

exports.process_all_messages = function () {
    exports.process_messages(message_list.all.all_messages());
};

exports.process_messages = function (messages) {
    messages.forEach(exports.process_message);
};

function reduce_message(msg) {
    return {
        id: msg.id,
        stream_name: msg.stream,
        timestamp: msg.timestamp,
        stream_id: msg.stream_id,
        subject: msg.subject,
        sender_id: msg.sender_id,
        unread: msg.unread,
        type: msg.type,
    };
}

exports.process_message = function (msg) {
    const is_ours = people.is_my_user_id(msg.sender_id);
    const is_relevant = is_ours && msg.type === 'stream';
    const key = msg.stream_id + ':' + msg.subject;
    const topic = topics.get(key);
    if (topic === undefined && !is_relevant) {
        return false;
    }
    if (!topic) {
        topics.set(key, {
            our_last_msg: reduce_message(msg),
            last_msg: reduce_message(msg),
            read: true,
        });
        return true;
    }
    // Update last messages sent to topic.
    if (is_ours && topic.our_last_msg.timestamp <= msg.timestamp) {
        topic.our_last_msg = reduce_message(msg);
    }
    if (topic.last_msg.timestamp <= msg.timestamp) {
        topic.last_msg = reduce_message(msg);
        if (msg.unread) {
            topic.read = false;
        } else {
            topic.read = true;
        }
    }
    topics.set(key, topic);
    return true;
};

function get_sorted_topics() {
    // Sort all recent topics by last message time.
    topics = new Map([...topics.entries()].sort(function (a, b) {
        if (a[1].last_msg.timestamp > b[1].last_msg.timestamp) {
            return 1;
        } else if (a[1].last_msg.timestamp < b[1].last_msg.timestamp) {
            return -1;
        }
        return 0;
    })[0]);
    return topics;
}

function map_topics(new_topics) {
    const mapped_topics = new Map();
    new_topics.forEach(function (elem, key) {
        mapped_topics.set(key, {
            read: elem.read,
            our_last_msg_id: elem.our_last_msg.id,
            last_msg_id: elem.last_msg.id,
        });
    });
    return mapped_topics;
}

exports.get = function () {
    return map_topics(get_sorted_topics());
};

exports.get_relevant = function () {
    // Return only those topics where someone else has replied.
    const all_topics = get_sorted_topics();
    const updated_topics = new Map();
    all_topics.forEach(function (elem, key) {
        if (elem.last_msg !== elem.our_last_msg && !elem.read) {
            updated_topics.set(key, elem);
        }
    });
    return map_topics(updated_topics);
};

exports.get_unread_count = function get_unread_count() {
    let count = 0;
    topics.forEach(function (elem) {
        count += unread.unread_topic_counter.get(
            elem.our_last_msg.stream_id, elem.our_last_msg.subject);
    });
    return count;
};

exports.launch = function () {

    function format_values() {
        const topics_array = Array();
        topics.forEach(function (elem, key) {
            const stream_name = elem.last_msg.stream_name;
            topics_array.push({
                stream_id: key.split(':')[0],
                stream_name: stream_name,
                topic: key.split(':')[1],
                unread_count:
                    unread.unread_topic_counter.get(elem.last_msg.stream_id,
                                                    elem.last_msg.subject),
                stream_color: stream_data.get_color(stream_name),
                timestamp: elem.last_msg.timestamp,
            });
        });
        return topics_array;
    }

    // console.log('HELLO');
    $('#recents_table').empty();
    const rendered = render_recent_topics_body({
        recent_topics: format_values(),
    });

    $('#recents_table').append(rendered);
    overlays.open_overlay({
        name: 'recents',
        overlay: $('#recent_overlay'),
        on_close: function () {
            hashchange.exit_overlay();
        },
    });
};


window.recent_topics = exports;
