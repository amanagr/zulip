import json
from typing import Any

import litellm
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.utils.timezone import now as timezone_now
from django.utils.translation import gettext as _
from pydantic import Json

from analytics.lib.counts import COUNT_STATS, do_increment_logging_stat
from zerver.lib.exceptions import JsonableError
from zerver.lib.narrow import NarrowParameter, clean_narrow_for_message_fetch, fetch_messages, LARGER_THAN_MAX_MESSAGE_ID
from zerver.lib.response import json_success
from zerver.lib.typed_endpoint import typed_endpoint
from zerver.models import UserProfile, UserMessage
from zerver.lib.message import messages_for_ids

# Maximum number of messages that can be summarized in a single request.
MAX_MESSAGES_SUMMARIZED = 100
# Price per token for input and output tokens.
# These values are based on the pricing of the Bedrock API.
# https://aws.amazon.com/bedrock/pricing/
# Unit: USD per 1 billion tokens.
OUTPUT_COST_PER_BTOKEN = 720
INPUT_COST_PER_BTOKEN = 720


def format_zulip_messages_for_model(zulip_messages: list[dict[str, Any]]) -> str:
    # Note: Including timestamps seems to have no impact; including reactions
    # makes the results worse.

    zulip_messages_list = [
        {"sender": message["sender_full_name"], "content": message["content"]}
        for message in zulip_messages
    ]
    return json.dumps(zulip_messages_list)


def make_message(content: str, role: str = "user") -> dict[str, str]:
    return {"content": content, "role": role}


def get_max_summary_length(conversation_length: int) -> int:
    return min(6, 4 + int((conversation_length - 10) / 10))


@typed_endpoint
def get_messages_summary(
    request: HttpRequest,
    user_profile: UserProfile,
    *,
    narrow: Json[list[NarrowParameter] | None] = None,
) -> HttpResponse:
    if not user_profile.is_realm_admin:
        return json_success(request, {"summary": "Feature limited to admin users for now."})

    if settings.TOPIC_SUMMARIZATION_MODEL is None:
        raise JsonableError(_("AI features are not enabled on this server."))

    # Since there will always be a limit to how much data we want the LLM to process
    # at once, due to API limits or performance reasons at least, we generate summaries
    # for the messages in chunks. We will be using Rolling Summaries for this purpose.
    # Rolling Summaries are summaries that are generated for a fixed number of messages
    # at a time, and then the next summary is generated for the next fixed number of
    # messages with the previous summary as the starting point. This way, we can
    # generate summaries for new messages in a single pass.
    # TODO: Come up with a plan to store these summaries in the database.

    narrow = clean_narrow_for_message_fetch(narrow, user_profile.realm, user_profile)

    query_info = fetch_messages(
        narrow=narrow,
        user_profile=user_profile,
        realm=user_profile.realm,
        is_web_public_query=False,
        anchor=LARGER_THAN_MAX_MESSAGE_ID,
        include_anchor=True,
        num_before=MAX_MESSAGES_SUMMARIZED,
        num_after=0,
    )

    if len(query_info.rows) == 0:
        return json_success(request, {"summary": "No messages in conversation to summarize"})

    result_message_ids: list[int] = []
    user_message_flags: dict[int, list[str]] = {}
    for row in query_info.rows:
        message_id = row[0]
        result_message_ids.append(message_id)
        # NOTE: Flags are not relevant for the query here,
        # so we skip populating them right now.
        user_message_flags[message_id] = []

    message_list = messages_for_ids(
        message_ids=result_message_ids,
        user_message_flags=user_message_flags,
        search_fields={},
        apply_markdown=False,
        client_gravatar=False,
        allow_empty_topic_name=False,
        allow_edit_history=False,
        user_profile=user_profile,
        realm=user_profile.realm,
    )

    # XXX: Translate input and output text to English?
    model = settings.TOPIC_SUMMARIZATION_MODEL
    litellm_params: dict[str, Any] = {}
    if model.startswith("huggingface"):
        assert settings.HUGGINGFACE_API_KEY is not None
        litellm_params["api_key"] = settings.HUGGINGFACE_API_KEY
    else:
        assert model.startswith("bedrock")
        litellm_params["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
        litellm_params["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
        litellm_params["aws_region_name"] = settings.AWS_REGION_NAME

    conversation_length = len(message_list)
    max_summary_length = get_max_summary_length(conversation_length)
    intro = "The following is a chat conversation in the Zulip team chat app."
    topic: str | None = None
    channel: str | None = None
    if narrow and len(narrow) == 2:
        for term in narrow:
            assert not term.negated
            if term.operator == "channel":
                channel = term.operand
            if term.operator == "topic":
                topic = term.operand
    if channel:
        intro += f" channel: {channel}"
    if topic:
        intro += f", topic: {topic}"

    formatted_conversation = format_zulip_messages_for_model(message_list)
    print(formatted_conversation)
    prompt = (
        f"Succinctly summarize this conversation based only on the information provided, "
        f"in up to {max_summary_length} sentences, for someone who is familiar with the context. "
        f"Mention key conclusions and actions, if any. Refer to specific people as appropriate. "
        f"Don't use an intro phrase."
    )
    messages = [
        make_message(intro, "system"),
        make_message(formatted_conversation),
        make_message(prompt),
    ]

    # Token counter is recommended by LiteLLM but mypy says it's not explicitly exported.
    # https://docs.litellm.ai/docs/completion/token_usage#3-token_counter
    input_tokens = litellm.token_counter(model=model, messages=messages)  # type: ignore[attr-defined] # Explained above
    response = litellm.completion(
        model=model,
        messages=messages,
        **litellm_params,
    )
    output_tokens = response["usage"]["completion_tokens"]

    credits_used = (output_tokens * OUTPUT_COST_PER_BTOKEN) + (input_tokens * INPUT_COST_PER_BTOKEN)
    do_increment_logging_stat(
        user_profile, COUNT_STATS["ai_credit_usage::day"], None, timezone_now(), credits_used
    )

    return json_success(request, {"summary": response["choices"][0]["message"]["content"]})
