from PIL import Image, ImageOps
import bitfield.models
from boto.s3.connection import S3Connection
from boto.s3.key import Key
from collections import defaultdict
import datetime
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
import django.contrib.auth.models
from django.core.exceptions import ObjectDoesNotExist
import django.core.validators
from django.db import migrations
from django.db import migrations, models
from django.db import connection, migrations
from django.db.migrations import RunPython
from django.db.backends.postgresql_psycopg2.schema import DatabaseSchemaEditor
from django.db.migrations.state import StateApps
from django.db.models import Max
from django.db.models import Case, Value, When
from django.db.models import F
from django.db.models import Min
from django.db.models import Count
import django.db.models.deletion
from django.db.utils import IntegrityError
import django.utils.timezone
from django.utils.timezone import now
import hashlib
import io
import logging
import lxml
from mimetypes import guess_type
from mock import patch
import os
import re
import requests
from requests import ConnectionError, Response
import shutil
import sys
import time
from typing import Text
from typing import Dict, Optional, Tuple, Union
from typing import Optional
from typing import Any, Dict
from typing import Any, Dict, Optional
from typing import Any, List
from typing import Any, Set, Union
import ujson
from unicodedata import category
import urllib
from zerver.lib.actions import render_stream_description
from zerver.lib.avatar_hash import user_avatar_hash, user_avatar_path
from zerver.lib.cache import cache_delete, user_profile_by_api_key_cache_key
from zerver.lib.fix_unreads import fix
from zerver.lib.queue import queue_json_publish
from zerver.lib.redis_utils import get_redis_client
from zerver.lib.upload import upload_backend
from zerver.lib.utils import generate_api_key
from zerver.lib.utils import generate_random_token
from zerver.lib.utils import make_safe_digest
import zerver.models
from zerver.models import UserProfile
from mock import patch



# We hackishly patch this function in order to revert it to the state
# it had when this migration was first written.  This is a balance
# between copying in a historical version of hundreds of lines of code
# from zerver.lib.upload (which would pretty annoying, but would be a
# pain) and just using the current version, which doesn't work
# since we rearranged the avatars in Zulip 1.6.
def patched_user_avatar_path(user_profile: UserProfile) -> Text:
    email = user_profile.email
    user_key = email.lower() + settings.AVATAR_SALT
    return make_safe_digest(user_key, hashlib.sha1)

@patch('zerver.lib.upload.user_avatar_path', patched_user_avatar_path)
def verify_medium_avatar_image(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    user_profile_model = apps.get_model('zerver', 'UserProfile')
    for user_profile in user_profile_model.objects.filter(avatar_source="U"):
        upload_backend.ensure_medium_avatar_image(user_profile)


def migrate_existing_attachment_data(apps: StateApps,
                                     schema_editor: DatabaseSchemaEditor) -> None:
    Attachment = apps.get_model('zerver', 'Attachment')
    Recipient = apps.get_model('zerver', 'Recipient')
    Stream = apps.get_model('zerver', 'Stream')

    attachments = Attachment.objects.all()
    for entry in attachments:
        owner = entry.owner
        entry.realm = owner.realm
        for message in entry.messages.all():
            if owner == message.sender:
                if message.recipient.type == Recipient.STREAM:
                    stream = Stream.objects.get(id=message.recipient.type_id)
                    is_realm_public = not stream.realm.is_zephyr_mirror_realm and not stream.invite_only
                    entry.is_realm_public = entry.is_realm_public or is_realm_public

        entry.save()


def set_subdomain_of_default_realm(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    if settings.DEVELOPMENT:
        Realm = apps.get_model('zerver', 'Realm')
        try:
            default_realm = Realm.objects.get(domain="zulip.com")
        except ObjectDoesNotExist:
            default_realm = None

        if default_realm is not None:
            default_realm.subdomain = "zulip"
            default_realm.save()


        @wraps(func)
        def patched(*args, **keywargs):
            extra_args = []
            entered_patchers = []

            exc_info = tuple()
            try:
                for patching in patched.patchings:
                    arg = patching.__enter__()
                    entered_patchers.append(patching)
                    if patching.attribute_name is not None:
                        keywargs.update(arg)
                    elif patching.new is DEFAULT:
                        extra_args.append(arg)

                args += tuple(extra_args)
                return func(*args, **keywargs)
            except:
                if (patching not in entered_patchers and
                    _is_started(patching)):
                    # the patcher may have been started, but an exception
                    # raised whilst entering one of its additional_patchers
                    entered_patchers.append(patching)
                # Pass the exception to __exit__
                exc_info = sys.exc_info()
                # re-raise the exception
                raise
            finally:
                for patching in reversed(entered_patchers):
                    patching.__exit__(*exc_info)


def add_domain_to_realm_alias_if_needed(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Realm = apps.get_model('zerver', 'Realm')
    RealmAlias = apps.get_model('zerver', 'RealmAlias')

    for realm in Realm.objects.all():
        # if realm.domain already exists in RealmAlias, assume it is correct
        if not RealmAlias.objects.filter(domain=realm.domain).exists():
            RealmAlias.objects.create(realm=realm, domain=realm.domain)


def set_string_id_using_domain(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Realm = apps.get_model('zerver', 'Realm')
    for realm in Realm.objects.all():
        if not realm.string_id:
            prefix = realm.domain.split('.')[0]
            try:
                realm.string_id = prefix
                realm.save(update_fields=["string_id"])
                continue
            except IntegrityError:
                pass
            for i in range(1, 100):
                try:
                    realm.string_id = prefix + str(i)
                    realm.save(update_fields=["string_id"])
                    continue
                except IntegrityError:
                    pass
            raise RuntimeError("Unable to find a good string_id for realm %s" % (realm,))


def check_and_create_attachments(apps: StateApps,
                                 schema_editor: DatabaseSchemaEditor) -> None:
    STREAM = 2
    Message = apps.get_model('zerver', 'Message')
    Attachment = apps.get_model('zerver', 'Attachment')
    Stream = apps.get_model('zerver', 'Stream')
    for message in Message.objects.filter(has_attachment=True, attachment=None):
        attachment_url_list = attachment_url_re.findall(message.content)
        for url in attachment_url_list:
            path_id = attachment_url_to_path_id(url)
            user_profile = message.sender
            is_message_realm_public = False
            if message.recipient.type == STREAM:
                stream = Stream.objects.get(id=message.recipient.type_id)
                is_message_realm_public = not stream.invite_only and stream.realm.domain != "mit.edu"

            if path_id is not None:
                attachment = Attachment.objects.create(
                    file_name=os.path.basename(path_id), path_id=path_id, owner=user_profile,
                    realm=user_profile.realm, is_realm_public=is_message_realm_public)
                attachment.messages.add(message)


def backfill_user_activations_and_deactivations(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    migration_time = timezone_now()
    RealmAuditLog = apps.get_model('zerver', 'RealmAuditLog')
    UserProfile = apps.get_model('zerver', 'UserProfile')

    for user in UserProfile.objects.all():
        RealmAuditLog.objects.create(realm=user.realm, modified_user=user,
                                     event_type='user_created', event_time=user.date_joined,
                                     backfilled=False)

    for user in UserProfile.objects.filter(is_active=False):
        RealmAuditLog.objects.create(realm=user.realm, modified_user=user,
                                     event_type='user_deactivated', event_time=migration_time,
                                     backfilled=True)


def reverse_code(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    RealmAuditLog = apps.get_model('zerver', 'RealmAuditLog')
    RealmAuditLog.objects.filter(event_type='user_created').delete()
    RealmAuditLog.objects.filter(event_type='user_deactivated').delete()


def move_avatars_to_be_uid_based(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    user_profile_model = apps.get_model('zerver', 'UserProfile')
    if settings.LOCAL_UPLOADS_DIR is not None:
        for user_profile in user_profile_model.objects.filter(avatar_source="U"):
            src_file_name = user_avatar_hash(user_profile.email)
            dst_file_name = user_avatar_path(user_profile)
            try:
                move_local_file('avatars', src_file_name + '.original', dst_file_name + '.original')
                move_local_file('avatars', src_file_name + '-medium.png', dst_file_name + '-medium.png')
                move_local_file('avatars', src_file_name + '.png', dst_file_name + '.png')
            except MissingAvatarException:
                # If the user's avatar is missing, it's probably
                # because they previously changed their email address.
                # So set them to have a gravatar instead.
                user_profile.avatar_source = "G"
                user_profile.save(update_fields=["avatar_source"])
    else:
        conn = S3Connection(settings.S3_KEY, settings.S3_SECRET_KEY)
        bucket_name = settings.S3_AVATAR_BUCKET
        bucket = conn.get_bucket(bucket_name, validate=False)
        for user_profile in user_profile_model.objects.filter(avatar_source="U"):
            uid_hash_path = user_avatar_path(user_profile)
            email_hash_path = user_avatar_hash(user_profile.email)
            if bucket.get_key(uid_hash_path):
                continue
            if not bucket.get_key(email_hash_path):
                # This is likely caused by a user having previously changed their email
                # If the user's avatar is missing, it's probably
                # because they previously changed their email address.
                # So set them to have a gravatar instead.
                user_profile.avatar_source = "G"
                user_profile.save(update_fields=["avatar_source"])
                continue

            bucket.copy_key(uid_hash_path + ".original",
                            bucket_name,
                            email_hash_path + ".original")
            bucket.copy_key(uid_hash_path + "-medium.png",
                            bucket_name,
                            email_hash_path + "-medium.png")
            bucket.copy_key(uid_hash_path,
                            bucket_name,
                            email_hash_path)

        # From an error handling sanity perspective, it's best to
        # start deleting after everything is copied, so that recovery
        # from failures is easy (just rerun one loop or the other).
        for user_profile in user_profile_model.objects.filter(avatar_source="U"):
            bucket.delete_key(user_avatar_hash(user_profile.email) + ".original")
            bucket.delete_key(user_avatar_hash(user_profile.email) + "-medium.png")
            bucket.delete_key(user_avatar_hash(user_profile.email))


def sync_filesizes(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    attachments = apps.get_model('zerver', 'Attachment')
    if settings.LOCAL_UPLOADS_DIR is not None:
        for attachment in attachments.objects.all():
            if attachment.size is None:
                try:
                    new_size = get_file_size_local(attachment.path_id)
                except MissingUploadFileException:
                    new_size = 0
                attachment.size = new_size
                attachment.save(update_fields=["size"])
    else:
        conn = S3Connection(settings.S3_KEY, settings.S3_SECRET_KEY)
        bucket_name = settings.S3_AUTH_UPLOADS_BUCKET
        bucket = conn.get_bucket(bucket_name, validate=False)
        for attachment in attachments.objects.all():
            if attachment.size is None:
                file_key: Optional[Key] = bucket.get_key(attachment.path_id)
                if file_key is None:
                    new_size = 0
                else:
                    new_size = file_key.size
                attachment.size = new_size
                attachment.save(update_fields=["size"])


def reverse_sync_filesizes(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    """Does nothing"""
    return None


def fix_duplicate_attachments(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    """Migration 0041 had a bug, where if multiple messages referenced the
    same attachment, rather than creating a single attachment object
    for all of them, we would incorrectly create one for each message.
    This results in exceptions looking up the Attachment object
    corresponding to a file that was used in multiple messages that
    predate migration 0041.

    This migration fixes this by removing the duplicates, moving their
    messages onto a single canonical Attachment object (per path_id).
    """
    Attachment = apps.get_model('zerver', 'Attachment')
    # Loop through all groups of Attachment objects with the same `path_id`
    for group in Attachment.objects.values('path_id').annotate(Count('id')).order_by().filter(id__count__gt=1):
        # Sort by the minimum message ID, to find the first attachment
        attachments = sorted(list(Attachment.objects.filter(path_id=group['path_id']).order_by("id")),
                             key = lambda x: min(x.messages.all().values_list('id')[0]))
        surviving = attachments[0]
        to_cleanup = attachments[1:]
        for a in to_cleanup:
            # For each duplicate attachment, we transfer its messages
            # to the canonical attachment object for that path, and
            # then delete the original attachment.
            for msg in a.messages.all():
                surviving.messages.add(msg)
            surviving.is_realm_public = surviving.is_realm_public or a.is_realm_public
            surviving.save()
            a.delete()


def upload_emoji_to_storage(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    realm_emoji_model = apps.get_model('zerver', 'RealmEmoji')
    uploader: Uploader = get_uploader()
    for emoji in realm_emoji_model.objects.all():
        file_name = uploader.upload_emoji(emoji.realm_id, emoji.img_url, emoji.name)
        if file_name is None:
            logging.warning("ERROR: Could not download emoji %s; please reupload manually" %
                            (emoji,))
        emoji.file_name = file_name
        emoji.save()


def delete_old_scheduled_jobs(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    """Delete any old scheduled jobs, to handle changes in the format of
    that table.  Ideally, we'd translate the jobs, but it's not really
    worth the development effort to save a few invitation reminders
    and day2 followup emails.
    """
    ScheduledJob = apps.get_model('zerver', 'ScheduledJob')
    ScheduledJob.objects.all().delete()


    def emoji_to_lowercase(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
        RealmEmoji = apps.get_model("zerver", "RealmEmoji")
        emoji = RealmEmoji.objects.all()
        for e in emoji:
            # Technically, this could create a conflict, but it's
            # exceedingly unlikely.  If that happens, the sysadmin can
            # manually rename the conflicts with the manage.py shell
            # and then rerun the migration/upgrade.
            e.name = e.name.lower()
            e.save()


def fix_bot_type(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    UserProfile = apps.get_model("zerver", "UserProfile")
    bots = UserProfile.objects.filter(is_bot=True, bot_type=None)
    for bot in bots:
        bot.bot_type = 1
        bot.save()


def delete_old_scheduled_jobs_2(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    """Delete any old scheduled jobs, to handle changes in the format of
    send_email. Ideally, we'd translate the jobs, but it's not really
    worth the development effort to save a few invitation reminders
    and day2 followup emails.
    """
    ScheduledJob = apps.get_model('zerver', 'ScheduledJob')
    ScheduledJob.objects.all().delete()


def backfill_subscription_log_events(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    migration_time = timezone_now()
    RealmAuditLog = apps.get_model('zerver', 'RealmAuditLog')
    Subscription = apps.get_model('zerver', 'Subscription')
    Message = apps.get_model('zerver', 'Message')
    objects_to_create = []

    subs_query = Subscription.objects.select_related(
        "user_profile", "user_profile__realm", "recipient").filter(recipient__type=2)
    for sub in subs_query:
        entry = RealmAuditLog(
            realm=sub.user_profile.realm,
            modified_user=sub.user_profile,
            modified_stream_id=sub.recipient.type_id,
            event_last_message_id=0,
            event_type='subscription_created',
            event_time=migration_time,
            backfilled=True)
        objects_to_create.append(entry)
    RealmAuditLog.objects.bulk_create(objects_to_create)
    objects_to_create = []

    event_last_message_id = Message.objects.aggregate(Max('id'))['id__max']
    migration_time_for_deactivation = timezone_now()
    for sub in subs_query.filter(active=False):
        entry = RealmAuditLog(
            realm=sub.user_profile.realm,
            modified_user=sub.user_profile,
            modified_stream_id=sub.recipient.type_id,
            event_last_message_id=event_last_message_id,
            event_type='subscription_deactivated',
            event_time=migration_time_for_deactivation,
            backfilled=True)
        objects_to_create.append(entry)
    RealmAuditLog.objects.bulk_create(objects_to_create)
    objects_to_create = []


def reverse_code_2(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    RealmAuditLog = apps.get_model('zerver', 'RealmAuditLog')
    RealmAuditLog.objects.filter(event_type='subscription_created').delete()
    RealmAuditLog.objects.filter(event_type='subscription_deactivated').delete()


def populate_new_fields(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    # Open the JSON file which contains the data to be used for migration.
    MIGRATION_DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "management", "data")
    path_to_unified_reactions = os.path.join(MIGRATION_DATA_PATH, "unified_reactions.json")
    unified_reactions = ujson.load(open(path_to_unified_reactions))

    Reaction = apps.get_model('zerver', 'Reaction')
    for reaction in Reaction.objects.all():
        reaction.emoji_code = unified_reactions.get(reaction.emoji_name)
        if reaction.emoji_code is None:
            # If it's not present in the unified_reactions map, it's a realm emoji.
            reaction.emoji_code = reaction.emoji_name
            if reaction.emoji_name == 'zulip':
                # `:zulip:` emoji is a zulip special custom emoji.
                reaction.reaction_type = 'zulip_extra_emoji'
            else:
                reaction.reaction_type = 'realm_emoji'
        reaction.save()


    @staticmethod
    def noop(apps, schema_editor):
        return None


def convert_muted_topics(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    stream_query = '''
        SELECT
            zerver_stream.name,
            zerver_stream.realm_id,
            zerver_stream.id,
            zerver_recipient.id
        FROM
            zerver_stream
        INNER JOIN zerver_recipient ON (
            zerver_recipient.type_id = zerver_stream.id AND
            zerver_recipient.type = 2
        )
    '''

    stream_dict = {}

    with connection.cursor() as cursor:
        cursor.execute(stream_query)
        rows = cursor.fetchall()
        for (stream_name, realm_id, stream_id, recipient_id) in rows:
            stream_name = stream_name.lower()
            stream_dict[(stream_name, realm_id)] = (stream_id, recipient_id)

    UserProfile = apps.get_model("zerver", "UserProfile")
    MutedTopic = apps.get_model("zerver", "MutedTopic")

    new_objs = []

    user_query = UserProfile.objects.values(
        'id',
        'realm_id',
        'muted_topics'
    )

    for row in user_query:
        user_profile_id = row['id']
        realm_id = row['realm_id']
        muted_topics = row['muted_topics']

        tups = ujson.loads(muted_topics)
        for (stream_name, topic_name) in tups:
            stream_name = stream_name.lower()
            val = stream_dict.get((stream_name, realm_id))
            if val is not None:
                stream_id, recipient_id = val
                muted_topic = MutedTopic(
                    user_profile_id=user_profile_id,
                    stream_id=stream_id,
                    recipient_id=recipient_id,
                    topic_name=topic_name,
                )
                new_objs.append(muted_topic)

    with connection.cursor() as cursor:
        cursor.execute('DELETE from zerver_mutedtopic')

    MutedTopic.objects.bulk_create(new_objs)


def fix_unreads(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    UserProfile = apps.get_model("zerver", "UserProfile")
    user_profiles = list(UserProfile.objects.filter(is_bot=False))
    for user_profile in user_profiles:
        fix(user_profile)


def fix_realm_string_ids(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Realm = apps.get_model('zerver', 'Realm')
    if Realm.objects.filter(deactivated=False).count() != 2:
        return

    zulip_realm = Realm.objects.get(string_id="zulip")
    try:
        user_realm = Realm.objects.filter(deactivated=False).exclude(id=zulip_realm.id)[0]
    except Realm.DoesNotExist:
        return

    user_realm.string_id = ""
    user_realm.save()


    @staticmethod
    def noop(apps, schema_editor):
        return None


def set_tutorial_status_to_finished(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    UserProfile = apps.get_model('zerver', 'UserProfile')
    UserProfile.objects.update(tutorial_status='F')


def populate_is_zephyr(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Realm = apps.get_model("zerver", "Realm")
    Stream = apps.get_model("zerver", "Stream")

    realms = Realm.objects.filter(
        string_id='zephyr',
    )

    for realm in realms:
        Stream.objects.filter(
            realm_id=realm.id
        ).update(
            is_in_zephyr_realm=True
        )


    @staticmethod
    def noop(apps, schema_editor):
        return None


def set_initial_value_for_signup_notifications_stream(
        apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    realm_model = apps.get_model("zerver", "Realm")
    realms = realm_model.objects.exclude(notifications_stream__isnull=True)
    for realm in realms:
        realm.signup_notifications_stream = realm.notifications_stream
        realm.save(update_fields=["signup_notifications_stream"])


    @staticmethod
    def noop(apps, schema_editor):
        return None


def remove_prereg_users_without_realm(
        apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    prereg_model = apps.get_model("zerver", "PreregistrationUser")
    prereg_model.objects.filter(realm=None, realm_creation=False).delete()


    @staticmethod
    def noop(apps, schema_editor):
        return None


def set_realm_for_existing_scheduledemails(
        apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    scheduledemail_model = apps.get_model("zerver", "ScheduledEmail")
    preregistrationuser_model = apps.get_model("zerver", "PreregistrationUser")
    for scheduledemail in scheduledemail_model.objects.all():
        if scheduledemail.type == 3:  # ScheduledEmail.INVITATION_REMINDER
            # Don't think this can be None, but just be safe
            prereg = preregistrationuser_model.objects.filter(email=scheduledemail.address).first()
            if prereg is not None:
                scheduledemail.realm = prereg.realm
        else:
            scheduledemail.realm = scheduledemail.user.realm
        scheduledemail.save(update_fields=['realm'])

    # Shouldn't be needed, but just in case
    scheduledemail_model.objects.filter(realm=None).delete()


    @staticmethod
    def noop(apps, schema_editor):
        return None


def change_emojiset(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    UserProfile = apps.get_model("zerver", "UserProfile")
    for user in UserProfile.objects.filter(emoji_alt_code=True):
        user.emojiset = "text"
        user.save(update_fields=["emojiset"])


def reverse_change_emojiset(apps: StateApps,
                            schema_editor: DatabaseSchemaEditor) -> None:
    UserProfile = apps.get_model("zerver", "UserProfile")
    for user in UserProfile.objects.filter(emojiset="text"):
        # Resetting `emojiset` to "google" (the default) doesn't make an
        # exact round trip, but it's nearly indistinguishable -- the setting
        # shouldn't really matter while `emoji_alt_code` is true.
        user.emoji_alt_code = True
        user.emojiset = "google"
        user.save(update_fields=["emoji_alt_code", "emojiset"])


def backfill_last_message_id(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    event_type = ['subscription_created', 'subscription_deactivated', 'subscription_activated']
    RealmAuditLog = apps.get_model('zerver', 'RealmAuditLog')
    subscription_logs = RealmAuditLog.objects.filter(
        event_last_message_id__isnull=True, event_type__in=event_type)
    subscription_logs.update(event_last_message_id=-1)


    @staticmethod
    def noop(apps, schema_editor):
        return None


def set_initial_value_for_bot_creation_policy(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Realm = apps.get_model("zerver", "Realm")
    Realm.BOT_CREATION_EVERYONE = 1
    Realm.BOT_CREATION_LIMIT_GENERIC_BOTS = 2
    for realm in Realm.objects.all():
        if realm.create_generic_bot_by_admins_only:
            realm.bot_creation_policy = Realm.BOT_CREATION_LIMIT_GENERIC_BOTS
        else:
            realm.bot_creation_policy = Realm.BOT_CREATION_EVERYONE
        realm.save(update_fields=["bot_creation_policy"])


def reverse_code_3(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Realm = apps.get_model("zerver", "Realm")
    Realm.BOT_CREATION_EVERYONE = 1
    for realm in Realm.objects.all():
        if realm.bot_creation_policy == Realm.BOT_CREATION_EVERYONE:
            realm.create_generic_bot_by_admins_only = False
        else:
            realm.create_generic_bot_by_admins_only = True
        realm.save(update_fields=["create_generic_bot_by_admins_only"])


def realm_emoji_name_to_id(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Reaction = apps.get_model('zerver', 'Reaction')
    RealmEmoji = apps.get_model('zerver', 'RealmEmoji')
    realm_emoji_by_realm_id: Dict[int, Dict[str, Any]] = defaultdict(dict)
    for realm_emoji in RealmEmoji.objects.all():
        realm_emoji_by_realm_id[realm_emoji.realm_id][realm_emoji.name] = {
            'id': str(realm_emoji.id),
            'name': realm_emoji.name,
            'deactivated': realm_emoji.deactivated,
        }
    for reaction in Reaction.objects.filter(reaction_type='realm_emoji'):
        realm_id = reaction.user_profile.realm_id
        emoji_name = reaction.emoji_name
        realm_emoji = realm_emoji_by_realm_id.get(realm_id, {}).get(emoji_name)
        if realm_emoji is None:
            # Realm emoji used in this reaction has been deleted so this
            # reaction should also be deleted. We don't need to reverse
            # this step in migration reversal code.
            print("Reaction for (%s, %s) refers to deleted custom emoji %s; deleting" %
                  (emoji_name, reaction.message_id, reaction.user_profile_id))
            reaction.delete()
        else:
            reaction.emoji_code = realm_emoji["id"]
            reaction.save()


def reversal(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Reaction = apps.get_model('zerver', 'Reaction')
    for reaction in Reaction.objects.filter(reaction_type='realm_emoji'):
        reaction.emoji_code = reaction.emoji_name
        reaction.save()


def migrate_realm_emoji_image_files(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    RealmEmoji = apps.get_model('zerver', 'RealmEmoji')
    uploader = get_uploader()
    for realm_emoji in RealmEmoji.objects.all():
        old_file_name = realm_emoji.file_name
        new_file_name = get_emoji_file_name(old_file_name, str(realm_emoji.id))
        uploader.ensure_emoji_images(realm_emoji.realm_id, old_file_name, new_file_name)
        realm_emoji.file_name = new_file_name
        realm_emoji.save(update_fields=['file_name'])


def reversal_2(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    # Ensures that migration can be re-run in case of a failure.
    RealmEmoji = apps.get_model('zerver', 'RealmEmoji')
    for realm_emoji in RealmEmoji.objects.all():
        corrupt_file_name = realm_emoji.file_name
        correct_file_name = get_emoji_file_name(corrupt_file_name, realm_emoji.name)
        realm_emoji.file_name = correct_file_name
        realm_emoji.save(update_fields=['file_name'])


def migrate_fix_invalid_bot_owner_values(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    """Fixes UserProfile objects that incorrectly had a bot_owner set"""
    UserProfile = apps.get_model('zerver', 'UserProfile')
    UserProfile.objects.filter(is_bot=False).exclude(bot_owner=None).update(bot_owner=None)


    @staticmethod
    def noop(apps, schema_editor):
        return None


def set_initial_value_for_history_public_to_subscribers(
        apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    stream_model = apps.get_model("zerver", "Stream")
    streams = stream_model.objects.all()

    for stream in streams:
        if stream.invite_only:
            stream.history_public_to_subscribers = getattr(settings, 'PRIVATE_STREAM_HISTORY_FOR_SUBSCRIBERS', False)
        else:
            stream.history_public_to_subscribers = True

        if stream.is_in_zephyr_realm:
            stream.history_public_to_subscribers = False

        stream.save(update_fields=["history_public_to_subscribers"])


    @staticmethod
    def noop(apps, schema_editor):
        return None


def migrate_set_order_value(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    CustomProfileField = apps.get_model('zerver', 'CustomProfileField')
    CustomProfileField.objects.all().update(order=F('id'))


    @staticmethod
    def noop(apps, schema_editor):
        return None


def copy_email_field(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    UserProfile = apps.get_model('zerver', 'UserProfile')
    UserProfile.objects.all().update(delivery_email=F('email'))


    @staticmethod
    def noop(apps, schema_editor):
        return None


def change_realm_audit_log_event_type_tense(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    RealmAuditLog = apps.get_model('zerver', 'RealmAuditLog')
    RealmAuditLog.objects.filter(event_type="user_change_password").update(event_type="user_password_changed")
    RealmAuditLog.objects.filter(event_type="user_change_avatar_source").update(event_type="user_avatar_source_changed")
    RealmAuditLog.objects.filter(event_type="bot_owner_changed").update(event_type="user_bot_owner_changed")


    @staticmethod
    def noop(apps, schema_editor):
        return None


def reset_is_private_flag(
        apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    UserMessage = apps.get_model("zerver", "UserMessage")
    UserProfile = apps.get_model("zerver", "UserProfile")
    user_profile_ids = UserProfile.objects.all().order_by("id").values_list("id", flat=True)
    # We only need to do this because previous migration
    # zerver/migrations/0100_usermessage_remove_is_me_message.py
    # didn't clean the field after removing it.

    i = 0
    total = len(user_profile_ids)
    print("Setting default values for the new flag...")
    sys.stdout.flush()
    for user_id in user_profile_ids:
        while True:
            # Ideally, we'd just do a single database query per user.
            # Unfortunately, Django doesn't use the fancy new index on
            # is_private that we just generated if we do that,
            # resulting in a very slow migration that could take hours
            # on a large server.  We address this issue by doing a bit
            # of hackery to generate the SQL just right (with an
            # `ORDER BY` clause that forces using the new index).
            flag_set_objects = UserMessage.objects.filter(user_profile__id = user_id).extra(
                where=["flags & 2048 != 0"]).order_by("message_id")[0:1000]
            user_message_ids = flag_set_objects.values_list("id", flat=True)
            count = UserMessage.objects.filter(id__in=user_message_ids).update(
                flags=F('flags').bitand(~UserMessage.flags.is_private))
            if count < 1000:
                break

        i += 1
        if (i % 50 == 0 or i == total):
            percent = round((i / total) * 100, 2)
            print("Processed %s/%s %s%%" % (i, total, percent))
            sys.stdout.flush()


    @staticmethod
    def noop(apps, schema_editor):
        return None


def change_emojiset_choice(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    UserProfile = apps.get_model('zerver', 'UserProfile')
    UserProfile.objects.exclude(emojiset__in=['google', 'text']).update(emojiset='google')


    @staticmethod
    def noop(apps, schema_editor):
        return None


def set_initial_value_of_is_private_flag(
        apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    UserMessage = apps.get_model("zerver", "UserMessage")
    Message = apps.get_model("zerver", "Message")
    if not Message.objects.exists():
        return

    i = 0
    # Total is only used for the progress bar
    total = Message.objects.filter(recipient__type__in=[1, 3]).count()
    processed = 0

    print("\nStart setting initial value for is_private flag...")
    sys.stdout.flush()
    while True:
        range_end = i + 10000
        # Can't use [Recipient.PERSONAL, Recipient.HUDDLE] in migration files
        message_ids = list(Message.objects.filter(recipient__type__in=[1, 3],
                                                  id__gt=i,
                                                  id__lte=range_end).values_list("id", flat=True).order_by("id"))
        count = UserMessage.objects.filter(message_id__in=message_ids).update(flags=F('flags').bitor(UserMessage.flags.is_private))
        if count == 0 and range_end >= Message.objects.last().id:
            break

        i = range_end
        processed += len(message_ids)
        if total != 0:
            percent = round((processed / total) * 100, 2)
        else:
            percent = 100.00
        print("Processed %s/%s %s%%" % (processed, total, percent))
        sys.stdout.flush()


    @staticmethod
    def noop(apps, schema_editor):
        return None


def change_emojiset_choice_2(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    UserProfile = apps.get_model('zerver', 'UserProfile')
    UserProfile.objects.filter(emojiset='google').update(emojiset='google-blob')


    @staticmethod
    def noop(apps, schema_editor):
        return None


def set_initial_value_for_invited_as(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    PreregistrationUser = apps.get_model("zerver", "PreregistrationUser")
    for user in PreregistrationUser.objects.all():
        if user.invited_as_admin:
            user.invited_as = 1     # PreregistrationUser.INVITE_AS['REALM_ADMIN']
        else:
            user.invited_as = 2     # PreregistrationUser.INVITE_AS['MEMBER']
        user.save(update_fields=["invited_as"])


def reverse_code_4(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    PreregistrationUser = apps.get_model("zerver", "PreregistrationUser")
    for user in PreregistrationUser.objects.all():
        if user.invited_as == 1:    # PreregistrationUser.INVITE_AS['REALM_ADMIN']
            user.invited_as_admin = True
        else:                       # PreregistrationUser.INVITE_AS['MEMBER']
            user.invited_as_admin = False
        user.save(update_fields=["invited_as_admin"])


def render_all_stream_descriptions(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Stream = apps.get_model('zerver', 'Stream')
    all_streams = Stream.objects.exclude(description='')
    for stream in all_streams:
        stream.rendered_description = render_stream_description(stream.description)
        stream.save(update_fields=["rendered_description"])


    @staticmethod
    def noop(apps, schema_editor):
        return None


def ensure_no_empty_passwords(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    """With CVE-2019-18933, it was possible for certain users created
    using social login (e.g. Google/GitHub auth) to have the empty
    string as their password in the Zulip database, rather than
    Django's "unusable password" (i.e. no password at all).  This was a
    serious security issue for organizations with both password and
    Google/GitHub authentication enabled.

    Combined with the code changes to prevent new users from entering
    this buggy state, this migration sets the intended "no password"
    state for any users who are in this buggy state, as had been
    intended.

    While this bug was discovered by our own development team and we
    believe it hasn't been exploited in the wild, out of an abundance
    of caution, this migration also resets the personal API keys for
    all users where Zulip's database-level logging cannot **prove**
    that user's current personal API key was never accessed using this
    bug.

    There are a few ways this can be proven: (1) the user's password
    has never been changed and is not the empty string,
    or (2) the user's personal API key has changed since that user last
    changed their password (which is not ''). Both constitute proof
    because this bug cannot be used to gain the access required to change
    or reset a user's password.

    Resetting those API keys has the effect of logging many users out
    of the Zulip mobile and terminal apps unnecessarily (e.g. because
    the user changed their password at any point in the past, even
    though the user never was affected by the bug), but we're
    comfortable with that cost for ensuring that this bug is
    completely fixed.

    To avoid this inconvenience for self-hosted servers which don't
    even have EmailAuthBackend enabled, we skip resetting any API keys
    if the server doesn't have EmailAuthBackend configured.
    """

    UserProfile = apps.get_model('zerver', 'UserProfile')
    RealmAuditLog = apps.get_model('zerver', 'RealmAuditLog')

    # Because we're backporting this migration to the Zulip 2.0.x
    # series, we've given it migration number 0209, which is a
    # duplicate with an existing migration already merged into Zulip
    # master.  Migration 0247_realmauditlog_event_type_to_int.py
    # changes the format of RealmAuditLog.event_type, so we need the
    # following conditional block to determine what values to use when
    # searching for the relevant events in that log.
    event_type_class = RealmAuditLog._meta.get_field('event_type').get_internal_type()
    if event_type_class == 'CharField':
        USER_PASSWORD_CHANGED: Union[int, str] = 'user_password_changed'
        USER_API_KEY_CHANGED: Union[int, str] = 'user_api_key_changed'
    else:
        USER_PASSWORD_CHANGED = 122
        USER_API_KEY_CHANGED = 127

    # First, we do some bulk queries to collect data we'll find useful
    # in the loop over all users below.

    # Users who changed their password at any time since account
    # creation.  These users could theoretically have started with an
    # empty password, but set a password later via the password reset
    # flow.  If their API key has changed since they changed their
    # password, we can prove their current API key cannot have been
    # exposed; we store those users in
    # password_change_user_ids_no_reset_needed.
    password_change_user_ids = set(RealmAuditLog.objects.filter(
        event_type=USER_PASSWORD_CHANGED).values_list("modified_user_id", flat=True))
    password_change_user_ids_api_key_reset_needed: Set[int] = set()
    password_change_user_ids_no_reset_needed: Set[int] = set()

    for user_id in password_change_user_ids:
        # Here, we check the timing for users who have changed
        # their password.

        # We check if the user changed their API key since their first password change.
        query = RealmAuditLog.objects.filter(
            modified_user=user_id, event_type__in=[USER_PASSWORD_CHANGED,
                                                   USER_API_KEY_CHANGED]
        ).order_by("event_time")

        earliest_password_change = query.filter(event_type=USER_PASSWORD_CHANGED).first()
        # Since these users are in password_change_user_ids, this must not be None.
        assert earliest_password_change is not None

        latest_api_key_change = query.filter(event_type=USER_API_KEY_CHANGED).last()
        if latest_api_key_change is None:
            # This user has never changed their API key.  As a
            # result, even though it's very likely this user never
            # had an empty password, they have changed their
            # password, and we have no record of the password's
            # original hash, so we can't prove the user's API key
            # was never affected.  We schedule this user's API key
            # to be reset.
            password_change_user_ids_api_key_reset_needed.add(user_id)
        elif earliest_password_change.event_time <= latest_api_key_change.event_time:
            # This user has changed their password before
            # generating their current personal API key, so we can
            # prove their current personal API key could not have
            # been exposed by this bug.
            password_change_user_ids_no_reset_needed.add(user_id)
        else:
            password_change_user_ids_api_key_reset_needed.add(user_id)

    if password_change_user_ids_no_reset_needed and settings.PRODUCTION:
        # We record in this log file users whose current API key was
        # generated after a real password was set, so there's no need
        # to reset their API key, but because they've changed their
        # password, we don't know whether or not they originally had a
        # buggy password.
        #
        # In theory, this list can be recalculated using the above
        # algorithm modified to only look at events before the time
        # this migration was installed, but it's helpful to log it as well.
        with open("/var/log/zulip/0209_password_migration.log", "w") as log_file:
            line = "No reset needed, but changed password: {}\n"
            log_file.write(line.format(password_change_user_ids_no_reset_needed))

    AFFECTED_USER_TYPE_EMPTY_PASSWORD = 'empty_password'
    AFFECTED_USER_TYPE_CHANGED_PASSWORD = 'changed_password'
    MIGRATION_ID = '0209_user_profile_no_empty_password'

    def write_realm_audit_log_entry(user_profile: Any,
                                    event_time: Any, event_type: Any,
                                    affected_user_type: str) -> None:
        RealmAuditLog.objects.create(
            realm=user_profile.realm,
            modified_user=user_profile,
            event_type=event_type,
            event_time=event_time,
            extra_data=ujson.dumps({
                'migration_id': MIGRATION_ID,
                'affected_user_type': affected_user_type,
            })
        )

    # If Zulip's built-in password authentication is not enabled on
    # the server level, then we plan to skip resetting any users' API
    # keys, since the bug requires EmailAuthBackend.
    email_auth_enabled = 'zproject.backends.EmailAuthBackend' in settings.AUTHENTICATION_BACKENDS

    # A quick note: This query could in theory exclude users with
    # is_active=False, is_bot=True, or realm__deactivated=True here to
    # accessing only active human users in non-deactivated realms.
    # But it's better to just be thorough; users can be reactivated,
    # and e.g. a server admin could manually edit the database to
    # change a bot into a human user if they really wanted to.  And
    # there's essentially no harm in rewriting state for a deactivated
    # account.
    for user_profile in UserProfile.objects.all():
        event_time = timezone_now()
        if check_password('', user_profile.password):
            # This user currently has the empty string as their password.

            # Change their password and record that we did so.
            user_profile.password = make_password(None)
            update_fields = ["password"]
            write_realm_audit_log_entry(user_profile, event_time,
                                        USER_PASSWORD_CHANGED,
                                        AFFECTED_USER_TYPE_EMPTY_PASSWORD)

            if email_auth_enabled and not user_profile.is_bot:
                # As explained above, if the built-in password authentication
                # is enabled, reset the API keys. We can skip bot accounts here,
                # because the `password` attribute on a bot user is useless.
                reset_user_api_key(user_profile)
                update_fields.append("api_key")

                event_time = timezone_now()
                write_realm_audit_log_entry(user_profile, event_time,
                                            USER_API_KEY_CHANGED,
                                            AFFECTED_USER_TYPE_EMPTY_PASSWORD)

            user_profile.save(update_fields=update_fields)
            continue

        elif email_auth_enabled and \
                user_profile.id in password_change_user_ids_api_key_reset_needed:
            # For these users, we just need to reset the API key.
            reset_user_api_key(user_profile)
            user_profile.save(update_fields=["api_key"])

            write_realm_audit_log_entry(user_profile, event_time,
                                        USER_API_KEY_CHANGED,
                                        AFFECTED_USER_TYPE_CHANGED_PASSWORD)


    @staticmethod
    def noop(apps, schema_editor):
        return None


def backfill_first_message_id(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Stream = apps.get_model('zerver', 'Stream')
    Message = apps.get_model('zerver', 'Message')
    for stream in Stream.objects.all():
        first_message = Message.objects.filter(
            recipient__type_id=stream.id,
            recipient__type=2).first()
        if first_message is None:
            # No need to change anything if the outcome is the default of None
            continue

        stream.first_message_id = first_message.id
        stream.save()


    @staticmethod
    def noop(apps, schema_editor):
        return None


def set_users_for_existing_scheduledemails(
        apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    ScheduledEmail = apps.get_model("zerver", "ScheduledEmail")
    for email in ScheduledEmail.objects.all():
        if email.user is not None:
            email.users.add(email.user)
        email.save()


    @staticmethod
    def noop(apps, schema_editor):
        return None


def handle_waiting_period(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Realm = apps.get_model('zerver', 'Realm')
    Realm.INVITE_TO_STREAM_POLICY_WAITING_PERIOD = 3
    Realm.objects.filter(waiting_period_threshold__gt=0).update(
        invite_to_stream_policy=Realm.INVITE_TO_STREAM_POLICY_WAITING_PERIOD)


    @staticmethod
    def noop(apps, schema_editor):
        return None


def upgrade_create_stream_policy(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Realm = apps.get_model('zerver', 'Realm')
    Realm.CREATE_STREAM_POLICY_MEMBERS = 1
    Realm.CREATE_STREAM_POLICY_ADMINS = 2
    Realm.CREATE_STREAM_POLICY_WAITING_PERIOD = 3
    Realm.objects.filter(waiting_period_threshold__exact=0) \
        .filter(create_stream_by_admins_only=False) \
        .update(create_stream_policy=Realm.CREATE_STREAM_POLICY_MEMBERS)
    Realm.objects.filter(create_stream_by_admins_only=True) \
        .update(create_stream_policy=Realm.CREATE_STREAM_POLICY_ADMINS)
    Realm.objects.filter(waiting_period_threshold__gt=0) \
        .filter(create_stream_by_admins_only=False) \
        .update(create_stream_policy=Realm.CREATE_STREAM_POLICY_WAITING_PERIOD)


    @staticmethod
    def noop(apps, schema_editor):
        return None


def disable_realm_digest_emails_enabled(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Realm = apps.get_model("zerver", "Realm")
    realms = Realm.objects.filter(digest_emails_enabled=True)
    realms.update(digest_emails_enabled=False)


    @staticmethod
    def noop(apps, schema_editor):
        return None


def update_notification_settings(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Subscription = apps.get_model('zerver', 'Subscription')
    UserProfile = apps.get_model('zerver', 'UserProfile')

    for setting_value in [True, False]:
        for sub_setting_name, user_setting_name in SETTINGS_MAP.items():
            sub_filter_kwargs = {sub_setting_name: setting_value}
            user_filter_kwargs = {user_setting_name: setting_value}
            update_kwargs = {sub_setting_name: None}
            Subscription.objects.filter(user_profile__in=UserProfile.objects.filter(**user_filter_kwargs),
                                        recipient__type=RECIPIENT_STREAM,
                                        **sub_filter_kwargs).update(**update_kwargs)


def reverse_notification_settings(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Subscription = apps.get_model('zerver', 'Subscription')
    UserProfile = apps.get_model('zerver', 'UserProfile')

    for setting_value in [True, False]:
        for sub_setting_name, user_setting_name in SETTINGS_MAP.items():
            sub_filter_kwargs = {sub_setting_name: None}
            user_filter_kwargs = {user_setting_name: setting_value}
            update_kwargs = {sub_setting_name: setting_value}
            Subscription.objects.filter(user_profile__in=UserProfile.objects.filter(**user_filter_kwargs),
                                        recipient__type=RECIPIENT_STREAM,
                                        **sub_filter_kwargs).update(**update_kwargs)

    for sub_setting_name, user_setting_name in SETTINGS_MAP.items():
        sub_filter_kwargs = {sub_setting_name: None}
        update_kwargs = {sub_setting_name: True}
        Subscription.objects.filter(recipient__type__in=[1, 3], **sub_filter_kwargs).update(**update_kwargs)


def set_initial_value_for_is_muted(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Subscription = apps.get_model("zerver", "Subscription")
    Subscription.objects.update(is_muted=Case(
        When(in_home_view=True, then=Value(False)),
        When(in_home_view=False, then=Value(True)),
    ))


def reverse_code_5(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Subscription = apps.get_model("zerver", "Subscription")
    Subscription.objects.update(in_home_view=Case(
        When(is_muted=True, then=Value(False)),
        When(is_muted=False, then=Value(True)),
    ))


def update_existing_video_chat_provider_values(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Realm = apps.get_model('zerver', 'Realm')

    for realm in Realm.objects.all():
        realm.video_chat_provider = get_video_chat_provider_detail(
            VIDEO_CHAT_PROVIDERS,
            p_name=realm.video_chat_provider_old)['id']
        realm.save(update_fields=["video_chat_provider"])


def reverse_code_6(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Realm = apps.get_model("zerver", "Realm")

    for realm in Realm.objects.all():
        realm.video_chat_provider_old = get_video_chat_provider_detail(
            VIDEO_CHAT_PROVIDERS,
            p_id=realm.video_chat_provider)['name']
        realm.save(update_fields=["video_chat_provider_old"])


def disable_realm_inline_url_embed_preview(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Realm = apps.get_model("zerver", "Realm")
    realms = Realm.objects.filter(inline_url_embed_preview=True)
    realms.update(inline_url_embed_preview=False)


    @staticmethod
    def noop(apps, schema_editor):
        return None


def remove_name_illegal_chars(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    UserProfile = apps.get_model("zerver", "UserProfile")
    for user in UserProfile.objects.all():
        stripped = []
        for char in user.full_name:
            if (char not in NAME_INVALID_CHARS) and (category(char)[0] != "C"):
                stripped.append(char)
        user.full_name = "".join(stripped)
        user.save(update_fields=["full_name"])


def rename_zulip_realm_to_zulipinternal(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    if not settings.PRODUCTION:
        return

    Realm = apps.get_model('zerver', 'Realm')
    UserProfile = apps.get_model('zerver', 'UserProfile')

    if Realm.objects.count() == 0:
        # Database not yet populated, do nothing:
        return

    if Realm.objects.filter(string_id="zulipinternal").exists():
        return
    if not Realm.objects.filter(string_id="zulip").exists():
        # If the user renamed the `zulip` system bot realm (or deleted
        # it), there's nothing for us to do.
        return

    internal_realm = Realm.objects.get(string_id="zulip")

    # For safety, as a sanity check, verify that "internal_realm" is indeed the realm for system bots:
    welcome_bot = UserProfile.objects.get(email="welcome-bot@zulip.com")
    assert welcome_bot.realm.id == internal_realm.id

    internal_realm.string_id = "zulipinternal"
    internal_realm.name = "System use only"
    internal_realm.save()


def copy_id_to_bigid(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    UserMessage = apps.get_model('zerver', 'UserMessage')
    if not UserMessage.objects.exists():
        # Nothing to do
        return

    #  TODO: is  the below lookup fast enough, considering there's no index on bigint_id?
    first_uncopied_id = UserMessage.objects.filter(bigint_id__isnull=True
                                                   ).aggregate(Min('id'))['id__min']
    # Note: the below id can fall in a segment
    # where bigint_id = id already, but it's not a big problem
    # this will just do some redundant UPDATEs.
    last_id = UserMessage.objects.latest("id").id

    id_range_lower_bound = first_uncopied_id
    id_range_upper_bound = first_uncopied_id + BATCH_SIZE
    while id_range_upper_bound <= last_id:
        sql_copy_id_to_bigint_id(id_range_lower_bound, id_range_upper_bound)
        id_range_lower_bound = id_range_upper_bound + 1
        id_range_upper_bound = id_range_lower_bound + BATCH_SIZE
        time.sleep(0.1)

    if last_id > id_range_lower_bound:
        # Copy for the last batch.
        sql_copy_id_to_bigint_id(id_range_lower_bound, last_id)


def fix_bot_email_property(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    UserProfile = apps.get_model('zerver', 'UserProfile')
    for user_profile in UserProfile.objects.filter(is_bot=True):
        if user_profile.email != user_profile.delivery_email:
            user_profile.email = user_profile.delivery_email
            user_profile.save(update_fields=["email"])


    @staticmethod
    def noop(apps, schema_editor):
        return None


def copy_pub_date_to_date_sent(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Message = apps.get_model('zerver', 'Message')
    if not Message.objects.exists():
        # Nothing to do
        return

    first_uncopied_id = Message.objects.filter(date_sent__isnull=True
                                               ).aggregate(Min('id'))['id__min']
    # Note: the below id can fall in a segment
    # where date_sent = pub_date already, but it's not a big problem
    # this will just do some redundant UPDATEs.
    last_id = Message.objects.latest("id").id

    id_range_lower_bound = first_uncopied_id
    id_range_upper_bound = first_uncopied_id + BATCH_SIZE
    while id_range_upper_bound <= last_id:
        sql_copy_pub_date_to_date_sent(id_range_lower_bound, id_range_upper_bound)
        id_range_lower_bound = id_range_upper_bound + 1
        id_range_upper_bound = id_range_lower_bound + BATCH_SIZE
        time.sleep(0.1)

    if last_id > id_range_lower_bound:
        # Copy for the last batch.
        sql_copy_pub_date_to_date_sent(id_range_lower_bound, last_id)


def update_existing_event_type_values(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    RealmAuditLog = apps.get_model('zerver', 'RealmAuditLog')
    for log_entry in RealmAuditLog.objects.all():
        log_entry.event_type_int = INT_VALUE[log_entry.event_type]
        log_entry.save(update_fields=['event_type_int'])


def reverse_code_7(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    RealmAuditLog = apps.get_model('zerver', 'RealmAuditLog')
    for log_entry in RealmAuditLog.objects.all():
        log_entry.event_type = STR_VALUE[log_entry.event_type_int]
        log_entry.save(update_fields=['event_type'])


def update_role(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    UserProfile = apps.get_model('zerver', 'UserProfile')
    # The values at the time of this migration
    UserProfile.ROLE_REALM_ADMINISTRATOR = 200
    UserProfile.ROLE_MEMBER = 400
    UserProfile.ROLE_GUEST = 600
    for user in UserProfile.objects.all():
        if user.is_realm_admin:
            user.role = UserProfile.ROLE_REALM_ADMINISTRATOR
        elif user.is_guest:
            user.role = UserProfile.ROLE_GUEST
        else:
            user.role = UserProfile.ROLE_MEMBER
        user.save(update_fields=['role'])


def reverse_code_8(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    UserProfile = apps.get_model('zerver', 'UserProfile')
    UserProfile.ROLE_REALM_ADMINISTRATOR = 200
    UserProfile.ROLE_GUEST = 600
    for user in UserProfile.objects.all():
        if user.role == UserProfile.ROLE_REALM_ADMINISTRATOR:
            user.is_realm_admin = True
            user.save(update_fields=['is_realm_admin'])
        elif user.role == UserProfile.ROLE_GUEST:
            user.is_guest = True
            user.save(update_fields=['is_guest'])


def fix_has_link(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Message = apps.get_model('zerver', 'Message')
    if not Message.objects.exists():
        # Nothing to do, and Message.objects.latest() will crash.
        return

    # This migration logic assumes that either the server is not
    # running, or that it's being run after the logic to correct how
    # `has_link` and friends are set for new messages have been
    # deployed.
    last_id = Message.objects.latest("id").id

    id_range_lower_bound = 0
    id_range_upper_bound = 0 + BATCH_SIZE
    while id_range_upper_bound <= last_id:
        process_batch(apps, id_range_lower_bound, id_range_upper_bound, last_id)

        id_range_lower_bound = id_range_upper_bound + 1
        id_range_upper_bound = id_range_lower_bound + BATCH_SIZE
        time.sleep(0.1)

    if last_id > id_range_lower_bound:
        # Copy for the last batch.
        process_batch(apps, id_range_lower_bound, last_id, last_id)


    @staticmethod
    def noop(apps, schema_editor):
        return None


def move_missed_message_addresses_to_database(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    redis_client = get_redis_client()
    MissedMessageEmailAddress = apps.get_model('zerver', 'MissedMessageEmailAddress')
    UserProfile = apps.get_model('zerver', 'UserProfile')
    Message = apps.get_model('zerver', 'Message')
    Recipient = apps.get_model('zerver', 'Recipient')
    RECIPIENT_PERSONAL = 1
    RECIPIENT_STREAM = 2

    all_mm_keys = redis_client.keys('missed_message:*')
    for key in all_mm_keys:
        # Don't migrate mm addresses that have already been used.
        if redis_client.hincrby(key, 'uses_left', -1) < 0:
            redis_client.delete(key)
            continue

        result = redis_client.hmget(key, 'user_profile_id', 'recipient_id', 'subject')
        if not all(val is not None for val in result):
            # Missing data, skip this key; this should never happen
            redis_client.delete(key)
            continue

        user_profile_id, recipient_id, subject_b = result  # type: (bytes, bytes, bytes)
        topic_name = subject_b.decode('utf-8')

        # The data model for missed-message emails has changed in two
        # key ways: We're moving it from redis to the database for
        # better persistence, and also replacing the stream + topic
        # (as the reply location) with a message to reply to.  Because
        # the redis data structure only had stream/topic pairs, we use
        # the following migration logic to find the latest message in
        # the thread indicated by the redis data (if it exists).
        try:
            user_profile = UserProfile.objects.get(id=user_profile_id)
            recipient = Recipient.objects.get(id=recipient_id)

            if recipient.type == RECIPIENT_STREAM:
                message = Message.objects.filter(subject__iexact=topic_name,
                                                 recipient_id=recipient.id).latest('id')
            elif recipient.type == RECIPIENT_PERSONAL:
                # Tie to the latest PM from the sender to this user;
                # we expect at least one existed because it generated
                # this missed-message email, so we can skip the
                # normally required additioanl check for messages we
                # ourselves sent to the target user.
                message = Message.objects.filter(recipient_id=user_profile.recipient_id,
                                                 sender_id=recipient.type_id).latest('id')
            else:
                message = Message.objects.filter(recipient_id=recipient.id).latest('id')
        except ObjectDoesNotExist:
            # If all messages in the original thread were deleted or
            # had their topics edited, we can't find an appropriate
            # message to tag; we just skip migrating this message.
            # The consequence (replies to this particular
            # missed-message email bouncing) is acceptable.
            redis_client.delete(key)
            continue

        # The timestamp will be set to the default (now) which means
        # the address will take longer to expire than it would have in
        # redis, but this small issue is probably worth the simplicity
        # of not having to figure out the precise timestamp.
        MissedMessageEmailAddress.objects.create(message=message,
                                                 user_profile=user_profile,
                                                 email_token=generate_missed_message_token())
        # We successfully transferred this missed-message email's data
        # to the database, so this message can be deleted from redis.
        redis_client.delete(key)


    @staticmethod
    def noop(apps, schema_editor):
        return None


def upgrade_stream_post_policy(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    Stream = apps.get_model('zerver', 'Stream')
    Stream.STREAM_POST_POLICY_EVERYONE = 1
    Stream.STREAM_POST_POLICY_ADMINS = 2
    Stream.objects.filter(is_announcement_only=False) \
        .update(stream_post_policy=Stream.STREAM_POST_POLICY_EVERYONE)
    Stream.objects.filter(is_announcement_only=True) \
        .update(stream_post_policy=Stream.STREAM_POST_POLICY_ADMINS)


    @staticmethod
    def noop(apps, schema_editor):
        return None

def emoji_to_lowercase(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    RealmEmoji = apps.get_model("zerver", "RealmEmoji")
    emoji = RealmEmoji.objects.all()
    for e in emoji:
        # Technically, this could create a conflict, but it's
        # exceedingly unlikely.  If that happens, the sysadmin can
        # manually rename the conflicts with the manage.py shell
        # and then rerun the migration/upgrade.
        e.name = e.name.lower()
        e.save()

SQL_1 = """
CREATE TEXT SEARCH DICTIONARY english_us_hunspell
  (template = ispell, DictFile = en_us, AffFile = en_us, StopWords = zulip_english);
CREATE TEXT SEARCH CONFIGURATION zulip.english_us_search (COPY=pg_catalog.english);
ALTER TEXT SEARCH CONFIGURATION zulip.english_us_search
  ALTER MAPPING FOR asciiword, asciihword, hword_asciipart, word, hword, hword_part
  WITH english_us_hunspell, english_stem;


CREATE FUNCTION escape_html(text) RETURNS text IMMUTABLE LANGUAGE 'sql' AS $$
  SELECT replace(replace(replace(replace(replace($1, '&', '&amp;'), '<', '&lt;'),
                                 '>', '&gt;'), '"', '&quot;'), '''', '&#39;');
$$ ;

ALTER TABLE zerver_message ADD COLUMN search_tsvector tsvector;
CREATE INDEX zerver_message_search_tsvector ON zerver_message USING gin(search_tsvector);
ALTER INDEX zerver_message_search_tsvector SET (fastupdate = OFF);

CREATE TABLE fts_update_log (id SERIAL PRIMARY KEY, message_id INTEGER NOT NULL);
CREATE FUNCTION do_notify_fts_update_log() RETURNS trigger LANGUAGE plpgsql AS
  $$ BEGIN NOTIFY fts_update_log; RETURN NEW; END $$;
CREATE TRIGGER fts_update_log_notify AFTER INSERT ON fts_update_log
  FOR EACH STATEMENT EXECUTE PROCEDURE do_notify_fts_update_log();
CREATE FUNCTION append_to_fts_update_log() RETURNS trigger LANGUAGE plpgsql AS
  $$ BEGIN INSERT INTO fts_update_log (message_id) VALUES (NEW.id); RETURN NEW; END $$;
CREATE TRIGGER zerver_message_update_search_tsvector_async
  BEFORE INSERT OR UPDATE OF subject, rendered_content ON zerver_message
  FOR EACH ROW EXECUTE PROCEDURE append_to_fts_update_log();
"""

SQL_2 = """CREATE INDEX upper_subject_idx ON zerver_message ((upper(subject)));"""

SQL_2_ROLLBACK = """DROP INDEX upper_subject_idx;"""

SQL_3 = """CREATE INDEX upper_stream_name_idx ON zerver_stream ((upper(name)));"""

SQL_3_ROLLBACK = """DROP INDEX upper_stream_name_idx;"""

SQL_4 = """CREATE INDEX upper_userprofile_email_idx ON zerver_userprofile ((upper(email)));"""

SQL_4_ROLLBACK = """DROP INDEX upper_userprofile_email_idx;"""

SQL_5 = """CREATE INDEX upper_preregistration_email_idx ON zerver_preregistrationuser ((upper(email)));"""

SQL_5_ROLLBACK = """DROP INDEX upper_preregistration_email_idx;"""

SQL_6 = """
            CREATE INDEX IF NOT EXISTS zerver_usermessage_starred_message_id
                ON zerver_usermessage (user_profile_id, message_id)
                WHERE (flags & 2) != 0;
            """

SQL_6_ROLLBACK = """DROP INDEX zerver_usermessage_starred_message_id;"""

SQL_7 = """
            CREATE INDEX IF NOT EXISTS zerver_usermessage_mentioned_message_id
                ON zerver_usermessage (user_profile_id, message_id)
                WHERE (flags & 8) != 0;
            """

SQL_7_ROLLBACK = """DROP INDEX zerver_usermessage_mentioned_message_id;"""

SQL_8 = """
            CREATE INDEX IF NOT EXISTS zerver_usermessage_unread_message_id
                ON zerver_usermessage (user_profile_id, message_id)
                WHERE (flags & 1) = 0;
            """

SQL_8_ROLLBACK = """DROP INDEX zerver_usermessage_unread_message_id;"""

SQL_9 = """
            CREATE INDEX IF NOT EXISTS zerver_usermessage_has_alert_word_message_id
                ON zerver_usermessage (user_profile_id, message_id)
                WHERE (flags & 512) != 0;
            """

SQL_9_ROLLBACK = """DROP INDEX zerver_usermessage_has_alert_word_message_id;"""

SQL_10 = """
            CREATE INDEX IF NOT EXISTS zerver_usermessage_wildcard_mentioned_message_id
                ON zerver_usermessage (user_profile_id, message_id)
                WHERE (flags & 8) != 0 OR (flags & 16) != 0;
            """

SQL_10_ROLLBACK = """DROP INDEX zerver_usermessage_wilcard_mentioned_message_id;"""

SQL_11 = """
            CREATE INDEX zerver_mutedtopic_stream_topic
            ON zerver_mutedtopic
            (stream_id, upper(topic_name))
            """

SQL_11_ROLLBACK = """DROP INDEX zerver_mutedtopic_stream_topic;"""

SQL_12 = """
            CREATE INDEX IF NOT EXISTS zerver_usermessage_is_private_message_id
                ON zerver_usermessage (user_profile_id, message_id)
                WHERE (flags & 2048) != 0;
            """

SQL_12_ROLLBACK = """DROP INDEX zerver_usermessage_is_private_message_id;"""

SQL_13 = """
            CREATE INDEX IF NOT EXISTS zerver_usermessage_active_mobile_push_notification_id
                ON zerver_usermessage (user_profile_id, message_id)
                WHERE (flags & 4096) != 0;
            """

SQL_13_ROLLBACK = """DROP INDEX zerver_usermessage_active_mobile_push_notification_id;"""

SQL_14 = """
        BEGIN;
        DELETE FROM zerver_archivedusermessage;
        DELETE FROM zerver_archivedreaction;
        DELETE FROM zerver_archivedsubmessage;
        DELETE FROM zerver_archivedattachment_messages;
        DELETE FROM zerver_archivedattachment;
        DELETE FROM zerver_archivedmessage;
        DELETE FROM zerver_archivetransaction;
        COMMIT;
        """

SQL_15 = """
        CREATE FUNCTION zerver_usermessage_bigint_id_to_id_trigger_function()
        RETURNS trigger AS $$
        BEGIN
            NEW.bigint_id = NEW.id;
            RETURN NEW;
        END
        $$ LANGUAGE 'plpgsql';

        CREATE TRIGGER zerver_usermessage_bigint_id_to_id_trigger
        BEFORE INSERT ON zerver_usermessage
        FOR EACH ROW
        EXECUTE PROCEDURE zerver_usermessage_bigint_id_to_id_trigger_function();
        """

SQL_16 = """
        CREATE UNIQUE INDEX CONCURRENTLY zerver_usermessage_bigint_id_idx ON zerver_usermessage (bigint_id);
        """

SQL_17 = """
            DROP TRIGGER zerver_usermessage_bigint_id_to_id_trigger ON zerver_usermessage;
            DROP FUNCTION zerver_usermessage_bigint_id_to_id_trigger_function();

            ALTER TABLE zerver_usermessage ALTER COLUMN bigint_id SET NOT NULL;
            ALTER TABLE zerver_usermessage DROP CONSTRAINT zerver_usermessage_pkey;
            DROP SEQUENCE zerver_usermessage_id_seq CASCADE;
            ALTER TABLE zerver_usermessage RENAME COLUMN id to id_old;
            ALTER TABLE zerver_usermessage RENAME COLUMN bigint_id to id;
            ALTER TABLE zerver_usermessage ADD CONSTRAINT zerver_usermessage_pkey PRIMARY KEY USING INDEX zerver_usermessage_bigint_id_idx;
            CREATE SEQUENCE zerver_usermessage_id_seq;
            SELECT SETVAL('zerver_usermessage_id_seq', (SELECT MAX(id)+1 FROM zerver_usermessage));
            ALTER TABLE zerver_usermessage ALTER COLUMN id SET DEFAULT NEXTVAL('zerver_usermessage_id_seq');
            ALTER TABLE zerver_usermessage ALTER COLUMN id_old DROP NOT NULL;
            """

SQL_18 = """ALTER TABLE zerver_usermessage DROP COLUMN id_old;"""

SQL_19 = """
        CREATE FUNCTION zerver_message_date_sent_to_pub_date_trigger_function()
        RETURNS trigger AS $$
        BEGIN
            NEW.date_sent = NEW.pub_date;
            RETURN NEW;
        END
        $$ LANGUAGE 'plpgsql';

        CREATE TRIGGER zerver_message_date_sent_to_pub_date_trigger
        BEFORE INSERT ON zerver_message
        FOR EACH ROW
        EXECUTE PROCEDURE zerver_message_date_sent_to_pub_date_trigger_function();
        """

SQL_20 = """
        CREATE INDEX CONCURRENTLY zerver_message_date_sent_3b5b05d8 ON zerver_message (date_sent);
        """

SQL_21 = """
            DROP TRIGGER zerver_message_date_sent_to_pub_date_trigger ON zerver_message;
            DROP FUNCTION zerver_message_date_sent_to_pub_date_trigger_function();

            ALTER TABLE zerver_message ALTER COLUMN date_sent SET NOT NULL;
            ALTER TABLE zerver_message ALTER COLUMN pub_date DROP NOT NULL;
            """

SQL_22 = """
        ALTER INDEX IF EXISTS zerver_archivedmessage_pub_date_509062c8 RENAME TO zerver_archivedmessage_date_sent_509062c8
        """

SQL_23 = """
            UPDATE zerver_userprofile
            SET recipient_id = zerver_recipient.id
            FROM zerver_recipient
            WHERE zerver_recipient.type_id = zerver_userprofile.id AND zerver_recipient.type = 1;
            """

SQL_23_ROLLBACK = """UPDATE zerver_userprofile SET recipient_id = NULL"""

SQL_24 = """
            UPDATE zerver_stream
            SET recipient_id = zerver_recipient.id
            FROM zerver_recipient
            WHERE zerver_recipient.type_id = zerver_stream.id AND zerver_recipient.type = 2;
            """

SQL_24_ROLLBACK = """UPDATE zerver_stream SET recipient_id = NULL"""

SQL_25 = """
            UPDATE zerver_userpresence
            SET realm_id = zerver_userprofile.realm_id
            FROM zerver_userprofile
            WHERE zerver_userprofile.id = zerver_userpresence.user_profile_id;
            """

SQL_25_ROLLBACK = """UPDATE zerver_userpresence SET realm_id = NULL"""

SQL_26 = """
            UPDATE zerver_huddle
            SET recipient_id = zerver_recipient.id
            FROM zerver_recipient
            WHERE zerver_recipient.type_id = zerver_huddle.id AND zerver_recipient.type = 3;
            """

SQL_26_ROLLBACK = """UPDATE zerver_huddle SET recipient_id = NULL"""

class Migration(migrations.Migration):

    replaces = [('zerver', '0001_initial'), ('zerver', '0029_realm_subdomain'), ('zerver', '0030_realm_org_type'), ('zerver', '0031_remove_system_avatar_source'), ('zerver', '0032_verify_all_medium_avatar_images'), ('zerver', '0033_migrate_domain_to_realmalias'), ('zerver', '0034_userprofile_enable_online_push_notifications'), ('zerver', '0035_realm_message_retention_period_days'), ('zerver', '0036_rename_subdomain_to_string_id'), ('zerver', '0037_disallow_null_string_id'), ('zerver', '0038_realm_change_to_community_defaults'), ('zerver', '0039_realmalias_drop_uniqueness'), ('zerver', '0040_realm_authentication_methods'), ('zerver', '0041_create_attachments_for_old_messages'), ('zerver', '0042_attachment_file_name_length'), ('zerver', '0043_realm_filter_validators'), ('zerver', '0044_reaction'), ('zerver', '0045_realm_waiting_period_threshold'), ('zerver', '0046_realmemoji_author'), ('zerver', '0047_realm_add_emoji_by_admins_only'), ('zerver', '0048_enter_sends_default_to_false'), ('zerver', '0049_userprofile_pm_content_in_desktop_notifications'), ('zerver', '0050_userprofile_avatar_version'), ('zerver', '0051_realmalias_add_allow_subdomains'), ('zerver', '0052_auto_fix_realmalias_realm_nullable'), ('zerver', '0053_emailchangestatus'), ('zerver', '0054_realm_icon'), ('zerver', '0055_attachment_size'), ('zerver', '0056_userprofile_emoji_alt_code'), ('zerver', '0057_realmauditlog'), ('zerver', '0058_realm_email_changes_disabled'), ('zerver', '0059_userprofile_quota'), ('zerver', '0060_move_avatars_to_be_uid_based'), ('zerver', '0061_userprofile_timezone'), ('zerver', '0062_default_timezone'), ('zerver', '0063_realm_description'), ('zerver', '0064_sync_uploads_filesize_with_db'), ('zerver', '0065_realm_inline_image_preview'), ('zerver', '0066_realm_inline_url_embed_preview'), ('zerver', '0067_archived_models'), ('zerver', '0068_remove_realm_domain'), ('zerver', '0069_realmauditlog_extra_data'), ('zerver', '0070_userhotspot'), ('zerver', '0071_rename_realmalias_to_realmdomain'), ('zerver', '0072_realmauditlog_add_index_event_time'), ('zerver', '0073_custom_profile_fields'), ('zerver', '0074_fix_duplicate_attachments'), ('zerver', '0075_attachment_path_id_unique'), ('zerver', '0076_userprofile_emojiset'), ('zerver', '0077_add_file_name_field_to_realm_emoji'), ('zerver', '0078_service'), ('zerver', '0079_remove_old_scheduled_jobs'), ('zerver', '0080_realm_description_length'), ('zerver', '0081_make_emoji_lowercase'), ('zerver', '0082_index_starred_user_messages'), ('zerver', '0083_index_mentioned_user_messages'), ('zerver', '0084_realmemoji_deactivated'), ('zerver', '0085_fix_bots_with_none_bot_type'), ('zerver', '0086_realm_alter_default_org_type'), ('zerver', '0087_remove_old_scheduled_jobs'), ('zerver', '0088_remove_referral_and_invites'), ('zerver', '0089_auto_20170710_1353'), ('zerver', '0090_userprofile_high_contrast_mode'), ('zerver', '0091_realm_allow_edit_history'), ('zerver', '0092_create_scheduledemail'), ('zerver', '0093_subscription_event_log_backfill'), ('zerver', '0094_realm_filter_url_validator'), ('zerver', '0095_index_unread_user_messages'), ('zerver', '0096_add_password_required'), ('zerver', '0097_reactions_emoji_code'), ('zerver', '0098_index_has_alert_word_user_messages'), ('zerver', '0099_index_wildcard_mentioned_user_messages'), ('zerver', '0100_usermessage_remove_is_me_message'), ('zerver', '0101_muted_topic'), ('zerver', '0102_convert_muted_topic'), ('zerver', '0103_remove_userprofile_muted_topics'), ('zerver', '0104_fix_unreads'), ('zerver', '0105_userprofile_enable_stream_push_notifications'), ('zerver', '0106_subscription_push_notifications'), ('zerver', '0107_multiuseinvite'), ('zerver', '0108_fix_default_string_id'), ('zerver', '0109_mark_tutorial_status_finished'), ('zerver', '0110_stream_is_in_zephyr_realm'), ('zerver', '0111_botuserstatedata'), ('zerver', '0112_index_muted_topics'), ('zerver', '0113_default_stream_group'), ('zerver', '0114_preregistrationuser_invited_as_admin'), ('zerver', '0115_user_groups'), ('zerver', '0116_realm_allow_message_deleting'), ('zerver', '0117_add_desc_to_user_group'), ('zerver', '0118_defaultstreamgroup_description'), ('zerver', '0119_userprofile_night_mode'), ('zerver', '0120_botuserconfigdata'), ('zerver', '0121_realm_signup_notifications_stream'), ('zerver', '0122_rename_botuserstatedata_botstoragedata'), ('zerver', '0123_userprofile_make_realm_email_pair_unique'), ('zerver', '0124_stream_enable_notifications'), ('zerver', '0125_realm_max_invites'), ('zerver', '0126_prereg_remove_users_without_realm'), ('zerver', '0127_disallow_chars_in_stream_and_user_name'), ('zerver', '0128_scheduledemail_realm'), ('zerver', '0129_remove_userprofile_autoscroll_forever'), ('zerver', '0130_text_choice_in_emojiset'), ('zerver', '0131_realm_create_generic_bot_by_admins_only'), ('zerver', '0132_realm_message_visibility_limit'), ('zerver', '0133_rename_botuserconfigdata_botconfigdata'), ('zerver', '0134_scheduledmessage'), ('zerver', '0135_scheduledmessage_delivery_type'), ('zerver', '0136_remove_userprofile_quota'), ('zerver', '0137_realm_upload_quota_gb'), ('zerver', '0138_userprofile_realm_name_in_notifications'), ('zerver', '0139_fill_last_message_id_in_subscription_logs'), ('zerver', '0140_realm_send_welcome_emails'), ('zerver', '0141_change_usergroup_description_to_textfield'), ('zerver', '0142_userprofile_translate_emoticons'), ('zerver', '0143_realm_bot_creation_policy'), ('zerver', '0144_remove_realm_create_generic_bot_by_admins_only'), ('zerver', '0145_reactions_realm_emoji_name_to_id'), ('zerver', '0146_userprofile_message_content_in_email_notifications'), ('zerver', '0147_realm_disallow_disposable_email_addresses'), ('zerver', '0148_max_invites_forget_default'), ('zerver', '0149_realm_emoji_drop_unique_constraint'), ('zerver', '0150_realm_allow_community_topic_editing'), ('zerver', '0151_last_reminder_default_none'), ('zerver', '0152_realm_default_twenty_four_hour_time'), ('zerver', '0153_remove_int_float_custom_fields'), ('zerver', '0154_fix_invalid_bot_owner'), ('zerver', '0155_change_default_realm_description'), ('zerver', '0156_add_hint_to_profile_field'), ('zerver', '0157_userprofile_is_guest'), ('zerver', '0158_realm_video_chat_provider'), ('zerver', '0159_realm_google_hangouts_domain'), ('zerver', '0160_add_choice_field'), ('zerver', '0161_realm_message_content_delete_limit_seconds'), ('zerver', '0162_change_default_community_topic_editing'), ('zerver', '0163_remove_userprofile_default_desktop_notifications'), ('zerver', '0164_stream_history_public_to_subscribers'), ('zerver', '0165_add_date_to_profile_field'), ('zerver', '0166_add_url_to_profile_field'), ('zerver', '0167_custom_profile_fields_sort_order'), ('zerver', '0168_stream_is_web_public'), ('zerver', '0169_stream_is_announcement_only'), ('zerver', '0170_submessage'), ('zerver', '0171_userprofile_dense_mode'), ('zerver', '0172_add_user_type_of_custom_profile_field'), ('zerver', '0173_support_seat_based_plans'), ('zerver', '0174_userprofile_delivery_email'), ('zerver', '0175_change_realm_audit_log_event_type_tense'), ('zerver', '0176_remove_subscription_notifications'), ('zerver', '0177_user_message_add_and_index_is_private_flag'), ('zerver', '0178_rename_to_emails_restricted_to_domains'), ('zerver', '0179_rename_to_digest_emails_enabled'), ('zerver', '0180_usermessage_add_active_mobile_push_notification'), ('zerver', '0181_userprofile_change_emojiset'), ('zerver', '0182_set_initial_value_is_private_flag'), ('zerver', '0183_change_custom_field_name_max_length'), ('zerver', '0184_rename_custom_field_types'), ('zerver', '0185_realm_plan_type'), ('zerver', '0186_userprofile_starred_message_counts'), ('zerver', '0187_userprofile_is_billing_admin'), ('zerver', '0188_userprofile_enable_login_emails'), ('zerver', '0189_userprofile_add_some_emojisets'), ('zerver', '0190_cleanup_pushdevicetoken'), ('zerver', '0191_realm_seat_limit'), ('zerver', '0192_customprofilefieldvalue_rendered_value'), ('zerver', '0193_realm_email_address_visibility'), ('zerver', '0194_userprofile_notification_sound'), ('zerver', '0195_realm_first_visible_message_id'), ('zerver', '0196_add_realm_logo_fields'), ('zerver', '0197_azure_active_directory_auth'), ('zerver', '0198_preregistrationuser_invited_as'), ('zerver', '0199_userstatus'), ('zerver', '0200_remove_preregistrationuser_invited_as_admin'), ('zerver', '0201_zoom_video_chat'), ('zerver', '0202_add_user_status_info'), ('zerver', '0203_realm_message_content_allowed_in_email_notifications'), ('zerver', '0204_remove_realm_billing_fields'), ('zerver', '0205_remove_realmauditlog_requires_billing_update'), ('zerver', '0206_stream_rendered_description'), ('zerver', '0207_multiuseinvite_invited_as'), ('zerver', '0208_add_realm_night_logo_fields'), ('zerver', '0209_stream_first_message_id'), ('zerver', '0209_user_profile_no_empty_password'), ('zerver', '0210_stream_first_message_id'), ('zerver', '0211_add_users_field_to_scheduled_email'), ('zerver', '0212_make_stream_email_token_unique'), ('zerver', '0213_realm_digest_weekday'), ('zerver', '0214_realm_invite_to_stream_policy'), ('zerver', '0215_realm_avatar_changes_disabled'), ('zerver', '0216_add_create_stream_policy'), ('zerver', '0217_migrate_create_stream_policy'), ('zerver', '0218_remove_create_stream_by_admins_only'), ('zerver', '0219_toggle_realm_digest_emails_enabled_default'), ('zerver', '0220_subscription_notification_settings'), ('zerver', '0221_subscription_notifications_data_migration'), ('zerver', '0222_userprofile_fluid_layout_width'), ('zerver', '0223_rename_to_is_muted'), ('zerver', '0224_alter_field_realm_video_chat_provider'), ('zerver', '0225_archived_reaction_model'), ('zerver', '0226_archived_submessage_model'), ('zerver', '0227_inline_url_embed_preview_default_off'), ('zerver', '0228_userprofile_demote_inactive_streams'), ('zerver', '0229_stream_message_retention_days'), ('zerver', '0230_rename_to_enable_stream_audible_notifications'), ('zerver', '0231_add_archive_transaction_model'), ('zerver', '0232_make_archive_transaction_field_not_nullable'), ('zerver', '0233_userprofile_avatar_hash'), ('zerver', '0234_add_external_account_custom_profile_field'), ('zerver', '0235_userprofile_desktop_icon_count_display'), ('zerver', '0236_remove_illegal_characters_email_full'), ('zerver', '0237_rename_zulip_realm_to_zulipinternal'), ('zerver', '0238_usermessage_bigint_id'), ('zerver', '0239_usermessage_copy_id_to_bigint_id'), ('zerver', '0240_usermessage_migrate_bigint_id_into_id'), ('zerver', '0241_usermessage_bigint_id_migration_finalize'), ('zerver', '0242_fix_bot_email_property'), ('zerver', '0243_message_add_date_sent_column'), ('zerver', '0244_message_copy_pub_date_to_date_sent'), ('zerver', '0245_message_date_sent_finalize_part1'), ('zerver', '0246_message_date_sent_finalize_part2'), ('zerver', '0247_realmauditlog_event_type_to_int'), ('zerver', '0248_userprofile_role_start'), ('zerver', '0249_userprofile_role_finish'), ('zerver', '0250_saml_auth'), ('zerver', '0251_prereg_user_add_full_name'), ('zerver', '0252_realm_user_group_edit_policy'), ('zerver', '0253_userprofile_wildcard_mentions_notify'), ('zerver', '0254_merge_0209_0253'), ('zerver', '0255_userprofile_stream_add_recipient_column'), ('zerver', '0256_userprofile_stream_set_recipient_column_values'), ('zerver', '0257_fix_has_link_attribute'), ('zerver', '0258_enable_online_push_notifications_default'), ('zerver', '0259_missedmessageemailaddress'), ('zerver', '0260_missed_message_addresses_from_redis_to_db'), ('zerver', '0261_realm_private_message_policy'), ('zerver', '0262_mutedtopic_date_muted'), ('zerver', '0263_stream_stream_post_policy'), ('zerver', '0264_migrate_is_announcement_only'), ('zerver', '0265_remove_stream_is_announcement_only'), ('zerver', '0266_userpresence_realm'), ('zerver', '0267_backfill_userpresence_realm_id'), ('zerver', '0268_add_userpresence_realm_timestamp_index'), ('zerver', '0269_gitlab_auth'), ('zerver', '0270_huddle_recipient'), ('zerver', '0271_huddle_set_recipient_column_values'), ('zerver', '0272_realm_default_code_block_language')]

    initial = True

    dependencies = [
        ('auth', '0011_update_proxy_permissions'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserProfile',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.', verbose_name='superuser status')),
                ('delivery_email', models.EmailField(db_index=True, max_length=254)),
                ('email', models.EmailField(db_index=True, max_length=254)),
                ('full_name', models.CharField(max_length=100)),
                ('short_name', models.CharField(max_length=100)),
                ('date_joined', models.DateTimeField(default=django.utils.timezone.now)),
                ('tos_version', models.CharField(max_length=10, null=True)),
                ('api_key', models.CharField(max_length=32)),
                ('pointer', models.IntegerField()),
                ('last_pointer_updater', models.CharField(max_length=64)),
                ('is_staff', models.BooleanField(default=False)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('is_billing_admin', models.BooleanField(db_index=True, default=False)),
                ('is_bot', models.BooleanField(db_index=True, default=False)),
                ('bot_type', models.PositiveSmallIntegerField(db_index=True, null=True)),
                ('role', models.PositiveSmallIntegerField(db_index=True, default=400)),
                ('long_term_idle', models.BooleanField(db_index=True, default=False)),
                ('last_active_message_id', models.IntegerField(null=True)),
                ('is_mirror_dummy', models.BooleanField(default=False)),
                ('is_api_super_user', models.BooleanField(db_index=True, default=False)),
                ('enable_stream_desktop_notifications', models.BooleanField(default=False)),
                ('enable_stream_email_notifications', models.BooleanField(default=False)),
                ('enable_stream_push_notifications', models.BooleanField(default=False)),
                ('enable_stream_audible_notifications', models.BooleanField(default=False)),
                ('notification_sound', models.CharField(default='zulip', max_length=20)),
                ('wildcard_mentions_notify', models.BooleanField(default=True)),
                ('enable_desktop_notifications', models.BooleanField(default=True)),
                ('pm_content_in_desktop_notifications', models.BooleanField(default=True)),
                ('enable_sounds', models.BooleanField(default=True)),
                ('enable_offline_email_notifications', models.BooleanField(default=True)),
                ('message_content_in_email_notifications', models.BooleanField(default=True)),
                ('enable_offline_push_notifications', models.BooleanField(default=True)),
                ('enable_online_push_notifications', models.BooleanField(default=True)),
                ('desktop_icon_count_display', models.PositiveSmallIntegerField(default=1)),
                ('enable_digest_emails', models.BooleanField(default=True)),
                ('enable_login_emails', models.BooleanField(default=True)),
                ('realm_name_in_notifications', models.BooleanField(default=False)),
                ('alert_words', models.TextField(default='[]')),
                ('last_reminder', models.DateTimeField(default=None, null=True)),
                ('rate_limits', models.CharField(default='', max_length=100)),
                ('default_all_public_streams', models.BooleanField(default=False)),
                ('enter_sends', models.NullBooleanField(default=False)),
                ('left_side_userlist', models.BooleanField(default=False)),
                ('default_language', models.CharField(default='en', max_length=50)),
                ('dense_mode', models.BooleanField(default=True)),
                ('fluid_layout_width', models.BooleanField(default=False)),
                ('high_contrast_mode', models.BooleanField(default=False)),
                ('night_mode', models.BooleanField(default=False)),
                ('translate_emoticons', models.BooleanField(default=False)),
                ('twenty_four_hour_time', models.BooleanField(default=False)),
                ('starred_message_counts', models.BooleanField(default=False)),
                ('demote_inactive_streams', models.PositiveSmallIntegerField(default=1)),
                ('timezone', models.CharField(default='', max_length=40)),
                ('emojiset', models.CharField(choices=[('google', 'Google modern'), ('google-blob', 'Google classic'), ('twitter', 'Twitter'), ('text', 'Plain text')], default='google-blob', max_length=20)),
                ('avatar_source', models.CharField(choices=[('G', 'Hosted by Gravatar'), ('U', 'Uploaded by user')], default='G', max_length=1)),
                ('avatar_version', models.PositiveSmallIntegerField(default=1)),
                ('avatar_hash', models.CharField(max_length=64, null=True)),
                ('tutorial_status', models.CharField(choices=[('W', 'Waiting'), ('S', 'Started'), ('F', 'Finished')], default='W', max_length=1)),
                ('onboarding_steps', models.TextField(default='[]')),
                ('bot_owner', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            managers=[
                ('objects', django.contrib.auth.models.UserManager()),
            ],
        ),
        migrations.CreateModel(
            name='ArchivedMessage',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('subject', models.CharField(db_index=True, max_length=60)),
                ('content', models.TextField()),
                ('rendered_content', models.TextField(null=True)),
                ('rendered_content_version', models.IntegerField(null=True)),
                ('date_sent', models.DateTimeField(db_index=True, verbose_name='date sent')),
                ('last_edit_time', models.DateTimeField(null=True)),
                ('edit_history', models.TextField(null=True)),
                ('has_attachment', models.BooleanField(db_index=True, default=False)),
                ('has_image', models.BooleanField(db_index=True, default=False)),
                ('has_link', models.BooleanField(db_index=True, default=False)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Client',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(db_index=True, max_length=30, unique=True)),
            ],
        ),
        migrations.CreateModel(
            name='Message',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('subject', models.CharField(db_index=True, max_length=60)),
                ('content', models.TextField()),
                ('rendered_content', models.TextField(null=True)),
                ('rendered_content_version', models.IntegerField(null=True)),
                ('date_sent', models.DateTimeField(db_index=True, verbose_name='date sent')),
                ('last_edit_time', models.DateTimeField(null=True)),
                ('edit_history', models.TextField(null=True)),
                ('has_attachment', models.BooleanField(db_index=True, default=False)),
                ('has_image', models.BooleanField(db_index=True, default=False)),
                ('has_link', models.BooleanField(db_index=True, default=False)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Realm',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=40, null=True)),
                ('description', models.TextField(default='')),
                ('string_id', models.CharField(max_length=40, unique=True)),
                ('date_created', models.DateTimeField(default=django.utils.timezone.now)),
                ('deactivated', models.BooleanField(default=False)),
                ('emails_restricted_to_domains', models.BooleanField(default=False)),
                ('invite_required', models.BooleanField(default=True)),
                ('invite_by_admins_only', models.BooleanField(default=False)),
                ('_max_invites', models.IntegerField(db_column='max_invites', null=True)),
                ('disallow_disposable_email_addresses', models.BooleanField(default=True)),
                ('authentication_methods', bitfield.models.BitField(['Google', 'Email', 'GitHub', 'LDAP', 'Dev', 'RemoteUser', 'AzureAD', 'SAML', 'GitLab'], default=2147483647)),
                ('inline_image_preview', models.BooleanField(default=True)),
                ('inline_url_embed_preview', models.BooleanField(default=False)),
                ('digest_emails_enabled', models.BooleanField(default=False)),
                ('digest_weekday', models.SmallIntegerField(default=1)),
                ('send_welcome_emails', models.BooleanField(default=True)),
                ('message_content_allowed_in_email_notifications', models.BooleanField(default=True)),
                ('mandatory_topics', models.BooleanField(default=False)),
                ('add_emoji_by_admins_only', models.BooleanField(default=False)),
                ('name_changes_disabled', models.BooleanField(default=False)),
                ('email_changes_disabled', models.BooleanField(default=False)),
                ('avatar_changes_disabled', models.BooleanField(default=False)),
                ('create_stream_policy', models.PositiveSmallIntegerField(default=1)),
                ('invite_to_stream_policy', models.PositiveSmallIntegerField(default=1)),
                ('user_group_edit_policy', models.PositiveSmallIntegerField(default=1)),
                ('private_message_policy', models.PositiveSmallIntegerField(default=1)),
                ('email_address_visibility', models.PositiveSmallIntegerField(default=1)),
                ('waiting_period_threshold', models.PositiveIntegerField(default=0)),
                ('allow_message_deleting', models.BooleanField(default=False)),
                ('message_content_delete_limit_seconds', models.IntegerField(default=600)),
                ('allow_message_editing', models.BooleanField(default=True)),
                ('message_content_edit_limit_seconds', models.IntegerField(default=600)),
                ('allow_edit_history', models.BooleanField(default=True)),
                ('allow_community_topic_editing', models.BooleanField(default=True)),
                ('default_twenty_four_hour_time', models.BooleanField(default=False)),
                ('default_language', models.CharField(default='en', max_length=50)),
                ('message_retention_days', models.IntegerField(null=True)),
                ('message_visibility_limit', models.IntegerField(null=True)),
                ('first_visible_message_id', models.IntegerField(default=0)),
                ('org_type', models.PositiveSmallIntegerField(default=1)),
                ('plan_type', models.PositiveSmallIntegerField(default=1)),
                ('bot_creation_policy', models.PositiveSmallIntegerField(default=1)),
                ('upload_quota_gb', models.IntegerField(null=True)),
                ('video_chat_provider', models.PositiveSmallIntegerField(default=1)),
                ('google_hangouts_domain', models.TextField(default='')),
                ('zoom_user_id', models.TextField(default='')),
                ('zoom_api_key', models.TextField(default='')),
                ('zoom_api_secret', models.TextField(default='')),
                ('default_code_block_language', models.TextField(default=None, null=True)),
                ('icon_source', models.CharField(choices=[('G', 'Hosted by Gravatar'), ('U', 'Uploaded by administrator')], default='G', max_length=1)),
                ('icon_version', models.PositiveSmallIntegerField(default=1)),
                ('logo_source', models.CharField(choices=[('D', 'Default to Zulip'), ('U', 'Uploaded by administrator')], default='D', max_length=1)),
                ('logo_version', models.PositiveSmallIntegerField(default=1)),
                ('night_logo_source', models.CharField(choices=[('D', 'Default to Zulip'), ('U', 'Uploaded by administrator')], default='D', max_length=1)),
                ('night_logo_version', models.PositiveSmallIntegerField(default=1)),
            ],
            options={
                'permissions': (('administer', 'Administer a realm'), ('api_super_user', 'Can send messages as other users for mirroring')),
            },
        ),
        migrations.CreateModel(
            name='Recipient',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('type_id', models.IntegerField(db_index=True)),
                ('type', models.PositiveSmallIntegerField(db_index=True)),
            ],
            options={
                'unique_together': {('type', 'type_id')},
            },
        ),
        migrations.CreateModel(
            name='UserGroup',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('description', models.TextField(default='')),
            ],
        ),
        migrations.CreateModel(
            name='UserStatus',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timestamp', models.DateTimeField()),
                ('status', models.PositiveSmallIntegerField(default=0)),
                ('status_text', models.CharField(default='', max_length=255)),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Client')),
                ('user_profile', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='UserGroupMembership',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('user_group', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.UserGroup')),
                ('user_profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'unique_together': {('user_group', 'user_profile')},
            },
        ),
        migrations.AddField(
            model_name='usergroup',
            name='members',
            field=models.ManyToManyField(through='zerver.UserGroupMembership', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='usergroup',
            name='realm',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm'),
        ),
        migrations.CreateModel(
            name='UserActivityInterval',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('start', models.DateTimeField(db_index=True, verbose_name='start time')),
                ('end', models.DateTimeField(db_index=True, verbose_name='end time')),
                ('user_profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='SubMessage',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('msg_type', models.TextField()),
                ('content', models.TextField()),
                ('message', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Message')),
                ('sender', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Stream',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(db_index=True, max_length=60)),
                ('date_created', models.DateTimeField(default=django.utils.timezone.now)),
                ('deactivated', models.BooleanField(default=False)),
                ('description', models.CharField(default='', max_length=1024)),
                ('rendered_description', models.TextField(default='')),
                ('invite_only', models.NullBooleanField(default=False)),
                ('history_public_to_subscribers', models.BooleanField(default=False)),
                ('is_web_public', models.BooleanField(default=False)),
                ('stream_post_policy', models.PositiveSmallIntegerField(default=1)),
                ('is_in_zephyr_realm', models.BooleanField(default=False)),
                ('email_token', models.CharField(default=zerver.models.generate_email_token_for_stream, max_length=32, unique=True)),
                ('message_retention_days', models.IntegerField(default=None, null=True)),
                ('first_message_id', models.IntegerField(db_index=True, null=True)),
                ('realm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm')),
                ('recipient', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='zerver.Recipient')),
            ],
            options={
                'unique_together': {('name', 'realm')},
            },
        ),
        migrations.CreateModel(
            name='Service',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('base_url', models.TextField()),
                ('token', models.TextField()),
                ('interface', models.PositiveSmallIntegerField(default=1)),
                ('user_profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='ScheduledMessage',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('subject', models.CharField(max_length=60)),
                ('content', models.TextField()),
                ('scheduled_timestamp', models.DateTimeField(db_index=True)),
                ('delivered', models.BooleanField(default=False)),
                ('delivery_type', models.PositiveSmallIntegerField(choices=[(1, 'send_later'), (2, 'remind')], default=1)),
                ('realm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm')),
                ('recipient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Recipient')),
                ('sender', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ('sending_client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Client')),
                ('stream', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='zerver.Stream')),
            ],
        ),
        migrations.CreateModel(
            name='ScheduledEmail',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('scheduled_timestamp', models.DateTimeField(db_index=True)),
                ('data', models.TextField()),
                ('address', models.EmailField(db_index=True, max_length=254, null=True)),
                ('type', models.PositiveSmallIntegerField()),
                ('realm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm')),
                ('users', models.ManyToManyField(to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='RealmEmoji',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.TextField(validators=[django.core.validators.MinLengthValidator(1), django.core.validators.RegexValidator(message='Invalid characters in emoji name', regex='^[0-9a-z.\\-_]+(?<![.\\-_])$')])),
                ('file_name', models.TextField(blank=True, db_index=True, null=True)),
                ('deactivated', models.BooleanField(default=False)),
                ('author', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ('realm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm')),
            ],
        ),
        migrations.CreateModel(
            name='RealmAuditLog',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_time', models.DateTimeField(db_index=True)),
                ('backfilled', models.BooleanField(default=False)),
                ('extra_data', models.TextField(null=True)),
                ('event_type', models.PositiveSmallIntegerField()),
                ('event_last_message_id', models.IntegerField(null=True)),
                ('acting_user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('modified_stream', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='zerver.Stream')),
                ('modified_user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('realm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.AddField(
            model_name='realm',
            name='notifications_stream',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='zerver.Stream'),
        ),
        migrations.AddField(
            model_name='realm',
            name='signup_notifications_stream',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='zerver.Stream'),
        ),
        migrations.CreateModel(
            name='PreregistrationUser',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(max_length=254)),
                ('full_name', models.CharField(max_length=100, null=True)),
                ('full_name_validated', models.BooleanField(default=False)),
                ('invited_at', models.DateTimeField(auto_now=True)),
                ('realm_creation', models.BooleanField(default=False)),
                ('password_required', models.BooleanField(default=True)),
                ('status', models.IntegerField(default=0)),
                ('invited_as', models.PositiveSmallIntegerField(default=1)),
                ('realm', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm')),
                ('referred_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ('streams', models.ManyToManyField(to='zerver.Stream')),
            ],
        ),
        migrations.CreateModel(
            name='MultiuseInvite',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('invited_as', models.PositiveSmallIntegerField(default=1)),
                ('realm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm')),
                ('referred_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ('streams', models.ManyToManyField(to='zerver.Stream')),
            ],
        ),
        migrations.CreateModel(
            name='MissedMessageEmailAddress',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email_token', models.CharField(db_index=True, max_length=34, unique=True)),
                ('timestamp', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('times_used', models.PositiveIntegerField(db_index=True, default=0)),
                ('message', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Message')),
                ('user_profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddField(
            model_name='message',
            name='recipient',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Recipient'),
        ),
        migrations.AddField(
            model_name='message',
            name='sender',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='message',
            name='sending_client',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Client'),
        ),
        migrations.CreateModel(
            name='Huddle',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('huddle_hash', models.CharField(db_index=True, max_length=40, unique=True)),
                ('recipient', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='zerver.Recipient')),
            ],
        ),
        migrations.CreateModel(
            name='EmailChangeStatus',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('new_email', models.EmailField(max_length=254)),
                ('old_email', models.EmailField(max_length=254)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('status', models.IntegerField(default=0)),
                ('realm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm')),
                ('user_profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='CustomProfileField',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=40)),
                ('hint', models.CharField(default='', max_length=80, null=True)),
                ('order', models.IntegerField(default=0)),
                ('field_type', models.PositiveSmallIntegerField(choices=[(1, 'Short text'), (2, 'Long text'), (4, 'Date picker'), (5, 'Link'), (7, 'External account'), (3, 'List of options'), (6, 'Person picker')], default=1)),
                ('field_data', models.TextField(default='', null=True)),
                ('realm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm')),
            ],
            options={
                'unique_together': {('realm', 'name')},
            },
        ),
        migrations.CreateModel(
            name='Attachment',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file_name', models.TextField(db_index=True)),
                ('path_id', models.TextField(db_index=True, unique=True)),
                ('create_time', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('size', models.IntegerField(null=True)),
                ('is_realm_public', models.BooleanField(default=False)),
                ('messages', models.ManyToManyField(to='zerver.Message')),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ('realm', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='ArchiveTransaction',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timestamp', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('restored', models.BooleanField(db_index=True, default=False)),
                ('type', models.PositiveSmallIntegerField(db_index=True)),
                ('realm', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm')),
            ],
        ),
        migrations.CreateModel(
            name='ArchivedSubMessage',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('msg_type', models.TextField()),
                ('content', models.TextField()),
                ('message', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.ArchivedMessage')),
                ('sender', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.AddField(
            model_name='archivedmessage',
            name='archive_transaction',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.ArchiveTransaction'),
        ),
        migrations.AddField(
            model_name='archivedmessage',
            name='recipient',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Recipient'),
        ),
        migrations.AddField(
            model_name='archivedmessage',
            name='sender',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='archivedmessage',
            name='sending_client',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Client'),
        ),
        migrations.CreateModel(
            name='ArchivedAttachment',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file_name', models.TextField(db_index=True)),
                ('path_id', models.TextField(db_index=True, unique=True)),
                ('create_time', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('size', models.IntegerField(null=True)),
                ('is_realm_public', models.BooleanField(default=False)),
                ('messages', models.ManyToManyField(to='zerver.ArchivedMessage')),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ('realm', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.AddField(
            model_name='userprofile',
            name='default_events_register_stream',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='zerver.Stream'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='default_sending_stream',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='zerver.Stream'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='groups',
            field=models.ManyToManyField(blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.', related_name='user_set', related_query_name='user', to='auth.Group', verbose_name='groups'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='realm',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='recipient',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='zerver.Recipient'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='user_permissions',
            field=models.ManyToManyField(blank=True, help_text='Specific permissions for this user.', related_name='user_set', related_query_name='user', to='auth.Permission', verbose_name='user permissions'),
        ),
        migrations.CreateModel(
            name='UserPresence',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timestamp', models.DateTimeField(verbose_name='presence changed')),
                ('status', models.PositiveSmallIntegerField(default=1)),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Client')),
                ('realm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm')),
                ('user_profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'unique_together': {('user_profile', 'client')},
                'index_together': {('realm', 'timestamp')},
            },
        ),
        migrations.CreateModel(
            name='UserMessage',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('flags', bitfield.models.BitField(['read', 'starred', 'collapsed', 'mentioned', 'wildcard_mentioned', 'summarize_in_home', 'summarize_in_stream', 'force_expand', 'force_collapse', 'has_alert_word', 'historical', 'is_private', 'active_mobile_push_notification'], default=0)),
                ('message', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Message')),
                ('user_profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
                'unique_together': {('user_profile', 'message')},
            },
        ),
        migrations.CreateModel(
            name='UserHotspot',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('hotspot', models.CharField(max_length=30)),
                ('timestamp', models.DateTimeField(default=django.utils.timezone.now)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'unique_together': {('user', 'hotspot')},
            },
        ),
        migrations.AlterUniqueTogether(
            name='usergroup',
            unique_together={('realm', 'name')},
        ),
        migrations.CreateModel(
            name='UserActivity',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('query', models.CharField(db_index=True, max_length=50)),
                ('count', models.IntegerField()),
                ('last_visit', models.DateTimeField(verbose_name='last visit')),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Client')),
                ('user_profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'unique_together': {('user_profile', 'client', 'query')},
            },
        ),
        migrations.CreateModel(
            name='Subscription',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('active', models.BooleanField(default=True)),
                ('is_muted', models.NullBooleanField(default=False)),
                ('color', models.CharField(default='#c2c2c2', max_length=10)),
                ('pin_to_top', models.BooleanField(default=False)),
                ('desktop_notifications', models.NullBooleanField(default=None)),
                ('audible_notifications', models.NullBooleanField(default=None)),
                ('push_notifications', models.NullBooleanField(default=None)),
                ('email_notifications', models.NullBooleanField(default=None)),
                ('wildcard_mentions_notify', models.NullBooleanField(default=None)),
                ('recipient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Recipient')),
                ('user_profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'unique_together': {('user_profile', 'recipient')},
            },
        ),
        migrations.CreateModel(
            name='RealmFilter',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pattern', models.TextField(validators=[zerver.models.filter_pattern_validator])),
                ('url_format_string', models.TextField(validators=[django.core.validators.URLValidator(), zerver.models.filter_format_validator])),
                ('realm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm')),
            ],
            options={
                'unique_together': {('realm', 'pattern')},
            },
        ),
        migrations.CreateModel(
            name='RealmDomain',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('domain', models.CharField(db_index=True, max_length=80)),
                ('allow_subdomains', models.BooleanField(default=False)),
                ('realm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm')),
            ],
            options={
                'unique_together': {('realm', 'domain')},
            },
        ),
        migrations.CreateModel(
            name='Reaction',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('emoji_name', models.TextField()),
                ('reaction_type', models.CharField(choices=[('unicode_emoji', 'Unicode emoji'), ('realm_emoji', 'Custom emoji'), ('zulip_extra_emoji', 'Zulip extra emoji')], default='unicode_emoji', max_length=30)),
                ('emoji_code', models.TextField()),
                ('message', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Message')),
                ('user_profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
                'unique_together': {('user_profile', 'message', 'emoji_name')},
            },
        ),
        migrations.CreateModel(
            name='PushDeviceToken',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.PositiveSmallIntegerField(choices=[(1, 'apns'), (2, 'gcm')])),
                ('token', models.CharField(db_index=True, max_length=4096)),
                ('last_updated', models.DateTimeField(auto_now=True)),
                ('ios_app_id', models.TextField(null=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'unique_together': {('user', 'kind', 'token')},
            },
        ),
        migrations.CreateModel(
            name='MutedTopic',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('topic_name', models.CharField(max_length=60)),
                ('date_muted', models.DateTimeField(default=datetime.datetime(2020, 1, 1, 0, 0))),
                ('recipient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Recipient')),
                ('stream', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Stream')),
                ('user_profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'unique_together': {('user_profile', 'stream', 'topic_name')},
            },
        ),
        migrations.CreateModel(
            name='DefaultStreamGroup',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(db_index=True, max_length=60)),
                ('description', models.CharField(default='', max_length=1024)),
                ('realm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm')),
                ('streams', models.ManyToManyField(to='zerver.Stream')),
            ],
            options={
                'unique_together': {('realm', 'name')},
            },
        ),
        migrations.CreateModel(
            name='DefaultStream',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('realm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm')),
                ('stream', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Stream')),
            ],
            options={
                'unique_together': {('realm', 'stream')},
            },
        ),
        migrations.CreateModel(
            name='CustomProfileFieldValue',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('value', models.TextField()),
                ('rendered_value', models.TextField(default=None, null=True)),
                ('field', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.CustomProfileField')),
                ('user_profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'unique_together': {('user_profile', 'field')},
            },
        ),
        migrations.CreateModel(
            name='BotStorageData',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.TextField(db_index=True)),
                ('value', models.TextField()),
                ('bot_profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'unique_together': {('bot_profile', 'key')},
            },
        ),
        migrations.CreateModel(
            name='BotConfigData',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.TextField(db_index=True)),
                ('value', models.TextField()),
                ('bot_profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'unique_together': {('bot_profile', 'key')},
            },
        ),
        migrations.CreateModel(
            name='ArchivedUserMessage',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('flags', bitfield.models.BitField(['read', 'starred', 'collapsed', 'mentioned', 'wildcard_mentioned', 'summarize_in_home', 'summarize_in_stream', 'force_expand', 'force_collapse', 'has_alert_word', 'historical', 'is_private', 'active_mobile_push_notification'], default=0)),
                ('message', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.ArchivedMessage')),
                ('user_profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
                'unique_together': {('user_profile', 'message')},
            },
        ),
        migrations.CreateModel(
            name='ArchivedReaction',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('emoji_name', models.TextField()),
                ('reaction_type', models.CharField(choices=[('unicode_emoji', 'Unicode emoji'), ('realm_emoji', 'Custom emoji'), ('zulip_extra_emoji', 'Zulip extra emoji')], default='unicode_emoji', max_length=30)),
                ('emoji_code', models.TextField()),
                ('message', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.ArchivedMessage')),
                ('user_profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
                'unique_together': {('user_profile', 'message', 'emoji_name')},
            },
        ),
        migrations.AlterUniqueTogether(
            name='userprofile',
            unique_together={('realm', 'email')},
        ),
        migrations.RunSQL(
            sql=SQL_1,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_2,
            reverse_sql=SQL_2_ROLLBACK,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_3,
            reverse_sql=SQL_3_ROLLBACK,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_4,
            reverse_sql=SQL_4_ROLLBACK,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_5,
            reverse_sql=SQL_5_ROLLBACK,
            elidable=False,
        ),
        migrations.RunPython(
            code=migrate_existing_attachment_data,
            elidable=False,
        ),
        migrations.RunPython(
            code=set_subdomain_of_default_realm,
            elidable=False,
        ),
        migrations.RunPython(
            code=verify_medium_avatar_image,
            elidable=False,
        ),
        migrations.RunPython(
            code=add_domain_to_realm_alias_if_needed,
            elidable=False,
        ),
        migrations.RunPython(
            code=set_string_id_using_domain,
            elidable=False,
        ),
        migrations.RunPython(
            code=check_and_create_attachments,
            elidable=False,
        ),
        migrations.RunPython(
            code=backfill_user_activations_and_deactivations,
            reverse_code=reverse_code,
            elidable=False,
        ),
        migrations.RunPython(
            code=move_avatars_to_be_uid_based,
            elidable=False,
        ),
        migrations.RunPython(
            code=sync_filesizes,
            reverse_code=reverse_sync_filesizes,
            elidable=False,
        ),
        migrations.RunPython(
            code=fix_duplicate_attachments,
            elidable=False,
        ),
        migrations.RunPython(
            code=upload_emoji_to_storage,
            elidable=False,
        ),
        migrations.RunPython(
            code=delete_old_scheduled_jobs,
            elidable=False,
        ),
        migrations.RunPython(
            code=emoji_to_lowercase,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_6,
            reverse_sql=SQL_6_ROLLBACK,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_7,
            reverse_sql=SQL_7_ROLLBACK,
            elidable=False,
        ),
        migrations.RunPython(
            code=fix_bot_type,
            elidable=False,
        ),
        migrations.RunPython(
            code=delete_old_scheduled_jobs_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=backfill_subscription_log_events,
            reverse_code=reverse_code_2,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_8,
            reverse_sql=SQL_8_ROLLBACK,
            elidable=False,
        ),
        migrations.RunPython(
            code=populate_new_fields,
            reverse_code=RunPython.noop_2_2,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_9,
            reverse_sql=SQL_9_ROLLBACK,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_10,
            reverse_sql=SQL_10_ROLLBACK,
            elidable=False,
        ),
        migrations.RunPython(
            code=convert_muted_topics,
            elidable=False,
        ),
        migrations.RunPython(
            code=fix_unreads,
            elidable=False,
        ),
        migrations.RunPython(
            code=fix_realm_string_ids,
            reverse_code=RunPython.noop_2_2_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=set_tutorial_status_to_finished,
            elidable=False,
        ),
        migrations.RunPython(
            code=populate_is_zephyr,
            reverse_code=RunPython.noop_2_2_2_2,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_11,
            reverse_sql=SQL_11_ROLLBACK,
            elidable=False,
        ),
        migrations.RunPython(
            code=set_initial_value_for_signup_notifications_stream,
            reverse_code=RunPython.noop_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=remove_prereg_users_without_realm,
            reverse_code=RunPython.noop_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=set_realm_for_existing_scheduledemails,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=change_emojiset,
            reverse_code=reverse_change_emojiset,
            elidable=False,
        ),
        migrations.RunPython(
            code=backfill_last_message_id,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=set_initial_value_for_bot_creation_policy,
            reverse_code=reverse_code_3,
            elidable=False,
        ),
        migrations.RunPython(
            code=realm_emoji_name_to_id,
            reverse_code=reversal,
            elidable=False,
        ),
        migrations.RunPython(
            code=migrate_realm_emoji_image_files,
            reverse_code=reversal_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=migrate_fix_invalid_bot_owner_values,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=set_initial_value_for_history_public_to_subscribers,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=migrate_set_order_value,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=copy_email_field,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=change_realm_audit_log_event_type_tense,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_12,
            reverse_sql=SQL_12_ROLLBACK,
            elidable=False,
        ),
        migrations.RunPython(
            code=reset_is_private_flag,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_13,
            reverse_sql=SQL_13_ROLLBACK,
            elidable=False,
        ),
        migrations.RunPython(
            code=change_emojiset_choice,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=set_initial_value_of_is_private_flag,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=change_emojiset_choice_2,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=set_initial_value_for_invited_as,
            reverse_code=reverse_code_4,
            elidable=False,
        ),
        migrations.RunPython(
            code=render_all_stream_descriptions,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=ensure_no_empty_passwords,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=backfill_first_message_id,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=set_users_for_existing_scheduledemails,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=handle_waiting_period,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=upgrade_create_stream_policy,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=disable_realm_digest_emails_enabled,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=update_notification_settings,
            reverse_code=reverse_notification_settings,
            elidable=False,
        ),
        migrations.RunPython(
            code=set_initial_value_for_is_muted,
            reverse_code=reverse_code_5,
            elidable=False,
        ),
        migrations.RunPython(
            code=update_existing_video_chat_provider_values,
            reverse_code=reverse_code_6,
            elidable=False,
        ),
        migrations.RunPython(
            code=disable_realm_inline_url_embed_preview,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_14,
            elidable=False,
        ),
        migrations.RunPython(
            code=remove_name_illegal_chars,
            elidable=False,
        ),
        migrations.RunPython(
            code=rename_zulip_realm_to_zulipinternal,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_15,
            elidable=False,
        ),
        migrations.RunPython(
            code=copy_id_to_bigid,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_16,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_17,
            state_operations=[migrations.RemoveField(
                model_name='usermessage',
                name='bigint_id',
            ), migrations.AlterField(
                model_name='usermessage',
                name='id',
                field=models.BigAutoField(primary_key=True, serialize=False),
            )],
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_18,
            elidable=False,
        ),
        migrations.RunPython(
            code=fix_bot_email_property,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_19,
            elidable=False,
        ),
        migrations.RunPython(
            code=copy_pub_date_to_date_sent,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_20,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_21,
            state_operations=[migrations.AlterField(
                model_name='message',
                name='date_sent',
                field=models.DateTimeField(db_index=True, verbose_name='date sent'),
            )],
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_22,
            elidable=False,
        ),
        migrations.RunPython(
            code=update_existing_event_type_values,
            reverse_code=reverse_code_7,
            elidable=False,
        ),
        migrations.RunPython(
            code=update_role,
            reverse_code=reverse_code_8,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_23,
            reverse_sql=SQL_23_ROLLBACK,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_24,
            reverse_sql=SQL_24_ROLLBACK,
            elidable=False,
        ),
        migrations.RunPython(
            code=fix_has_link,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=move_missed_message_addresses_to_database,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=upgrade_stream_post_policy,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_25,
            reverse_sql=SQL_25_ROLLBACK,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_26,
            reverse_sql=SQL_26_ROLLBACK,
            elidable=False,
        ),
    ]
