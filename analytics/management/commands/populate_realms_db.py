import itertools
import os
import random
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import bmemcached
import orjson
from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.files.base import File
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandParser
from django.db import connection
from django.db.models import F
from django.db.models.signals import post_delete
from django.utils.timezone import now as timezone_now
from typing_extensions import override
from corporate.lib.stripe import do_create_stripe_customer, update_or_create_stripe_customer
from corporate.models import Customer, CustomerPlan, LicenseLedger

from scripts.lib.zulip_tools import get_or_create_dev_uuid_var_path
from zerver.actions.create_realm import do_create_realm
from zerver.actions.custom_profile_fields import (
    do_update_user_custom_profile_data_if_changed,
    try_add_realm_custom_profile_field,
    try_add_realm_default_custom_profile_field,
)
from zerver.actions.message_send import build_message_send_dict, do_send_messages
from zerver.actions.realm_emoji import check_add_realm_emoji
from zerver.actions.realm_linkifiers import do_add_linkifier
from zerver.actions.scheduled_messages import check_schedule_message
from zerver.actions.streams import bulk_add_subscriptions
from zerver.actions.user_groups import create_user_group_in_database
from zerver.actions.user_settings import do_change_user_setting
from zerver.actions.users import do_change_user_role
from zerver.lib.bulk_create import bulk_create_streams
from zerver.lib.create_user import create_user, create_user_profile
from zerver.lib.generate_test_data import create_test_data, generate_topics
from zerver.lib.initial_password import initial_password
from zerver.lib.onboarding import create_if_missing_realm_internal_bots
from zerver.lib.push_notifications import logger as push_notifications_logger
from zerver.lib.server_initialization import create_internal_realm, create_users
from zerver.lib.storage import static_path
from zerver.lib.stream_color import STREAM_ASSIGNMENT_COLORS
from zerver.lib.types import ProfileFieldData
from zerver.lib.users import add_service
from zerver.lib.utils import generate_api_key
from zerver.models import (
    AlertWord,
    Client,
    CustomProfileField,
    DefaultStream,
    Draft,
    Huddle,
    Message,
    Reaction,
    Realm,
    RealmAuditLog,
    RealmDomain,
    RealmUserDefault,
    Recipient,
    Service,
    Stream,
    Subscription,
    UserGroup,
    UserMessage,
    UserPresence,
    UserProfile,
    flush_alert_word,
    get_client,
    get_or_create_huddle,
    get_realm,
    get_stream,
    get_user,
    get_user_by_delivery_email,
    get_user_profile_by_id,
)


class Command(BaseCommand):
    help = "Populate database with different types of realms that can exist."

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        # Create a realm for each plan type
        for plan_type, plan_name in Realm.ALL_PLAN_TYPES:
            customer_profiles = [
                {
                    "unique_id": f"{plan_name}-sponsorship-pending",
                    "sponsorship_pending": True,
                },
                {
                    "unique_id": f"{plan_name}-annual-standard",
                    "sponsorship_pending": False,
                    "billing_schedule": CustomerPlan.ANNUAL,
                    "tier": CustomerPlan.STANDARD,
                    "automanage_licenses": False,
                },
                {
                    "unique_id": f"{plan_name}-annual-plus",
                    "sponsorship_pending": False,
                    "billing_schedule": CustomerPlan.ANNUAL,
                    "tier": CustomerPlan.PLUS,
                    "automanage_licenses": False,
                },
                {
                    "unique_id": f"{plan_name}-annual-enterprise",
                    "sponsorship_pending": False,
                    "billing_schedule": CustomerPlan.ANNUAL,
                    "tier": CustomerPlan.ENTERPRISE,
                    "automanage_licenses": False,
                },
                {
                    "unique_id": f"{plan_name}-monthly-standard",
                    "sponsorship_pending": False,
                    "billing_schedule": CustomerPlan.MONTHLY,
                    "tier": CustomerPlan.STANDARD,
                    "automanage_licenses": False,
                },
                {
                    "unique_id": f"{plan_name}-monthly-plus",
                    "sponsorship_pending": False,
                    "billing_schedule": CustomerPlan.MONTHLY,
                    "tier": CustomerPlan.PLUS,
                    "automanage_licenses": False,
                },
                {
                    "unique_id": f"{plan_name}-monthly-enterprise",
                    "sponsorship_pending": False,
                    "billing_schedule": CustomerPlan.ANNUAL,
                    "tier": CustomerPlan.ENTERPRISE,
                    "automanage_licenses": False,
                },
                {
                    "unique_id": f"{plan_name}-automanage-licenses",
                    "sponsorship_pending": False,
                    "billing_schedule": CustomerPlan.MONTHLY,
                    "tier": CustomerPlan.STANDARD,
                    "automanage_licenses": True,
                },
            ]

            # create a realm for each customer profile
            for i, customer_profile in enumerate(customer_profiles):
                unique_id = customer_profile["unique_id"]
                # Delete existing realm with this name
                try:
                    get_realm(unique_id).delete()
                except Realm.DoesNotExist:
                    pass

                realm = do_create_realm(
                    string_id=unique_id,
                    name=unique_id,
                    description=unique_id,
                    plan_type=plan_type,
                )

                # Create a user with billing access
                full_name = f"{plan_name}-admin"
                email = f"{full_name}@zulip.com"
                user = create_user(
                    email,
                    full_name,
                    realm,
                    full_name,
                    role=UserProfile.ROLE_REALM_OWNER,
                )

                administrators_user_group = UserGroup.objects.get(
                    name=UserGroup.ADMINISTRATORS_GROUP_NAME, realm=realm, is_system_group=True
                )
                stream = Stream.objects.create(
                    name="all",
                    realm=realm,
                    can_remove_subscribers_group=administrators_user_group,
                )
                recipient = Recipient.objects.create(type_id=stream.id, type=Recipient.STREAM)
                stream.recipient = recipient
                stream.save(update_fields=["recipient"])

                Subscription.objects.create(
                    recipient=recipient,
                    user_profile=user,
                    is_user_active=user.is_active,
                    color=STREAM_ASSIGNMENT_COLORS[0],
                )

                if customer_profile["sponsorship_pending"]:
                    customer = Customer.objects.create(
                        realm=realm,
                        sponsorship_pending=customer_profile["sponsorship_pending"],
                    )
                    continue

                customer = update_or_create_stripe_customer(user)
            
                customer_plan = CustomerPlan.objects.create(
                    customer=customer,
                    billing_cycle_anchor=timezone_now(),
                    billing_schedule=customer_profile["billing_schedule"],
                    tier=customer_profile["tier"],
                    price_per_license = 3,
                    automanage_licenses = customer_profile["automanage_licenses"],
                )

                LicenseLedger.objects.create(
                    licenses=10,
                    licenses_at_next_renewal=10,
                    event_time=timezone_now(),
                    is_renewal=True,
                    plan=customer_plan,
                )
