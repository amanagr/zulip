let rt = zrequire('recent_topics');

let people = {
    is_my_user_id: function (id) {
        return id === 1;
    },
};

set_global('people', people);

run_test('basic assertions',() => {
    const stream1 = 1;

    const topic1 = "topic-1";  // No Other sender
    const topic2 = "topic-2";  // Other sender but msg read
    const topic3 = "topic-3";  // User not present and unread
    const topic4 = "topic-4";  // User not present and read
    const topic5 = "topic-5";  // other sender and msg unread
    const topic6 = "topic-6";  // other sender and msg unread

    const sender1 = 1;
    const sender2 = 2;

    // New stream
    let messages = [];

    messages[0] = {
        stream_id: stream1,
        timestamp: 1000,
        subject: topic1,
        sender_id: sender1,
        unread: false,
        type: 'stream',
    };

    messages[1] = {
        stream_id: stream1,
        timestamp: 1010,
        subject: topic2,
        sender_id: sender1,
        unread: false,
        type: 'stream',
    };

    messages[2] = {
        stream_id: stream1,
        timestamp: messages[1].timestamp + 1,
        subject: topic2,
        sender_id: sender2,
        unread: false,
        type: 'stream',
    };

    messages[3] = {
        stream_id: stream1,
        timestamp: 1020,
        subject: topic3,
        sender_id: sender2,
        unread: true,
        type: 'stream',
    };

    messages[4] = {
        stream_id: stream1,
        timestamp: 1030,
        subject: topic4,
        sender_id: sender2,
        unread: false,
        type: 'stream',
    };

    messages[5] = {
        stream_id: stream1,
        timestamp: 1040,
        subject: topic5,
        sender_id: sender1,
        unread: false,
        type: 'stream',
    };

    messages[6] = {
        stream_id: stream1,
        timestamp: messages[5].timestamp + 1,
        subject: topic5,
        sender_id: sender2,
        unread: true,
        type: 'stream',
    };

    messages[7] = {
        stream_id: stream1,
        timestamp: 1050,
        subject: topic6,
        sender_id: sender1,
        unread: false,
        type: 'stream',
    };

    messages[8] = {
        stream_id: stream1,
        timestamp: messages[7].timestamp + 1,
        subject: topic6,
        sender_id: sender2,
        unread: true,
        type: 'stream',
    };

    rt.process_messages(messages);
    let all_topics = rt.get();
    let rel_topics = rt.get_relevant();

    // Check for expected lengths.

    assert(all_topics.size, 4); // Participated in 4 topics.
    assert(rel_topics.size, 2); // Two unread topics.

    // Last message was sent by us.
    assert(all_topics.has(stream1 + ':' + topic1));
    assert(!rel_topics.has(stream1 + ':' + topic1));
    assert(all_topics.get(stream1 + ':' + topic1).read);

    // Last message was sent by them but we've read it.
    assert(all_topics.has(stream1 + ':' + topic2));
    assert(!rel_topics.has(stream1 + ':' + topic2));
    assert(all_topics.get(stream1 + ':' + topic2).read);

    // No message was sent by us.
    assert(!all_topics.has(stream1 + ':' + topic3));
    assert(!rel_topics.has(stream1 + ':' + topic3));

    // No message was sent by us.
    assert(!all_topics.has(stream1 + ':' + topic4));
    assert(!rel_topics.has(stream1 + ':' + topic4));

    // Last message was sent by them and is unread.
    assert(all_topics.has(stream1 + ':' + topic5));
    assert(rel_topics.has(stream1 + ':' + topic5));
    assert(!all_topics.get(stream1 + ':' + topic5).read);

    // Last message was sent by them and is unread.
    assert(all_topics.has(stream1 + ':' + topic6));
    assert(rel_topics.has(stream1 + ':' + topic6));
    assert(!all_topics.get(stream1 + ':' + topic6).read);

    // Send new message to topic1 and mark it as unread.
    rt.process_message({
        stream_id: stream1,
        timestamp: messages[1].timestamp + 1,
        subject: topic1,
        sender_id: sender2,
        unread: true,
        type: 'stream',
    });

    // Mark last message to topic5 as read.
    rt.process_message({
        stream_id: stream1,
        timestamp: messages[5].timestamp,
        subject: topic5,
        sender_id: sender2,
        unread: false,
        type: 'stream',
    });

    // Send new message to topic5, and mark it as unread.
    rt.process_message({
        stream_id: stream1,
        timestamp: messages[6].timestamp + 2,
        subject: topic5,
        sender_id: sender2,
        unread: true,
        type: 'stream',
    });

    // Send new message to topic6 and mark it as read.
    rt.process_message({
        stream_id: stream1,
        timestamp: messages[8].timestamp + 1,
        subject: topic6,
        sender_id: sender2,
        unread: false,
        type: 'stream',
    });

    all_topics = rt.get();
    rel_topics = rt.get_relevant();

    // Check for expected lengths.
    assert(all_topics.size, 4); // Participated in 4 topics.
    assert(rel_topics.size, 2); // Two unread topics.

    // Last message was sent by them and is unread.
    assert(all_topics.has(stream1 + ':' + topic1));
    assert(rel_topics.has(stream1 + ':' + topic1));
    assert(!all_topics.get(stream1 + ':' + topic1).read);

    // Last message was sent by them and is unread.
    assert(all_topics.has(stream1 + ':' + topic5));
    assert(rel_topics.has(stream1 + ':' + topic5));
    assert(!all_topics.get(stream1 + ':' + topic5).read);

    // Last message was sent by them but we've read it.
    assert(all_topics.has(stream1 + ':' + topic6));
    assert(!rel_topics.has(stream1 + ':' + topic6));
    assert(all_topics.get(stream1 + ':' + topic6).read);

});