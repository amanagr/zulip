let topics = new Map(); // Key is stream-id:topic.

exports.process_messages = function (messages) {
    messages.forEach(exports.process_message);
};

function reduce_message(msg) {
    // Remove features not used to place msg
    // in recent topics.
    return {
        id: msg.id,
        timestamp: msg.timestamp,
        stream_id: msg.stream_id,
        topic: msg.topic,
        sender_id: msg.sender_id,
        unread: msg.unread,
        type: msg.type,
    };
}

exports.process_message = function (msg) {
    const is_ours = people.is_my_user_id(msg.sender_id);
    const is_relevant = is_ours && msg.type === 'stream';
    // Combine stream_id and topic to make the key unique
    // for every new topic.
    const key = msg.stream_id + ':' + msg.topic;
    const topic = topics.get(key);
    // Only those topics are relevant in which msg sent by
    // current user is present.
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
    // Sort all recent topics by last message timestamp.
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

exports.get = function () {
    return get_sorted_topics();
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
    return updated_topics;
};

window.recent_topics = exports;
