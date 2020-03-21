const topics = new Map(); // Key is stream-id:topic.

exports.process_messages = function (messages) {
    messages.forEach(exports.process_message);
};

function reduce_message(msg) {
    return {
        id: msg.id,
        timestamp: msg.timestamp,
        stream_id: msg.stream_id,
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

window.recent_topics = exports;
