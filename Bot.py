#!/usr/bin/env python3
"""
Advanced Telegram Bot with Content Management System & Force Join
Secure, Scalable, and Production-Ready
Author: Senior Telegram Bot Developer

Upgraded with:
- Refer & Earn
- Multi‑Payment Withdrawal System
- Enterprise Admin Panel for Withdrawals
- Batch Upload Mode
- MONGODB ATLAS BACKEND (No more data loss!)
"""

import os
import logging
import asyncio
import uuid
import re
import html
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Dict, List, Tuple, Optional, Union
from enum import Enum

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    Chat,
    Message,
    ChatMember,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
    ConversationHandler
)
from telegram.constants import ParseMode, ChatType, ChatMemberStatus
from telegram.error import BadRequest, Forbidden, TelegramError

# ========================
# MongoDB ATLAS Setup
# ========================
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError, PyMongoError

# ⚠️ IMPORTANT: Use environment variable in production!
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://justneedbro_db_user:FMZLmB5MJ3xFsnV3@cluster0.yoxfhc4.mongodb.net/?appName=Cluster0")
client = MongoClient(MONGO_URI)
db = client["telegram_bot"]          # database name

# Collections
users_col = db["users"]
contents_col = db["contents"]
referrals_col = db["referrals"]
content_views_col = db["content_views"]
earnings_col = db["earnings"]
user_payments_col = db["user_payments"]
withdrawals_col = db["withdrawals"]
settings_col = db["settings"]

# Create indexes for performance
users_col.create_index("user_id", unique=True)
users_col.create_index("referred_by")
users_col.create_index("is_banned")

contents_col.create_index("content_id", unique=True)
contents_col.create_index("uploader_user_id")
contents_col.create_index("content_type")
contents_col.create_index("protection_mode")

referrals_col.create_index("referred_user_id", unique=True)
referrals_col.create_index("referrer_id")

content_views_col.create_index([("content_id", ASCENDING), ("viewer_user_id", ASCENDING)], unique=True)

earnings_col.create_index("user_id")
earnings_col.create_index("source_type")

user_payments_col.create_index("user_id", unique=True)

withdrawals_col.create_index("user_id")
withdrawals_col.create_index("status")
withdrawals_col.create_index("requested_at")

settings_col.create_index("setting_name", unique=True)

# ========================
# CONFIGURATION
# ========================
BOT_TOKEN = "8344340012:AAEptGjW0Rsv4DMq0WvMQVgqcbta4z4N5Vw"  # ⚠️ CHANGE THIS!
ADMIN_IDS = [
    8771679213,
    8488305795,
    8577263306,
    8370998743
]  # ⚠️ CHANGE THIS!
BACKUP_CHANNEL_ID = -1003866297712  # ⚠️ CHANGE THIS! (Private admin-only channel)

FORCE_JOIN_CHANNELS = [
    # {"id": -1002872721854, "link": "https://t.me/workunlimited", "title": "Test Channel 🎫"},
    # {"id": -1003754168905, "link": "https://t.me/KaizenXhubupdate", "title": "Bot Updates "},
]

DATABASE_NAME = "content_bot.db"  # kept for compatibility, but not used
AUTO_DELETE_SECONDS = 3600  # Default: 1 hour auto-delete
TIMEZONE = timezone.utc

# Conversation states for payment setup
(SET_PAYMENT_METHOD, SET_PAYMENT_DETAILS) = range(2)

# ========================
# ENUMS & CONSTANTS
# ========================
class ContentType(Enum):
    FILE = "file"
    VIDEO = "video"
    AUDIO = "audio"
    PHOTO = "photo"
    TEXT = "text"
    BATCH = "batch"

class MaintenanceMode(Enum):
    ON = "ON"
    OFF = "OFF"

class ProtectionMode(Enum):
    PROTECTED = "protected"
    UNPROTECTED = "unprotected"

# ========================
# LOGGING SETUP
# ========================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========================
# HTML ESCAPE HELPER
# ========================
def escape_html(text: str) -> str:
    if text is None:
        return ""
    return html.escape(str(text))

def escape_markdown(text: str) -> str:
    if not text:
        return ""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{c}' if c in escape_chars else c for c in str(text))

# ========================
# DATABASE MANAGER (MONGODB VERSION)
# ========================
class DatabaseManager:
    """MongoDB Atlas database manager for all operations."""

    def __init__(self):
        self.init_database()

    def init_database(self):
        """Ensure collections and default settings exist."""
        try:
            # Insert default settings if they don't exist
            settings_to_init = [
                ('maintenance_mode', 'OFF'),
                ('auto_delete_time', '3600'),
                ('referral_reward', '0.01'),
                ('view_reward', '0.01'),
                ('min_withdrawal', '1.00')
            ]
            for name, value in settings_to_init:
                settings_col.update_one(
                    {"setting_name": name},
                    {"$setOnInsert": {"setting_value": value}},
                    upsert=True
                )
            logger.info("MongoDB database initialized/upgraded successfully")
        except Exception as e:
            logger.error(f"Database initialization error: {e}")

    # ---------------------- User methods ----------------------
    def add_user(self, user_id: int, username: str = None):
        try:
            users_col.update_one(
                {"user_id": user_id},
                {"$setOnInsert": {
                    "user_id": user_id,
                    "username": username,
                    "join_date": datetime.now(TIMEZONE),
                    "has_joined_all_channels": 0,
                    "is_banned": 0,
                    "ban_reason": None,
                    "banned_by": None,
                    "ban_date": None,
                    "referred_by": None
                }},
                upsert=True
            )
            # Update username if changed
            if username:
                users_col.update_one(
                    {"user_id": user_id},
                    {"$set": {"username": username}}
                )
        except Exception as e:
            logger.error(f"Error adding user: {e}")

    def update_user_channel_status(self, user_id: int, has_joined: bool):
        try:
            users_col.update_one(
                {"user_id": user_id},
                {"$set": {"has_joined_all_channels": 1 if has_joined else 0}}
            )
        except Exception as e:
            logger.error(f"Error updating user channel status: {e}")

    def get_user(self, user_id: int) -> Optional[Dict]:
        try:
            doc = users_col.find_one({"user_id": user_id})
            return doc if doc else None
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return None

    def is_user_banned(self, user_id: int) -> bool:
        try:
            user = users_col.find_one({"user_id": user_id}, {"is_banned": 1})
            return bool(user and user.get("is_banned", 0))
        except Exception as e:
            logger.error(f"Error checking if user is banned: {e}")
            return False

    def ban_user(self, user_id: int, banned_by: int, reason: str = "No reason provided"):
        try:
            result = users_col.update_one(
                {"user_id": user_id},
                {"$set": {
                    "is_banned": 1,
                    "ban_reason": reason,
                    "banned_by": banned_by,
                    "ban_date": datetime.now(TIMEZONE)
                }},
                upsert=True
            )
            logger.info(f"User {user_id} banned by {banned_by}. Reason: {reason}")
            return True
        except Exception as e:
            logger.error(f"Error banning user: {e}")
            return False

    def unban_user(self, user_id: int):
        try:
            users_col.update_one(
                {"user_id": user_id},
                {"$set": {
                    "is_banned": 0,
                    "ban_reason": None,
                    "banned_by": None,
                    "ban_date": None
                }}
            )
            logger.info(f"User {user_id} unbanned")
            return True
        except Exception as e:
            logger.error(f"Error unbanning user: {e}")
            return False

    def get_banned_users(self) -> List[Dict]:
        try:
            cursor = users_col.find({"is_banned": 1}).sort("ban_date", DESCENDING)
            return list(cursor)
        except Exception as e:
            logger.error(f"Error getting banned users: {e}")
            return []

    # ---------------------- Content methods ----------------------
    def add_content(self, content_data: Dict) -> str:
        try:
            content_id = content_data.get('content_id')
            if not content_id:
                content_id = str(uuid.uuid4())[:12]
                content_data['content_id'] = content_id

            content_data['upload_timestamp'] = content_data.get(
                'upload_timestamp',
                datetime.now(TIMEZONE)
            )
            contents_col.insert_one(content_data)
            logger.info(f"Content added with ID: {content_id}")
            return content_id
        except Exception as e:
            logger.error(f"Error adding content: {e}")
            raise

    def get_content(self, content_id: str) -> Optional[Dict]:
        try:
            doc = contents_col.find_one({"content_id": content_id})
            return doc if doc else None
        except Exception as e:
            logger.error(f"Error getting content: {e}")
            return None

    def delete_content(self, content_id: str, user_id: int) -> bool:
        try:
            content = contents_col.find_one({"content_id": content_id})
            if not content:
                return False
            uploader_id = content.get("uploader_user_id")
            if user_id != uploader_id and user_id not in ADMIN_IDS:
                return False
            result = contents_col.delete_one({"content_id": content_id})
            if result.deleted_count:
                logger.info(f"Content {content_id} deleted by user {user_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting content: {e}")
            return False

    def update_backup_message_id(self, content_id: str, message_id: int):
        try:
            contents_col.update_one(
                {"content_id": content_id},
                {"$set": {"backup_message_id": message_id}}
            )
        except Exception as e:
            logger.error(f"Error updating backup message ID: {e}")

    def get_user_contents(self, user_id: int) -> List[Dict]:
        try:
            cursor = contents_col.find({"uploader_user_id": user_id}).sort("upload_timestamp", DESCENDING)
            return list(cursor)
        except Exception as e:
            logger.error(f"Error getting user contents: {e}")
            return []

    def get_content_stats_by_user(self, user_id: int) -> Dict:
        try:
            pipeline = [
                {"$match": {"uploader_user_id": user_id}},
                {"$group": {"_id": "$content_type", "count": {"$sum": 1}}}
            ]
            results = list(contents_col.aggregate(pipeline))
            return {r["_id"]: r["count"] for r in results}
        except Exception as e:
            logger.error(f"Error getting user stats: {e}")
            return {}

    def get_global_stats(self) -> Dict:
        try:
            stats = {}

            stats['total_users'] = users_col.count_documents({})
            stats['verified_users'] = users_col.count_documents({"has_joined_all_channels": 1})
            stats['banned_users'] = users_col.count_documents({"is_banned": 1})
            stats['total_contents'] = contents_col.count_documents({})

            # contents by type
            pipeline_type = [
                {"$group": {"_id": "$content_type", "count": {"$sum": 1}}}
            ]
            stats['contents_by_type'] = {r["_id"]: r["count"] for r in contents_col.aggregate(pipeline_type)}

            # contents by protection
            pipeline_prot = [
                {"$group": {"_id": "$protection_mode", "count": {"$sum": 1}}}
            ]
            stats['contents_by_protection'] = {r["_id"]: r["count"] for r in contents_col.aggregate(pipeline_prot)}

            # earnings stats
            total_earnings_pipeline = [{"$group": {"_id": None, "total": {"$sum": "$amount"}}}]
            total_earnings = list(earnings_col.aggregate(total_earnings_pipeline))
            stats['total_earnings'] = total_earnings[0]["total"] if total_earnings else 0.0

            stats['total_referrals'] = referrals_col.count_documents({})
            stats['total_views'] = content_views_col.count_documents({})
            stats['total_withdrawals'] = withdrawals_col.count_documents({})
            stats['pending_withdrawals'] = withdrawals_col.count_documents({"status": "pending"})

            return stats
        except Exception as e:
            logger.error(f"Error getting global stats: {e}")
            return {}

    # ---------------------- Settings methods ----------------------
    def get_maintenance_mode(self) -> str:
        try:
            doc = settings_col.find_one({"setting_name": "maintenance_mode"})
            return doc["setting_value"] if doc else "OFF"
        except Exception as e:
            logger.error(f"Error getting maintenance mode: {e}")
            return "OFF"

    def set_maintenance_mode(self, mode: str):
        try:
            settings_col.update_one(
                {"setting_name": "maintenance_mode"},
                {"$set": {"setting_value": mode}},
                upsert=True
            )
        except Exception as e:
            logger.error(f"Error setting maintenance mode: {e}")

    def get_auto_delete_time(self) -> int:
        try:
            doc = settings_col.find_one({"setting_name": "auto_delete_time"})
            return int(doc["setting_value"]) if doc else AUTO_DELETE_SECONDS
        except Exception as e:
            logger.error(f"Error getting auto-delete time: {e}")
            return AUTO_DELETE_SECONDS

    def set_auto_delete_time(self, seconds: int):
        try:
            settings_col.update_one(
                {"setting_name": "auto_delete_time"},
                {"$set": {"setting_value": str(seconds)}},
                upsert=True
            )
            global AUTO_DELETE_SECONDS
            AUTO_DELETE_SECONDS = seconds
            logger.info(f"Auto-delete time set to {seconds} seconds")
        except Exception as e:
            logger.error(f"Error setting auto-delete time: {e}")

    def get_setting(self, name: str, default: str = None) -> str:
        try:
            doc = settings_col.find_one({"setting_name": name})
            return doc["setting_value"] if doc else default
        except Exception as e:
            logger.error(f"Error getting setting {name}: {e}")
            return default

    def set_setting(self, name: str, value: str):
        try:
            settings_col.update_one(
                {"setting_name": name},
                {"$set": {"setting_value": value}},
                upsert=True
            )
            logger.info(f"Setting {name} set to {value}")
        except Exception as e:
            logger.error(f"Error setting {name}: {e}")

    # ---------------------- Referral & Earnings ----------------------
    def process_referral(self, referrer_id: int, referred_user_id: int) -> bool:
        if referrer_id == referred_user_id:
            return False

        try:
            # Check if already referred
            existing = referrals_col.find_one({"referred_user_id": referred_user_id})
            if existing:
                return False

            # Ensure referrer exists in users
            self.add_user(referrer_id, None)

            reward = float(self.get_setting('referral_reward', '0.01'))

            # Insert referral
            referrals_col.insert_one({
                "referrer_id": referrer_id,
                "referred_user_id": referred_user_id,
                "reward_amount": reward,
                "created_at": datetime.now(TIMEZONE)
            })

            # Add earning for referrer
            earnings_col.insert_one({
                "user_id": referrer_id,
                "source_type": "referral",
                "source_id": str(referred_user_id),
                "amount": reward,
                "created_at": datetime.now(TIMEZONE)
            })

            # Update referred_by in user document
            users_col.update_one(
                {"user_id": referred_user_id},
                {"$set": {"referred_by": referrer_id}}
            )

            logger.info(f"Referral reward: {reward} to {referrer_id} for {referred_user_id}")
            return True
        except Exception as e:
            logger.error(f"Error processing referral: {e}")
            return False

    def record_view(self, content_id: str, viewer_user_id: int) -> Optional[float]:
        try:
            content = contents_col.find_one({"content_id": content_id})
            if not content:
                return None
            uploader_id = content.get("uploader_user_id")
            if uploader_id == viewer_user_id:
                return None

            # Check if already viewed
            existing = content_views_col.find_one({
                "content_id": content_id,
                "viewer_user_id": viewer_user_id
            })
            if existing:
                return None

            reward = float(self.get_setting('view_reward', '0.01'))

            # Insert view record
            content_views_col.insert_one({
                "content_id": content_id,
                "viewer_user_id": viewer_user_id,
                "viewed_at": datetime.now(TIMEZONE)
            })

            # Add earning for uploader
            earnings_col.insert_one({
                "user_id": uploader_id,
                "source_type": "view",
                "source_id": content_id,
                "amount": reward,
                "created_at": datetime.now(TIMEZONE)
            })

            logger.info(f"View reward: {reward} to {uploader_id} for content {content_id}")
            return reward
        except Exception as e:
            logger.error(f"Error recording view: {e}")
            return None

    def get_user_balance(self, user_id: int) -> float:
        try:
            # total earnings
            pipeline_earn = [
                {"$match": {"user_id": user_id}},
                {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
            ]
            earn_result = list(earnings_col.aggregate(pipeline_earn))
            total_earned = earn_result[0]["total"] if earn_result else 0.0

            # total completed withdrawals
            pipeline_withdrawn = [
                {"$match": {"user_id": user_id, "status": "completed"}},
                {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
            ]
            withdrawn_result = list(withdrawals_col.aggregate(pipeline_withdrawn))
            total_withdrawn = withdrawn_result[0]["total"] if withdrawn_result else 0.0

            # total pending withdrawals
            pipeline_pending = [
                {"$match": {"user_id": user_id, "status": "pending"}},
                {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
            ]
            pending_result = list(withdrawals_col.aggregate(pipeline_pending))
            total_pending = pending_result[0]["total"] if pending_result else 0.0

            return total_earned - total_withdrawn - total_pending
        except Exception as e:
            logger.error(f"Error getting user balance: {e}")
            return 0.0

    def get_user_earnings_summary(self, user_id: int) -> Dict:
        try:
            # referral earnings
            pipeline_ref = [
                {"$match": {"user_id": user_id, "source_type": "referral"}},
                {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
            ]
            ref_result = list(earnings_col.aggregate(pipeline_ref))
            referral_earnings = ref_result[0]["total"] if ref_result else 0.0

            # view earnings
            pipeline_view = [
                {"$match": {"user_id": user_id, "source_type": "view"}},
                {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
            ]
            view_result = list(earnings_col.aggregate(pipeline_view))
            view_earnings = view_result[0]["total"] if view_result else 0.0

            total_earnings = referral_earnings + view_earnings

            total_referrals = referrals_col.count_documents({"referrer_id": user_id})

            # total views (as uploader)
            pipeline_views = [
                {"$match": {"uploader_user_id": user_id}},
                {"$lookup": {
                    "from": "content_views",
                    "localField": "content_id",
                    "foreignField": "content_id",
                    "as": "views"
                }},
                {"$unwind": "$views"},
                {"$count": "total"}
            ]
            views_result = list(contents_col.aggregate(pipeline_views))
            total_views = views_result[0]["total"] if views_result else 0

            # total withdrawn
            pipeline_withdrawn = [
                {"$match": {"user_id": user_id, "status": "completed"}},
                {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
            ]
            withdrawn_result = list(withdrawals_col.aggregate(pipeline_withdrawn))
            total_withdrawn = withdrawn_result[0]["total"] if withdrawn_result else 0.0

            balance = self.get_user_balance(user_id)

            return {
                'referral_earnings': referral_earnings,
                'view_earnings': view_earnings,
                'total_earnings': total_earnings,
                'total_referrals': total_referrals,
                'total_views': total_views,
                'total_withdrawn': total_withdrawn,
                'balance': balance
            }
        except Exception as e:
            logger.error(f"Error getting earnings summary: {e}")
            return {}

    # ---------------------- Payment & Withdrawal ----------------------
    def set_user_payment(self, user_id: int, method: str, details: str) -> bool:
        try:
            user_payments_col.update_one(
                {"user_id": user_id},
                {"$set": {
                    "payment_method": method,
                    "payment_details": details,
                    "updated_at": datetime.now(TIMEZONE)
                }},
                upsert=True
            )
            logger.info(f"Payment method set for user {user_id}: {method}")
            return True
        except Exception as e:
            logger.error(f"Error setting payment: {e}")
            return False

    def get_user_payment(self, user_id: int) -> Optional[Dict]:
        try:
            doc = user_payments_col.find_one({"user_id": user_id})
            return doc if doc else None
        except Exception as e:
            logger.error(f"Error getting payment: {e}")
            return None

    def create_withdrawal(self, user_id: int, amount: float, method: str, details: str) -> Optional[int]:
        try:
            # Check balance (atomic read)
            balance = self.get_user_balance(user_id)
            if balance < amount:
                return None

            # Insert withdrawal
            result = withdrawals_col.insert_one({
                "user_id": user_id,
                "amount": amount,
                "payment_method": method,
                "payment_details": details,
                "status": "pending",
                "requested_at": datetime.now(TIMEZONE),
                "processed_at": None,
                "processed_by": None
            })
            withdrawal_id = result.inserted_id
            logger.info(f"Withdrawal request #{withdrawal_id} created for user {user_id}, amount {amount}")
            return withdrawal_id
        except Exception as e:
            logger.error(f"Error creating withdrawal: {e}")
            return None

    def get_pending_withdrawals(self) -> List[Dict]:
        try:
            pipeline = [
                {"$match": {"status": "pending"}},
                {"$lookup": {
                    "from": "users",
                    "localField": "user_id",
                    "foreignField": "user_id",
                    "as": "user_info"
                }},
                {"$unwind": {"path": "$user_info", "preserveNullAndEmptyArrays": True}},
                {"$sort": {"requested_at": ASCENDING}}
            ]
            results = list(withdrawals_col.aggregate(pipeline))
            # Flatten user info
            for r in results:
                if r.get("user_info"):
                    r["username"] = r["user_info"].get("username")
                else:
                    r["username"] = None
            return results
        except Exception as e:
            logger.error(f"Error getting pending withdrawals: {e}")
            return []

    def process_withdrawal(self, withdrawal_id, admin_id: int, status: str) -> bool:
        try:
            from bson.objectid import ObjectId
            obj_id = ObjectId(withdrawal_id) if isinstance(withdrawal_id, str) else withdrawal_id

            result = withdrawals_col.update_one(
                {"_id": obj_id, "status": "pending"},
                {"$set": {
                    "status": status,
                    "processed_at": datetime.now(TIMEZONE),
                    "processed_by": admin_id
                }}
            )
            if result.modified_count:
                logger.info(f"Withdrawal #{withdrawal_id} {status} by admin {admin_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error processing withdrawal: {e}")
            return False

# Initialize database manager
db = DatabaseManager()

# ========================
# FORCE JOIN SYSTEM (unchanged)
# ========================
async def check_channel_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not FORCE_JOIN_CHANNELS:
        return True
    for channel in FORCE_JOIN_CHANNELS:
        try:
            member = await context.bot.get_chat_member(
                chat_id=channel["id"],
                user_id=user_id
            )
            if member.status in [
                ChatMemberStatus.LEFT,
                ChatMemberStatus.BANNED,
                ChatMemberStatus.RESTRICTED
            ]:
                return False
        except (BadRequest, Forbidden) as e:
            logger.error(f"Error checking membership for channel {channel['id']}: {e}")
            return False
    return True

def create_join_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    for channel in FORCE_JOIN_CHANNELS:
        keyboard.append([
            InlineKeyboardButton(
                f"👉 Join {channel['title']}",
                url=channel["link"]
            )
        ])
    keyboard.append([
        InlineKeyboardButton("✅ I've Joined - Check Now", callback_data="recheck_membership")
    ])
    return InlineKeyboardMarkup(keyboard)

async def require_channel_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if user.id in ADMIN_IDS:
        return False
    has_joined = await check_channel_membership(user.id, context)
    if not has_joined:
        db.update_user_channel_status(user.id, False)
        join_message = (
            f"👋 Welcome {user.first_name}!\n\n"
            f"🔒 **Access Restricted**\n\n"
            f"To use this bot, you must join the required channels.\n\n"
            f"👇 Click the buttons below to join\n"
            f"✅ Then press **I've Joined – Check Now**\n\n"
            f"⚠️ You must stay in the channels to keep access."
        )
        if update.callback_query:
            await update.callback_query.edit_message_text(
                join_message,
                reply_markup=create_join_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
        elif update.message:
            await update.message.reply_text(
                join_message,
                reply_markup=create_join_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
        return True
    db.update_user_channel_status(user.id, True)
    return False

# ========================
# SECURITY & ADMIN GUARD
# ========================
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if user.id not in ADMIN_IDS:
            if update.message:
                await update.message.delete()
            elif update.callback_query:
                await update.callback_query.answer()
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

async def check_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if user.id in ADMIN_IDS:
        return False
    if db.get_maintenance_mode() == 'ON':
        maintenance_msg = (
            "🔧 **Maintenance Mode**\n\n"
            "The bot is currently undergoing maintenance.\n"
            "Please try again later.\n\n"
            "Thank you for your patience! ❤️"
        )
        if update.message:
            await update.message.reply_text(maintenance_msg, parse_mode=ParseMode.MARKDOWN)
        elif update.callback_query:
            await update.callback_query.answer(maintenance_msg, show_alert=True)
        return True
    return False

async def check_ban_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if user.id in ADMIN_IDS:
        return False
    if db.is_user_banned(user.id):
        user_data = db.get_user(user.id)
        ban_reason = user_data.get('ban_reason', 'No reason provided')
        ban_date = user_data.get('ban_date', 'Unknown date')
        if isinstance(ban_date, datetime):
            ban_date_display = ban_date.strftime('%Y-%m-%d %H:%M:%S')
        else:
            ban_date_display = str(ban_date)
        ban_msg = (
            "🚫 **Account Banned**\n\n"
            "Your account has been restricted from uploading content.\n\n"
            f"**Reason:** {ban_reason}\n"
            f"**Date:** {ban_date_display}\n\n"
            "If you believe this is a mistake, contact the administrator."
        )
        if update.message:
            await update.message.reply_text(ban_msg, parse_mode=ParseMode.MARKDOWN)
        elif update.callback_query:
            await update.callback_query.answer(ban_msg, show_alert=True)
        return True
    return False

# ========================
# COMMAND VISIBILITY SYSTEM
# ========================
async def set_command_scopes(application: Application):
    user_commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("get", "Get content by secret ID"),
        BotCommand("profile", "Your profile & earnings"),
        BotCommand("delete", "Delete your content"),
        BotCommand("withdraw", "Withdraw your earnings"),
        BotCommand("setpayment", "Set your payment method"),
        BotCommand("batch", "Start batch upload mode"),
        BotCommand("done", "Finish batch upload"),
        BotCommand("stats", "Bot Status (admin only)"),
        BotCommand("help", "This help message"),
    ]
    admin_commands = user_commands + [
        BotCommand("upload", "Upload content"),
        BotCommand("adms", "Broadcast"),
        BotCommand("maintenance", "Toggle maintenance mode"),
        BotCommand("settime", "Set auto-delete time"),
        BotCommand("ban", "Ban a user"),
        BotCommand("unban", "Unban a user"),
        BotCommand("banned", "List banned users"),
        BotCommand("withdrawals", "Manage withdrawals"),
        BotCommand("setreward", "Set referral/view reward"),
        BotCommand("setminwithdraw", "Set minimum withdrawal"),
        BotCommand("find", "Inspect any user (admin)"),
        BotCommand("setmod", "Set upload mode (private/public)"),
    ]
    try:
        await application.bot.set_my_commands(
            commands=user_commands,
            scope=BotCommandScopeDefault()
        )
        for admin_id in ADMIN_IDS:
            try:
                await application.bot.set_my_commands(
                    commands=admin_commands,
                    scope=BotCommandScopeChat(chat_id=admin_id)
                )
                logger.info(f"Admin commands set for user: {admin_id}")
            except Exception as e:
                logger.error(f"Failed to set admin commands for {admin_id}: {e}")
        logger.info("Command scopes set successfully")
    except Exception as e:
        logger.error(f"Error setting command scopes: {e}")

# ========================
# BATCH UPLOAD COMMANDS
# ========================
async def batch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_maintenance(update, context):
        return
    if await check_ban_status(update, context):
        return
    user = update.effective_user
    if user.id not in ADMIN_IDS and await require_channel_join(update, context):
        return

    # FIX: Check private upload mode – block batch for non-admins
    if UPLOAD_MODE == "private" and user.id not in ADMIN_IDS:
        await update.message.reply_text(
            "❌ Batch uploads are currently restricted to admins only."
        )
        return

    if context.user_data.get('batch_mode'):
        await update.message.reply_text(
            "⚠️ You are already in batch upload mode.\n"
            "Send files or use /done to finish."
        )
        return

    context.user_data['batch_mode'] = True
    context.user_data['batch_files'] = []
    await update.message.reply_text(
        "📦 **Batch Upload Mode Started**\n\n"
        "Send multiple files or content now.\n"
        "When finished uploading, send /done to complete the batch.",
        parse_mode=ParseMode.MARKDOWN
    )

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_maintenance(update, context):
        return
    if await check_ban_status(update, context):
        return
    user = update.effective_user
    if user.id not in ADMIN_IDS and await require_channel_join(update, context):
        return

    # FIX: Check private upload mode – block batch finishing for non-admins
    if UPLOAD_MODE == "private" and user.id not in ADMIN_IDS:
        # Clean up any leftover batch state
        context.user_data.pop('batch_mode', None)
        context.user_data.pop('batch_files', None)
        await update.message.reply_text(
            "❌ Batch uploads are currently restricted to admins only."
        )
        return

    if not context.user_data.get('batch_mode'):
        await update.message.reply_text(
            "❌ You are not in batch upload mode.\n"
            "Send /batch first."
        )
        return

    batch_files = context.user_data.get('batch_files', [])
    if not batch_files:
        await update.message.reply_text(
            "❌ No files uploaded in batch.\n"
            "Send files first."
        )
        return

    del context.user_data['batch_mode']
    context.user_data['pending_batch'] = batch_files

    keyboard = [
        [
            InlineKeyboardButton("🔒 Protected", callback_data="protection_protected"),
            InlineKeyboardButton("🔓 Unprotected", callback_data="protection_unprotected")
        ],
        [InlineKeyboardButton("❌ Cancel Upload", callback_data="cancel_upload")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔒 **Protection Mode**\n\n"
        "How would you like to protect this batch?\n\n"
        "**🔒 Protected** - Users cannot save/forward\n"
        "**🔓 Unprotected** - No restrictions\n\n"
        "Please choose an option below:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# ========================
# UPLOAD HANDLER (modified to intercept batch files)
# ========================
UPLOAD_MODE = "public"

async def handle_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_maintenance(update, context):
        return
    if await check_ban_status(update, context):
        return
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        if await require_channel_join(update, context):
            return

    # FIX: Private mode check moved to top – blocks ALL upload attempts (including batch additions)
    if UPLOAD_MODE == "private" and user.id not in ADMIN_IDS:
        # Clean up any leftover batch state to avoid stuck sessions
        if context.user_data.get('batch_mode'):
            context.user_data['batch_mode'] = False
            context.user_data.pop('batch_files', None)
        await update.message.reply_text("❌ Uploads are currently restricted to admins only.")
        return

    if context.user_data.get('batch_mode'):
        message = update.message
        file_info = None
        if message.photo:
            file_info = {
                'type': 'photo',
                'file_id': message.photo[-1].file_id,
                'caption': message.caption or ""
            }
        elif message.video:
            file_info = {
                'type': 'video',
                'file_id': message.video.file_id,
                'caption': message.caption or ""
            }
        elif message.audio:
            file_info = {
                'type': 'audio',
                'file_id': message.audio.file_id,
                'caption': message.caption or ""
            }
        elif message.document:
            file_info = {
                'type': 'document',
                'file_id': message.document.file_id,
                'caption': message.caption or ""
            }
        elif message.text:
            file_info = {
                'type': 'text',
                'text': message.text,
                'caption': None
            }
        if file_info:
            context.user_data.setdefault('batch_files', []).append(file_info)
        else:
            await message.reply_text("Unsupported content type. Please send a file, video, audio, photo, or text.")
        return

    if UPLOAD_MODE == "private" and user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Only admins can upload content right now.")
        return

    message = update.message
    if not (message.photo or message.video or message.audio or message.document or message.text):
        await message.reply_text(
            "📤 **How to upload content:**\n\n"
            "Simply send me:\n"
            "• Any file (document)\n"
            "• Video\n"
            "• Audio\n"
            "• Photo\n"
            "• Text message\n\n"
            "I'll generate a unique Content ID that you can share!",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    progress_msg = await show_upload_progress(context, update.effective_chat.id)
    context.user_data['upload_progress_msg'] = progress_msg
    context.user_data['upload_in_progress'] = True
    asyncio.create_task(upload_progress_task(context, progress_msg))

    try:
        db.add_user(user.id, user.username)

        content_data = {
            'uploader_user_id': user.id,
            'uploader_username': user.username,
            'upload_timestamp': datetime.now(TIMEZONE),
            'auto_delete_time': db.get_auto_delete_time(),
        }

        if message.text:
            content_data['content_type'] = ContentType.TEXT.value
            content_data['text_data'] = message.text
            content_data['telegram_file_id'] = None
        elif message.photo:
            content_data['content_type'] = ContentType.PHOTO.value
            content_data['telegram_file_id'] = message.photo[-1].file_id
            content_data['text_data'] = message.caption or ""
        elif message.video:
            content_data['content_type'] = ContentType.VIDEO.value
            content_data['telegram_file_id'] = message.video.file_id
            content_data['text_data'] = message.caption or ""
        elif message.audio:
            content_data['content_type'] = ContentType.AUDIO.value
            content_data['telegram_file_id'] = message.audio.file_id
            content_data['text_data'] = message.caption or ""
        elif message.document:
            content_data['content_type'] = ContentType.FILE.value
            content_data['telegram_file_id'] = message.document.file_id
            content_data['text_data'] = message.caption or ""

        context.user_data['pending_upload'] = content_data

        keyboard = [
            [
                InlineKeyboardButton("🔒 Protected", callback_data="protection_protected"),
                InlineKeyboardButton("🔓 Unprotected", callback_data="protection_unprotected")
            ],
            [InlineKeyboardButton("❌ Cancel Upload", callback_data="cancel_upload")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await message.reply_text(
            "🔒 **Protection Mode**\n\n"
            "How would you like to protect this content?\n\n"
            "**🔒 Protected** - Users cannot save/forward\n"
            "**🔓 Unprotected** - No restrictions\n\n"
            "Please choose an option below:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Error handling upload: {e}")
        await message.reply_text(
            "❌ An error occurred while processing your upload. Please try again.",
            parse_mode=ParseMode.MARKDOWN
        )

# ========================
# PROCESS PENDING REFERRAL
# ========================
async def process_pending_referral(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    pending_referrer = context.user_data.get("pending_referrer")
    if pending_referrer:
        user_data = db.get_user(user_id)
        if user_data and not user_data.get("referred_by"):
            db.process_referral(pending_referrer, user_id)
        context.user_data.pop("pending_referrer", None)

# ========================
# COMPLETE BATCH UPLOAD
# ========================
async def complete_batch_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, protection_mode: str):
    query = update.callback_query
    user = update.effective_user
    batch_files = context.user_data.get('pending_batch', [])
    if not batch_files:
        await query.edit_message_text("❌ Batch session expired. Please start over with /batch.")
        return

    del context.user_data['pending_batch']

    content_id = "BATCH_" + uuid.uuid4().hex[:12].upper()

    content_data = {
        'content_id': content_id,
        'telegram_file_id': None,
        'text_data': json.dumps(batch_files),
        'content_type': ContentType.BATCH.value,
        'uploader_user_id': user.id,
        'uploader_username': user.username,
        'upload_timestamp': datetime.now(TIMEZONE),
        'auto_delete_time': db.get_auto_delete_time(),
        'protection_mode': protection_mode
    }

    db.add_content(content_data)
    await process_pending_referral(user.id, context)

    backup_msg = await forward_batch_to_backup_channel(update, context, content_id, batch_files, user)
    if backup_msg:
        db.update_backup_message_id(content_id, backup_msg.message_id)

    if context.user_data.get('upload_in_progress'):
        context.user_data['upload_in_progress'] = False
        progress_msg = context.user_data.get('upload_progress_msg')
        if progress_msg:
            try:
                await progress_msg.edit_text("📤 Upload Complete ✅")
            except:
                pass
        context.user_data.pop('upload_progress_msg', None)

    bot_username = (await context.bot.get_me()).username
    content_link = f"https://yourfilelinkbyxd.blogspot.com?start={content_id}"
    safe_content_id = escape_html(content_id)
    safe_content_link = escape_html(content_link)
    files_count = len(batch_files)

    confirmation_text = (
        f"✅ Content uploaded successfully!\n\n"
        f"🔗 Direct Access Link:\n"
        f"{safe_content_link}\n\n"
        f"🕵️ Secret ID (Private Access Key)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<code>{safe_content_id}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📁 Type: Batch\n"
        f"📦 Files Stored: {files_count}\n"
        f"{'🔒' if protection_mode=='protected' else '🔓'} Protection: {'Protected' if protection_mode=='protected' else 'Unprotected'}\n"
        f"🕒 Uploaded: {datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
        f"How to share:\n"
        f"<code>/get {safe_content_id}</code>\n\n"
        f"To delete this content send this:\n"
        f"<code>/delete {safe_content_id}</code>"
    )

    keyboard = [[InlineKeyboardButton("🔗 Open Content", url=content_link)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await query.edit_message_text(
            confirmation_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"HTML send failed: {e}. Falling back to plain text.")
        plain_text = confirmation_text.replace('<code>', '`').replace('</code>', '`')
        await query.edit_message_text(
            plain_text,
            disable_web_page_preview=True,
            reply_markup=reply_markup
        )

async def forward_batch_to_backup_channel(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                          content_id: str, batch_files: list, user) -> Optional[Message]:
    try:
        safe_content_id = escape_html(content_id)
        safe_user_id = escape_html(str(user.id))
        safe_username = escape_html(user.username) if user.username else "Not set"
        safe_full_name = escape_html(user.full_name)

        file_list = "\n".join([f"• {f['type']}: {f.get('file_id', 'text')[:20]}..." for f in batch_files])
        metadata = (
            f"📦 BATCH BACKUP\n\n"
            f"🕵️ Batch ID: <code>{safe_content_id}</code>\n"
            f"👤 Uploader: <a href='tg://user?id={user.id}'>{safe_full_name}</a>\n"
            f"🆔 User ID: <code>{safe_user_id}</code>\n"
            f"👤 Username: @{safe_username}\n"
            f"📁 Type: Batch\n"
            f"📦 Files: {len(batch_files)}\n\n"
            f"Files:\n{file_list}\n\n"
            f"⏰ {datetime.now(ZoneInfo('Asia/Dhaka')).strftime('%d %b %Y, %I:%M %p')}"
        )
        backup_msg = await context.bot.send_message(
            chat_id=BACKUP_CHANNEL_ID,
            text=metadata,
            parse_mode=ParseMode.HTML
        )
        logger.info(f"Batch backup sent to channel for content {content_id}")
        return backup_msg
    except Exception as e:
        logger.error(f"Error sending batch backup: {e}")
        return None

# ========================
# COMPLETE UPLOAD
# ========================
async def complete_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, content_data: Dict):
    try:
        user = update.effective_user
        content_id = db.add_content(content_data)
        await process_pending_referral(user.id, context)

        backup_msg = await forward_to_backup_channel(update, context, content_id, content_data)
        if backup_msg:
            db.update_backup_message_id(content_id, backup_msg.message_id)

        if 'pending_upload' in context.user_data:
            del context.user_data['pending_upload']

        if context.user_data.get('upload_in_progress'):
            context.user_data['upload_in_progress'] = False
            progress_msg = context.user_data.get('upload_progress_msg')
            if progress_msg:
                try:
                    await progress_msg.edit_text("📤 Upload Complete ✅")
                except:
                    pass
            context.user_data.pop('upload_progress_msg', None)

        protection_mode = content_data.get('protection_mode', 'protected')
        protection_emoji = "🔒" if protection_mode == 'protected' else "🔓"
        protection_text = "Protected (no save/forward)" if protection_mode == 'protected' else "Unprotected"

        bot_username = (await context.bot.get_me()).username
        content_link = f"https://yourfilelinkbyxd.blogspot.com?start={content_id}"

        auto_delete_hours = content_data.get('auto_delete_time', AUTO_DELETE_SECONDS) // 3600
        uploaded_time = content_data['upload_timestamp'].strftime('%Y-%m-%d %H:%M:%S UTC')

        safe_content_id = escape_html(content_id)
        safe_content_type = escape_html(content_data['content_type'])
        safe_protection_text = escape_html(protection_text)
        safe_uploaded_time = escape_html(uploaded_time)
        safe_content_link = escape_html(content_link)

        confirmation_text = (
            f"✅ Content uploaded successfully!\n\n"
            f"🔗 Direct Access Link:\n"
            f"{safe_content_link}\n\n"
            f"🕵️ Secret ID (Private Access Key)\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<code>{safe_content_id}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📁 Type: {safe_content_type}\n"
            f"{protection_emoji} Protection: {safe_protection_text}\n"
            f"🕒 Uploaded: {safe_uploaded_time}\n\n"
            f"How to share:\n"
            f"<code>/get {safe_content_id}</code>\n\n"
            f"To delete this content send this:\n"
            f"<code>/delete {safe_content_id}</code>"
        )

        keyboard = [[InlineKeyboardButton("🔗 Open Content", url=content_link)]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    confirmation_text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                    reply_markup=reply_markup
                )
            else:
                await context.bot.send_message(
                    chat_id=user.id,
                    text=confirmation_text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                    reply_markup=reply_markup
                )
        except Exception as html_error:
            logger.error(f"HTML send failed: {html_error}. Falling back to plain text.")
            plain_text = confirmation_text.replace('<code>', '`').replace('</code>', '`')
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    plain_text,
                    disable_web_page_preview=True,
                    reply_markup=reply_markup
                )
            else:
                await context.bot.send_message(
                    chat_id=user.id,
                    text=plain_text,
                    disable_web_page_preview=True,
                    reply_markup=reply_markup
                )
    except Exception as e:
        logger.error(f"Error completing upload: {e}")
        error_msg = "❌ An error occurred while processing your upload. Please try again."
        if update.callback_query:
            await update.callback_query.edit_message_text(error_msg)
        else:
            await context.bot.send_message(chat_id=user.id, text=error_msg)

# ========================
# BACKUP FORWARDING FUNCTION
# ========================
async def forward_to_backup_channel(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                   content_id: str, content_data: Dict) -> Optional[Message]:
    try:
        user = update.effective_user
        if not user:
            logger.error("No effective user in update for backup forwarding")
            return None

        protection_emoji = "🔒" if content_data.get('protection_mode') == 'protected' else "🔓"

        safe_full_name = escape_html(user.full_name)
        safe_username = escape_html(user.username) if user.username else "Not set"
        safe_user_id = escape_html(str(user.id))
        safe_content_id = escape_html(content_id)
        safe_content_type = escape_html(content_data['content_type'])

        metadata = (
            f"📋 CONTENT BACKUP\n\n"
            f"🕵️ Secret ID: <code>{safe_content_id}</code>\n"
            f"👤 Uploader: <a href='tg://user?id={user.id}'>{safe_full_name}</a>\n"
            f"🆔 User ID: <code>{safe_user_id}</code>\n"
            f"👤 Username: @{safe_username}\n"
            f"📁 Type: {safe_content_type}\n"
            f"⏰ Date & Time: {datetime.now(ZoneInfo('Asia/Dhaka')).strftime('%d %b %Y, %I:%M %p')}\n"
        )

        backup_msg = None

        if content_data['content_type'] == ContentType.TEXT.value:
            safe_text_data = escape_html(content_data['text_data'])
            full_text = f"{safe_text_data}\n\n{metadata}"
            try:
                backup_msg = await context.bot.send_message(
                    chat_id=BACKUP_CHANNEL_ID,
                    text=full_text,
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Text backup sent to channel for content {content_id}")
            except Exception as e:
                logger.error(f"Failed to send text backup to channel with HTML: {e}")
                try:
                    backup_msg = await context.bot.send_message(
                        chat_id=BACKUP_CHANNEL_ID,
                        text=full_text
                    )
                    logger.info(f"Text backup sent (without HTML) for content {content_id}")
                except Exception as e2:
                    logger.error(f"Also failed without HTML: {e2}")
        else:
            try:
                if content_data['content_type'] == ContentType.PHOTO.value:
                    backup_msg = await context.bot.send_photo(
                        chat_id=BACKUP_CHANNEL_ID,
                        photo=content_data['telegram_file_id'],
                        caption=metadata,
                        parse_mode=ParseMode.HTML
                    )
                elif content_data['content_type'] == ContentType.VIDEO.value:
                    backup_msg = await context.bot.send_video(
                        chat_id=BACKUP_CHANNEL_ID,
                        video=content_data['telegram_file_id'],
                        caption=metadata,
                        parse_mode=ParseMode.HTML
                    )
                elif content_data['content_type'] == ContentType.AUDIO.value:
                    backup_msg = await context.bot.send_audio(
                        chat_id=BACKUP_CHANNEL_ID,
                        audio=content_data['telegram_file_id'],
                        caption=metadata,
                        parse_mode=ParseMode.HTML
                    )
                elif content_data['content_type'] == ContentType.FILE.value:
                    backup_msg = await context.bot.send_document(
                        chat_id=BACKUP_CHANNEL_ID,
                        document=content_data['telegram_file_id'],
                        caption=metadata,
                        parse_mode=ParseMode.HTML
                    )
                logger.info(f"Media backup sent to channel for content {content_id}")
            except Exception as e:
                logger.error(f"Failed to send media backup to channel with HTML: {e}")
                try:
                    if content_data['content_type'] == ContentType.PHOTO.value:
                        backup_msg = await context.bot.send_photo(
                            chat_id=BACKUP_CHANNEL_ID,
                            photo=content_data['telegram_file_id'],
                            caption=metadata
                        )
                    elif content_data['content_type'] == ContentType.VIDEO.value:
                        backup_msg = await context.bot.send_video(
                            chat_id=BACKUP_CHANNEL_ID,
                            video=content_data['telegram_file_id'],
                            caption=metadata
                        )
                    elif content_data['content_type'] == ContentType.AUDIO.value:
                        backup_msg = await context.bot.send_audio(
                            chat_id=BACKUP_CHANNEL_ID,
                            audio=content_data['telegram_file_id'],
                            caption=metadata
                        )
                    elif content_data['content_type'] == ContentType.FILE.value:
                        backup_msg = await context.bot.send_document(
                            chat_id=BACKUP_CHANNEL_ID,
                            document=content_data['telegram_file_id'],
                            caption=metadata
                        )
                    logger.info(f"Media backup sent (without HTML) for content {content_id}")
                except Exception as e2:
                    logger.error(f"Also failed without HTML: {e2}")

        return backup_msg

    except Exception as e:
        logger.error(f"Unexpected error in forward_to_backup_channel: {e}")
        return None

# ========================
# CONTENT DELIVERY SYSTEM
# ========================
async def get_content_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_maintenance(update, context):
        return
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        if await require_channel_join(update, context):
            return

    if not context.args:
        await update.message.reply_text(
            "🕵️ **Access via Secret ID**\n\n"
            "Usage: `/get <secret_id>`\n\n"
            "Example: `/get abc123xyz456`\n\n"
            f"The content will auto-delete after {AUTO_DELETE_SECONDS//3600} hour(s).",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    content_id = context.args[0].strip()

    try:
        content = db.get_content(content_id)
        if not content:
            await update.message.reply_text(
                "❌ **Content not found!**\n\n"
                "The provided **Secret ID** is invalid or has expired.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        await process_pending_referral(user.id, context)
        view_reward = db.record_view(content_id, user.id)

        # Batch content
        if content['content_type'] == ContentType.BATCH.value:
            try:
                batch_files = json.loads(content['text_data'])
            except:
                await update.message.reply_text("❌ Error reading batch content.")
                return

            protection_mode = content.get('protection_mode', 'protected')
            protect_content = protection_mode == 'protected'

            status_msg = await update.message.reply_text(f"📦 Sending {len(batch_files)} files...")
            sent_count = 0
            for file_info in batch_files:
                try:
                    sent = None
                    if file_info['type'] == 'photo':
                        sent = await context.bot.send_photo(
                            chat_id=user.id,
                            photo=file_info['file_id'],
                            caption=file_info.get('caption', ''),
                            protect_content=protect_content
                        )
                    elif file_info['type'] == 'video':
                        sent = await context.bot.send_video(
                            chat_id=user.id,
                            video=file_info['file_id'],
                            caption=file_info.get('caption', ''),
                            protect_content=protect_content
                        )
                    elif file_info['type'] == 'audio':
                        sent = await context.bot.send_audio(
                            chat_id=user.id,
                            audio=file_info['file_id'],
                            caption=file_info.get('caption', ''),
                            protect_content=protect_content
                        )
                    elif file_info['type'] == 'document':
                        sent = await context.bot.send_document(
                            chat_id=user.id,
                            document=file_info['file_id'],
                            caption=file_info.get('caption', ''),
                            protect_content=protect_content
                        )
                    elif file_info['type'] == 'text':
                        sent = await context.bot.send_message(
                            chat_id=user.id,
                            text=file_info['text'],
                            protect_content=protect_content
                        )
                    sent_count += 1

                    if sent and hasattr(sent, 'message_id'):
                        asyncio.create_task(
                            delete_message_after_delay(context, user.id, sent.message_id, AUTO_DELETE_SECONDS)
                        )
                except Exception as e:
                    logger.error(f"Failed to send batch file: {e}")
            await status_msg.delete()

            reply_text = f"📦 Sent {sent_count} files.\n"
            reply_text += "```সাবধান  অনুগ্রহ করে এই ফাইলটি আপনার ব্যক্তিগত চ্যাট যেমন সংরক্ষিত বার্তা বা যেকোনো গ্রুপে ফরোয়ার্ড করুন।

কিছুক্ষণ পরে ফাইলটি স্বয়ংক্রিয়ভাবে মুছে ফেলা হবে। Please Forward this file to your personal chat like saved message or any group.File will be Auto Deleted after few minutes```"
            await update.message.reply_text(reply_text, parse_mode=ParseMode.MARKDOWN)
            return

        # Single content delivery
        content_type_names = {
            'file': '📄 File',
            'video': '🎬 Video',
            'audio': '🎵 Audio',
            'photo': '🖼 Photo',
            'text': '📝 Text'
        }
        content_type_display = content_type_names.get(content['content_type'], content['content_type'])
        protection_mode = content.get('protection_mode', 'protected')
        protect_content = protection_mode == 'protected'
        protection_text = "🔒 Protected" if protect_content else "🔓 Unprotected"

        user_caption = content.get("text_data", "").strip()
        if user_caption:
            user_caption = escape_markdown(user_caption)
            if len(user_caption) > 1024:
                user_caption = user_caption[:1000] + "..."
            caption = (
                f"━━━━━━━━━━━━━━\n"
                f"{user_caption}\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"{protection_text}\n"
                f"⚡ Powered by  ◯│Kᴀɪᴢᴇɴ X Share"
            )
        else:
            caption = (
                f"{protection_text}\n"
                f"⚡ Powered by  ◯│Kᴀɪᴢᴇɴ X Share"
            )

        status_msg = await update.message.reply_text("⏳ Loading content...")
        await asyncio.sleep(1)
        await status_msg.edit_text("🔜 Preparing file...")
        await asyncio.sleep(1)
        await status_msg.edit_text("😊 Sending now...")
        await asyncio.sleep(0.5)
        await status_msg.delete()

        send_methods = {
            'text': lambda: update.message.reply_text(
                f"**📝 Text Content**\n\n{content['text_data']}\n\n{caption}",
                parse_mode=ParseMode.MARKDOWN
            ),
            'photo': lambda: context.bot.send_photo(
                chat_id=user.id,
                photo=content['telegram_file_id'],
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                protect_content=protect_content
            ),
            'video': lambda: context.bot.send_video(
                chat_id=user.id,
                video=content['telegram_file_id'],
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                protect_content=protect_content
            ),
            'audio': lambda: context.bot.send_audio(
                chat_id=user.id,
                audio=content['telegram_file_id'],
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                protect_content=protect_content
            ),
            'file': lambda: context.bot.send_document(
                chat_id=user.id,
                document=content['telegram_file_id'],
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                protect_content=protect_content
            )
        }

        sent_message = await send_methods[content['content_type']]()

        if hasattr(sent_message, 'message_id'):
            asyncio.create_task(
                delete_message_after_delay(context, user.id, sent_message.message_id, AUTO_DELETE_SECONDS)
            )

        reply_text = "```সাবধান অনুগ্রহ করে এই ফাইলটি আপনার ব্যক্তিগত চ্যাট যেমন সংরক্ষিত বার্তা বা যেকোনো গ্রুপে ফরোয়ার্ড করুন।

কিছুক্ষণ পরে ফাইলটি স্বয়ংক্রিয়ভাবে মুছে ফেলা হবে। Please Forward this file to your personal chat like saved message or any group.File will be Auto Deleted after few minutes```\n\n"
        reply_text += "```Check your chat with me for the content☺️```"
        await update.message.reply_text(reply_text, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Error getting content: {e}")
        await update.message.reply_text(
            "❌ An error occurred while retrieving the content. Please try again.",
            parse_mode=ParseMode.MARKDOWN
        )

async def delete_message_after_delay(context: ContextTypes.DEFAULT_TYPE,
                                    chat_id: int,
                                    message_id: int,
                                    delay_seconds: int):
    try:
        await asyncio.sleep(delay_seconds)
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Auto-deleted message {message_id} after {delay_seconds}s")
    except Exception as e:
        logger.error(f"Error auto-deleting message: {e}")

# ========================
# DELETE CONTENT COMMAND
# ========================
async def delete_content_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_maintenance(update, context):
        return
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        if await require_channel_join(update, context):
            return

    if not context.args:
        await update.message.reply_text(
            "🗑️ **Delete Content**\n\n"
            "Usage: `/delete <content_id>`\n\n"
            "Example: `/delete abc123xyz456`\n\n"
            "You can only delete content that you uploaded.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    content_id = context.args[0].strip()

    try:
        success = db.delete_content(content_id, user.id)
        if success:
            await update.message.reply_text(
                f"✅ **Content deleted successfully!**\n\n"
                f"Content ID: `{content_id}`\n"
                f"The content has been permanently removed from the bot.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                "❌ **Cannot delete content!**\n\n"
                "Possible reasons:\n"
                "• Content ID not found\n"
                "• You are not the uploader\n"
                "• Content already deleted",
                parse_mode=ParseMode.MARKDOWN
            )
    except Exception as e:
        logger.error(f"Error deleting content: {e}")
        await update.message.reply_text(
            "❌ An error occurred while deleting the content. Please try again.",
            parse_mode=ParseMode.MARKDOWN
        )

# ========================
# PROFILE COMMAND (UPGRADED with earnings)
# ========================
def escape_md(text):
    if text is None:
        return ""
    escape_chars = r'_*`[]()'
    return ''.join(f'\\{c}' if c in escape_chars else c for c in str(text))

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_maintenance(update, context):
        return
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        if await require_channel_join(update, context):
            return

    try:
        user_data = db.get_user(user.id)
        if not user_data:
            db.add_user(user.id, user.username)
            user_data = db.get_user(user.id)

        earnings = db.get_user_earnings_summary(user.id)
        payment = db.get_user_payment(user.id)
        payment_info = "Not set"
        if payment:
            method = payment['payment_method']
            details = payment['payment_details']
            masked = details[-4:] if len(details) > 4 else details
            payment_info = f"{method} - ...{masked}"

        if user.id in ADMIN_IDS:
            channel_status = "👑 Admin (bypass)"
        else:
            channel_status = "✅ Verified" if user_data.get('has_joined_all_channels') else "❌ Not verified"

        ban_status = "🚫 BANNED" if db.is_user_banned(user.id) else "✅ Active"

        user_contents = db.get_user_contents(user.id)
        total_uploads = len(user_contents)
        content_stats = db.get_content_stats_by_user(user.id)
        stats_text = ""
        for content_type in ContentType:
            count = content_stats.get(content_type.value, 0)
            if count > 0:
                emoji = {'file':'📄','video':'🎬','audio':'🎵','photo':'🖼','text':'📝','batch':'📦'}.get(content_type.value,'📁')
                stats_text += f"{emoji} {content_type.value.title()}: {count}\n"

        recent_ids = [content['content_id'] for content in user_contents[:10]]

        profile_msg = (
            f"👤 **Your Profile**\n\n"
            f"🆔 **User ID:** `{user.id}`\n"
            f"👤 **Username:** @{escape_md(user.username) or 'Not set'}\n"
            f"📅 **Join Date:** {escape_md(user_data.get('join_date', 'N/A'))}\n"
            f"📢 **Channel Status:** {channel_status}\n"
            f"🚫 **Account Status:** {ban_status}\n\n"
            f"💰 **Earnings Summary**\n"
            f"📊 **Total Balance:** `${earnings.get('balance', 0):.2f}`\n"
            f"• Referral Earnings: `${earnings.get('referral_earnings', 0):.2f}`\n"
            f"• View Earnings: `${earnings.get('view_earnings', 0):.2f}`\n"
            f"• Total Withdrawn: `${earnings.get('total_withdrawn', 0):.2f}`\n"
            f"👥 **Total Referrals:** {earnings.get('total_referrals', 0)}\n"
            f"👁 **Total Paid Views:** {earnings.get('total_views', 0)}\n\n"
            f"💳 **Current Payment Method:**\n`{payment_info}`\n\n"
            f"🔗 **Your Referral Link:**\n"
            f"`https://t.me/{(await context.bot.get_me()).username}?start={user.id}`\n\n"
            f"📊 **Upload Statistics**\n"
            f"📈 **Total Uploads:** {total_uploads}\n"
        )
        if stats_text:
            profile_msg += f"\n**Breakdown by Type:**\n{stats_text}"
        if recent_ids:
            profile_msg += f"\n**Recent Content IDs:**\n"
            for content_id in recent_ids:
                profile_msg += f"• `{content_id}`\n"
            if len(user_contents) > 10:
                profile_msg += f"\n... and {len(user_contents) - 10} more"

        if db.is_user_banned(user.id):
            profile_msg += f"\n\n🚫 **Ban Information:**\n"
            profile_msg += f"• **Reason:** {escape_md(user_data.get('ban_reason', 'No reason'))}\n"
            profile_msg += f"• **Date:** {escape_md(user_data.get('ban_date', 'Unknown'))}"

        keyboard = []
        if total_uploads > 0:
            keyboard.append([InlineKeyboardButton("📥 View All Uploads", callback_data=f"view_uploads_{user.id}")])
        keyboard.append([InlineKeyboardButton("💳 Set Payment Method", callback_data="set_payment")])
        keyboard.append([InlineKeyboardButton("💰 Withdraw", callback_data="withdraw_help")])
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

        await update.message.reply_text(
            profile_msg,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Error in profile command: {e}")
        await update.message.reply_text(
            "❌ An error occurred while loading your profile.",
            parse_mode=ParseMode.MARKDOWN
        )

# ========================
# START COMMAND
# ========================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.username)

    if context.args and len(context.args) > 0:
        arg = context.args[0].strip()
        if arg.isdigit():
            referrer_id = int(arg)
            if referrer_id != user.id and db.get_user(referrer_id):
                context.user_data["pending_referrer"] = referrer_id
        else:
            context.args = [arg]
            await get_content_command(update, context)
            return

    if user.id not in ADMIN_IDS:
        if await require_channel_join(update, context):
            return

    welcome_msg = (
    f"👋 Hii {user.first_name}!\n\n"
    f"🚀 *Welcome to Kaizen X Share*\n\n"

    f"📤 *Upload & Share Instantly*\n"
    f"• Files, Videos, Audio\n"
    f"• Photos & Text\n"
    f"• **Batch Upload** (use /batch)\n\n"

    f"🆔 *Private Secret ID System*\n"
    f"• Get a unique Secret ID\n"
    f"• Share securely with anyone\n"
    f"• Auto-deletes after {AUTO_DELETE_SECONDS//3600} hour(s)\n\n"

    f"💰 *Earn Real Rewards*\n"
    f"• Referral Bonus: ${float(db.get_setting('referral_reward','0.01')):.2f} per user\n"
    f"• View Reward: ${float(db.get_setting('view_reward','0.01')):g} per unique view\n\n"

    f"📌 *Main Commands*\n"
    f"• /get — Access content via Secret ID\n"
    f"• /profile — View earnings & uploads\n"
    f"• /delete — Remove your content\n"
    f"• /withdraw — Request payout\n"
    f"• /setpayment — Set payout method\n"
    f"• /batch — Upload multiple files at once\n"
    f"• /done — Finish batch upload\n"
    f"• /help — Help & guide\n\n"

    f"✨ Simply send any content to get started!"
)

    reply_markup = main_menu_keyboard()

    await update.message.reply_text(
        welcome_msg,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_maintenance(update, context):
        return
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        if await require_channel_join(update, context):
            return

    help_msg = (
        "❓ **Help & Guide**\n\n"
        "**📤 How to Upload:**\n"
        "1. Send me any content (file, video, audio, photo, or text)\n"
        "2. I'll generate a unique **Secret ID**\n"
        "3. Share this ID with anyone\n\n"
        "**📦 Batch Upload:**\n"
        "1. Use /batch to start batch mode\n"
        "2. Send multiple files\n"
        "3. Use /done to finish and get a single Secret ID\n"
        "4. All files will be sent together when accessed\n\n"
        "**📥 How to Retrieve:**\n"
        "1. Use `/get <secret_id>`\n"
        f"2. It auto-deletes after {AUTO_DELETE_SECONDS//3600} hour(s)\n\n"
        "**💰 Earnings:**\n"
        f"• Referral: `${float(db.get_setting('referral_reward','0.01')):g}` per new user\n"
        f"• View: `${float(db.get_setting('view_reward','0.01')):g}` per view of your content\n"
        f"• Minimum withdrawal: `${float(db.get_setting('min_withdrawal','1.00')):.2f}`\n\n"
        "**💳 Payment Methods:**\n"
        "• Binance (UID or Email)\n"
        "• PayPal (Email)\n"
        "• TRX (TRC20 wallet)\n"
        "• BEP20 (USDT/BNB wallet)\n\n"
        "Use `/setpayment` to set your method.\n\n"
        "**🗑️ How to Delete:**\n"
        "Use `/delete <secret_id>` (only your own)\n\n"
        "**👤 Your Profile:**\n"
        "`/profile` shows your earnings, referral link, and stats.\n\n"
        f"📢 **Channel Requirements:**\n"
        f"You must join {len(FORCE_JOIN_CHANNELS)} channel(s) to use the bot."
    )
    await update.message.reply_text(help_msg, parse_mode=ParseMode.MARKDOWN)

# ========================
# PAYMENT SETUP CONVERSATION
# ========================
async def setpayment_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if await check_maintenance(update, context) or await check_ban_status(update, context):
        return ConversationHandler.END
    if user.id not in ADMIN_IDS and await require_channel_join(update, context):
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("Binance", callback_data="pay_binance")],
        [InlineKeyboardButton("PayPal", callback_data="pay_paypal")],
        [InlineKeyboardButton("TRX (TRC20)", callback_data="pay_trx")],
        [InlineKeyboardButton("BEP20", callback_data="pay_bep20")],
        [InlineKeyboardButton("❌ Cancel", callback_data="pay_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "💳 **Set Payment Method**\n\n"
        "Please choose your preferred payment method🔝⚠️ If Buttons are not working then send this command /setpayment",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    return SET_PAYMENT_METHOD

async def setpayment_method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    method_map = {
        'pay_binance': 'Binance',
        'pay_paypal': 'PayPal',
        'pay_trx': 'TRX (TRC20)',
        'pay_bep20': 'BEP20'
    }
    method = method_map.get(query.data)
    if not method:
        await query.edit_message_text("❌ Setup cancelled.")
        return ConversationHandler.END

    context.user_data['payment_method'] = method

    prompt = {
        'Binance': "Please send your **Binance UID or Email**.",
        'PayPal': "Please send your **PayPal Email**.",
        'TRX (TRC20)': "Please send your **TRX (TRC20) wallet address**.",
        'BEP20': "Please send your **BEP20 wallet address** (for USDT/BNB)."
    }[method]

    await query.edit_message_text(
        f"💳 **{method}**\n\n{prompt}\n\n"
        f"Send the details as a text message.\n"
        f"Type /cancel to abort.",
        parse_mode=ParseMode.MARKDOWN
    )
    return SET_PAYMENT_DETAILS

async def setpayment_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    details = update.message.text.strip()
    method = context.user_data.get('payment_method')

    if not method:
        await update.message.reply_text("❌ Session expired. Please start again with /setpayment.")
        return ConversationHandler.END

    valid = False
    if method == 'Binance':
        if '@' in details or details.isdigit():
            valid = True
    elif method == 'PayPal':
        if '@' in details and '.' in details:
            valid = True
    elif method in ('TRX (TRC20)', 'BEP20'):
        if len(details) >= 30 and len(details) <= 50:
            valid = True

    if not valid:
        await update.message.reply_text(
            "❌ Invalid format. Please check and try again.\n"
            "Send /setpayment to restart."
        )
        return SET_PAYMENT_DETAILS

    if db.set_user_payment(user.id, method, details):
        await update.message.reply_text(
            f"✅ **Payment method saved!**\n\n"
            f"**Method:** {method}\n"
            f"**Details:** `{details}`\n\n"
            f"You can now use /withdraw to request payout.",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text("❌ Failed to save. Please try again later.")

    context.user_data.pop('payment_method', None)
    return ConversationHandler.END

async def setpayment_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.edit_message_text("❌ Setup cancelled.")
    else:
        await update.message.reply_text("❌ Setup cancelled.")
    context.user_data.pop('payment_method', None)
    return ConversationHandler.END

# ========================
# WITHDRAW COMMAND
# ========================
async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if await check_maintenance(update, context) or await check_ban_status(update, context):
        return
    if user.id not in ADMIN_IDS and await require_channel_join(update, context):
        return

    payment = db.get_user_payment(user.id)
    if not payment:
        await update.message.reply_text(
            "❌ **No payment method set!**\n\n"
            "Please set your payment method first using /setpayment.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    balance = db.get_user_balance(user.id)
    min_withdrawal = float(db.get_setting('min_withdrawal', '1.00'))

    if balance < min_withdrawal:
        await update.message.reply_text(
            f"❌ **Insufficient balance for withdrawal.**\n\n"
            f"Your available balance: **${balance:.2f}**\n"
            f"Minimum withdrawal: **${min_withdrawal:.2f}**\n\n"
            f"Earn more by referring friends and uploading content!",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if context.args:
        try:
            amount = float(context.args[0])
            if amount < min_withdrawal:
                await update.message.reply_text(f"❌ Minimum withdrawal is ${min_withdrawal:.2f}.")
                return
            if amount > balance:
                await update.message.reply_text(f"❌ Insufficient balance. You have ${balance:.2f} available.")
                return

            withdrawal_id = db.create_withdrawal(user.id, amount, payment['payment_method'], payment['payment_details'])
            if withdrawal_id:
                await update.message.reply_text(
                    f"✅ **Withdrawal request submitted!**\n\n"
                    f"**Amount:** ${amount:.2f}\n"
                    f"**Payment Method:** {payment['payment_method']}\n"
                    f"**Details:** `{payment['payment_details']}`\n"
                    f"**Status:** Pending\n\n"
                    f"Your request ID: `{withdrawal_id}`\n\n"
                    f"Admins will process it soon. You'll be notified.",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text("❌ Failed to create withdrawal. Please try again.")
        except ValueError:
            await update.message.reply_text("❌ Invalid amount. Please enter a number.")
    else:
        await update.message.reply_text(
            f"💰 **Withdraw Funds**\n\n"
            f"Your available balance: **${balance:.2f}**\n"
            f"Minimum withdrawal: **${min_withdrawal:.2f}**\n\n"
            f"**Payment Method:** {payment['payment_method']}\n"
            f"**Details:** `{payment['payment_details']}`\n\n"
            f"To request withdrawal, use:\n"
            f"`/withdraw <amount>`\n\n"
            f"Example: `/withdraw {min_withdrawal}`",
            parse_mode=ParseMode.MARKDOWN
        )

# ========================
# ADMIN WITHDRAWAL MANAGEMENT
# ========================
@admin_only
async def withdrawals_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    page = 0
    status_filter = "pending"
    user_filter = None
    min_amount = None
    max_amount = None

    for arg in args:
        if arg.isdigit() and len(arg) > 5:
            user_filter = int(arg)
        elif arg.lower() in ["pending", "approved", "rejected", "all"]:
            status_filter = arg.lower()
        elif arg.replace('.', '', 1).isdigit():
            if min_amount is None:
                min_amount = float(arg)
            else:
                max_amount = float(arg)

    if args and args[-1].isdigit() and len(args[-1]) <= 3:
        page = int(args[-1])

    # Build query
    query = {}
    if status_filter != "all":
        query["status"] = status_filter
    if user_filter:
        query["user_id"] = user_filter
    if min_amount is not None:
        query["amount"] = {"$gte": min_amount}
    if max_amount is not None:
        if "amount" in query:
            query["amount"]["$lte"] = max_amount
        else:
            query["amount"] = {"$lte": max_amount}

    cursor = withdrawals_col.find(query).sort("requested_at", DESCENDING)
    results = list(cursor)

    if not results:
        await update.message.reply_text("❌ No matching withdrawals found.")
        return

    per_page = 10
    total_pages = (len(results) - 1) // per_page + 1
    page = max(0, min(page, total_pages - 1))

    start = page * per_page
    end = start + per_page
    withdrawals_slice = results[start:end]

    for w in withdrawals_slice:
        buttons = []
        if w["status"] == "pending":
            buttons = [
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"wd_approve_{w['_id']}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"wd_reject_{w['_id']}")
                ]
            ]

        keyboard = InlineKeyboardMarkup(buttons) if buttons else None

        # get username
        user_info = users_col.find_one({"user_id": w["user_id"]}, {"username": 1})
        username = user_info["username"] if user_info else "N/A"
        if username != "N/A":
            username = escape_md(username)

        text = (
            f"💰 *Withdrawal #{w['_id']}*\n\n"
            f"👤 User ID: `{w['user_id']}`\n"
            f"👤 Username: @{username}\n"
            f"💵 Amount: `${w['amount']:.2f}`\n"
            f"📊 Status: *{w['status'].upper()}*\n"
            f"💳 Method: {w['payment_method']}\n"
            f"📝 Details: `{w['payment_details']}`\n"
            f"📅 Requested: {w['requested_at']}"
        )

        await update.message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅ Previous", callback_data=f"wd_page_{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ➡", callback_data=f"wd_page_{page+1}"))

    if nav:
        await update.message.reply_text(
            f"📄 Page {page+1}/{total_pages}",
            reply_markup=InlineKeyboardMarkup([nav])
        )

@admin_only
async def handle_withdrawal_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split("_")

    if data[1] == "page":
        context.args = [data[2]]
        await withdrawals_command(update, context)
        return

    action = data[1]
    withdrawal_id = data[2]  # string ObjectId

    success = db.process_withdrawal(withdrawal_id, query.from_user.id, "completed" if action == "approve" else "rejected")

    if not success:
        await query.edit_message_text("⚠️ Already processed or invalid withdrawal.")
        return

    # Fetch withdrawal info for user notification
    from bson.objectid import ObjectId
    w = withdrawals_col.find_one({"_id": ObjectId(withdrawal_id)})
    if w:
        user_id = w["user_id"]
        amount = w["amount"]
        try:
            msg = (
                f"🎉 Withdrawal Approved!\n\n💵 Amount: ${amount:.2f}"
                if action == "approve"
                else f"❌ Withdrawal Rejected\n\n💵 Amount: ${amount:.2f}"
            )
            await context.bot.send_message(chat_id=user_id, text=msg)
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")

    await query.edit_message_text(
        f"💰 Withdrawal #{withdrawal_id}\n\n"
        f"{'✅ Approved' if action == 'approve' else '❌ Rejected'}\n"
        f"Processed by admin {query.from_user.id}"
    )

# ========================
# ADMIN REWARD SETTINGS
# ========================
@admin_only
async def setreward_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text(
            "Usage: `/setreward referral 0.02`\n"
            "       `/setreward view 0.015`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    reward_type = context.args[0].lower()
    try:
        amount = float(context.args[1])
        if amount < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Must be a positive number.")
        return
    if reward_type == 'referral':
        db.set_setting('referral_reward', str(amount))
        await update.message.reply_text(f"✅ Referral reward set to `${amount:.2f}`.")
    elif reward_type == 'view':
        db.set_setting('view_reward', str(amount))
        await update.message.reply_text(f"✅ View reward set to `${amount:.2f}`.")
    else:
        await update.message.reply_text("❌ Type must be 'referral' or 'view'.")

@admin_only
async def setminwithdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Usage: `/setminwithdraw 2.0`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        amount = float(context.args[0])
        if amount < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Invalid amount.")
        return
    db.set_setting('min_withdrawal', str(amount))
    await update.message.reply_text(f"✅ Minimum withdrawal set to `${amount:.2f}`.")

# ========================
# ADMIN STATS COMMAND
# ========================
@admin_only
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        stats = db.get_global_stats()
        maintenance_mode = db.get_maintenance_mode()
        auto_delete_time = db.get_auto_delete_time()

        content_stats_text = ""
        contents_by_type = stats.get('contents_by_type', {})
        for content_type, count in contents_by_type.items():
            emoji = {'file':'📄','video':'🎬','audio':'🎵','photo':'🖼','text':'📝','batch':'📦'}.get(content_type,'📁')
            content_stats_text += f"{emoji} {content_type.title()}: {count}\n"

        protection_stats_text = ""
        contents_by_protection = stats.get('contents_by_protection', {})
        for protection_mode, count in contents_by_protection.items():
            emoji = "🔒" if protection_mode == 'protected' else "🔓"
            protection_stats_text += f"{emoji} {protection_mode.title()}: {count}\n"

        channels_info = "\n".join(
            [f"• {channel['title']} (ID: {channel['id']})" for channel in FORCE_JOIN_CHANNELS]
        ) if FORCE_JOIN_CHANNELS else "No channels configured"

        total_earnings = stats.get('total_earnings', 0)
        total_referrals = stats.get('total_referrals', 0)
        total_views = stats.get('total_views', 0)
        total_withdrawals = stats.get('total_withdrawals', 0)
        pending_withdrawals = stats.get('pending_withdrawals', 0)

        stats_msg = (
            f"📊 **Bot Statistics**\n\n"
            f"👥 **Total Users:** {stats.get('total_users', 0)}\n"
            f"✅ **Verified Users:** {stats.get('verified_users', 0)}\n"
            f"🚫 **Banned Users:** {stats.get('banned_users', 0)}\n"
            f"📁 **Total Contents:** {stats.get('total_contents', 0)}\n"
            f"👑 **Active Admins:** {len(ADMIN_IDS)}\n"
            f"🔧 **Maintenance Mode:** {maintenance_mode}\n"
            f"⏰ **Auto-delete Time:** {auto_delete_time//3600} hour(s)\n\n"
            f"💰 **Earnings Distributed:** `${total_earnings:.2f}`\n"
            f"👥 **Total Referrals:** {total_referrals}\n"
            f"👁 **Total Paid Views:** {total_views}\n"
            f"💳 **Total Withdrawals:** {total_withdrawals}\n"
            f"⏳ **Pending Withdrawals:** {pending_withdrawals}\n\n"
        )
        if content_stats_text:
            stats_msg += f"**Contents by Type:**\n{content_stats_text}\n"
        if protection_stats_text:
            stats_msg += f"**Contents by Protection:**\n{protection_stats_text}\n"
        stats_msg += (
            f"📢 **Force Join Channels:**\n{channels_info}\n\n"
            f"🔒 **Backup Channel:** {'✅ Connected' if BACKUP_CHANNEL_ID else '❌ Not set'}"
        )
        await update.message.reply_text(stats_msg, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error in stats command: {e}")
        await update.message.reply_text("❌ An error occurred while fetching statistics.")

# ========================
# ADMIN COMMANDS
# ========================
@admin_only
async def maintenance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current_mode = db.get_maintenance_mode()
    if not context.args:
        await update.message.reply_text(
            f"🔧 **Maintenance Mode**\n\n"
            f"Current status: **{current_mode}**\n\n"
            f"Usage: `/maintenance <ON|OFF>`\n"
            f"Example: `/maintenance ON`\n"
            f"Example: `/maintenance OFF`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    new_mode = context.args[0].upper()
    if new_mode not in ['ON', 'OFF']:
        await update.message.reply_text("❌ Invalid mode. Use 'ON' or 'OFF'.", parse_mode=ParseMode.MARKDOWN)
        return
    db.set_maintenance_mode(new_mode)
    status_text = "🔴 ACTIVATED" if new_mode == 'ON' else "🟢 DEACTIVATED"
    message_text = f"✅ **Maintenance Mode {status_text}**\n\n"
    if new_mode == 'ON':
        message_text += "Normal users will now see maintenance message.\nAdmins can still use all commands."
    else:
        message_text += "All users can now access the bot normally."
    await update.message.reply_text(message_text, parse_mode=ParseMode.MARKDOWN)

@admin_only
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args and not update.message.reply_to_message:
        await update.message.reply_text(
            "📢 **Broadcast Message**\n\n"
            "Usage: `/adms <message>`\n"
            "Or reply to a message with `/adms`\n\n"
            "This will send your message to all bot users.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    try:
        users = list(users_col.find({}, {"user_id": 1}))
        total_users = len(users)
        if total_users == 0:
            await update.message.reply_text("❌ No users found in database.")
            return
        status_msg = await update.message.reply_text(f"📤 Starting broadcast to {total_users} users...\n⏳ Please wait...")
        success_count = 0
        fail_count = 0
        if update.message.reply_to_message:
            replied = update.message.reply_to_message
            for user_doc in users:
                try:
                    await replied.forward(chat_id=user_doc["user_id"])
                    success_count += 1
                except:
                    fail_count += 1
        else:
            broadcast_text = " ".join(context.args)
            for user_doc in users:
                try:
                    await context.bot.send_message(
                        chat_id=user_doc["user_id"],
                        text=f"⚠️ **Important Notice**\n\n{broadcast_text}",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    success_count += 1
                except BadRequest as e:
                    # Fallback: retry without parse_mode if Markdown fails
                    if "Can't parse entities" in str(e):
                        try:
                            await context.bot.send_message(
                                chat_id=user_doc["user_id"],
                                text=f"⚠️ Important Notice\n\n{broadcast_text}"
                            )
                            success_count += 1
                        except:
                            fail_count += 1
                    else:
                        fail_count += 1
                except:
                    fail_count += 1
        await status_msg.edit_text(
            f"✅ **Broadcast Complete!**\n\n"
            f"📊 **Statistics:**\n"
            f"• Total users: {total_users}\n"
            f"• ✅ Successful: {success_count}\n"
            f"• ❌ Failed: {fail_count}\n"
            f"• 📈 Success rate: {(success_count/total_users*100):.1f}%\n\n"
            f"{'🎉 All messages sent successfully!' if fail_count == 0 else '⚠️ Some messages failed to deliver.'}",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Error in broadcast command: {e}")
        await update.message.reply_text("❌ An error occurred during broadcast.", parse_mode=ParseMode.MARKDOWN)

@admin_only
async def settime_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current_time = db.get_auto_delete_time()
    if not context.args:
        await update.message.reply_text(
            f"⏰ **Auto-Delete Time**\n\n"
            f"Current setting: **{current_time//3600} hour(s)** ({current_time} seconds)\n\n"
            f"Usage: `/settime <hours>`\n"
            f"Example: `/settime 2` (for 2 hours)\n"
            f"Example: `/settime 0.5` (for 30 minutes)\n\n"
            f"Note: Changes apply to new uploads only.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    try:
        hours = float(context.args[0])
        if hours <= 0:
            await update.message.reply_text("❌ Time must be greater than 0.")
            return
        seconds = int(hours * 3600)
        db.set_auto_delete_time(seconds)
        await update.message.reply_text(
            f"✅ **Auto-delete time updated!**\n\n"
            f"New setting: **{hours} hour(s)** ({seconds} seconds)\n"
            f"This will apply to all new uploads.\n\n"
            f"Existing content will use their original settings.",
            parse_mode=ParseMode.MARKDOWN
        )
    except ValueError:
        await update.message.reply_text("❌ Invalid time format. Use a number (e.g., 1, 2, 0.5).")
    except Exception as e:
        logger.error(f"Error in settime command: {e}")
        await update.message.reply_text("❌ An error occurred while setting time.")

@admin_only
async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args and not update.message.reply_to_message:
        await update.message.reply_text(
            "🚫 **Ban User**\n\n"
            "Usage: `/ban <user_id> [reason]`\n"
            "Or reply to a user's message with `/ban [reason]`\n\n"
            "Examples:\n"
            "• `/ban 123456789` (default reason)\n"
            "• `/ban 123456789 Spam uploads`\n"
            "• Reply to message: `/ban Violating terms`\n\n"
            "Banned users cannot upload new content.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    user = update.effective_user
    target_user_id = None
    reason = "No reason provided"
    if update.message.reply_to_message:
        target_user_id = update.message.reply_to_message.from_user.id
        if context.args:
            reason = " ".join(context.args)
    else:
        try:
            target_user_id = int(context.args[0])
            if len(context.args) > 1:
                reason = " ".join(context.args[1:])
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. User ID must be a number.", parse_mode=ParseMode.MARKDOWN)
            return
    if not target_user_id:
        await update.message.reply_text("❌ Could not identify user to ban.", parse_mode=ParseMode.MARKDOWN)
        return
    if target_user_id == user.id:
        await update.message.reply_text("❌ You cannot ban yourself!")
        return
    if target_user_id in ADMIN_IDS:
        await update.message.reply_text("❌ You cannot ban another admin!")
        return
    try:
        target_user = await context.bot.get_chat(target_user_id)
        username = target_user.username
        user_full_name = target_user.full_name
    except:
        username = "Unknown"
        user_full_name = f"User {target_user_id}"
    success = db.ban_user(target_user_id, user.id, reason)
    if success:
        await update.message.reply_text(
            f"✅ **User banned successfully!**\n\n"
            f"👤 **User:** {user_full_name}\n"
            f"🆔 **ID:** `{target_user_id}`\n"
            f"🚫 **Reason:** {reason}\n"
            f"👑 **Banned by:** {user.first_name}\n\n"
            f"This user can no longer upload content.",
            parse_mode=ParseMode.MARKDOWN
        )
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"🚫 **Account Banned**\n\n"
                     f"Your account has been banned from uploading content.\n\n"
                     f"**Reason:** {reason}\n"
                     f"**Banned by:** Admin\n\n"
                     f"If you believe this is a mistake, contact the administrator.",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass
    else:
        await update.message.reply_text("❌ Failed to ban user. Please try again.", parse_mode=ParseMode.MARKDOWN)

@admin_only
async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args and not update.message.reply_to_message:
        await update.message.reply_text(
            "✅ **Unban User**\n\n"
            "Usage: `/unban <user_id>`\n"
            "Or reply to a message with `/unban`\n\n"
            "Examples:\n"
            "• `/unban 123456789`\n"
            "• Reply to message: `/unban`\n\n"
            "Unbanned users can upload content again.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    user = update.effective_user
    target_user_id = None
    if update.message.reply_to_message:
        target_user_id = update.message.reply_to_message.from_user.id
    else:
        try:
            target_user_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. User ID must be a number.", parse_mode=ParseMode.MARKDOWN)
            return
    if not target_user_id:
        await update.message.reply_text("❌ Could not identify user to unban.", parse_mode=ParseMode.MARKDOWN)
        return
    if not db.is_user_banned(target_user_id):
        await update.message.reply_text(f"ℹ️ User `{target_user_id}` is not currently banned.", parse_mode=ParseMode.MARKDOWN)
        return
    success = db.unban_user(target_user_id)
    if success:
        await update.message.reply_text(
            f"✅ **User unbanned successfully!**\n\n"
            f"🆔 **User ID:** `{target_user_id}`\n"
            f"👑 **Unbanned by:** {user.first_name}\n\n"
            f"This user can now upload content again.",
            parse_mode=ParseMode.MARKDOWN
        )
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text="✅ **Account Unbanned**\n\n"
                     "Your account has been unbanned.\n"
                     "You can now upload content again.",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass
    else:
        await update.message.reply_text("❌ Failed to unban user. Please try again.", parse_mode=ParseMode.MARKDOWN)

@admin_only
async def banned_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        banned_users = db.get_banned_users()
        if not banned_users:
            await update.message.reply_text(
                "✅ **No banned users found.**\n\n"
                "All users are currently allowed to upload content.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        banned_list_msg = "🚫 **Banned Users List**\n\n"
        for i, banned_user in enumerate(banned_users, 1):
            user_id = banned_user['user_id']
            username = banned_user.get('username') or "No username"
            ban_reason = banned_user.get('ban_reason') or "No reason"
            banned_by = banned_user.get('banned_by') or "Unknown"
            ban_date = banned_user.get('ban_date')
            if isinstance(ban_date, datetime):
                ban_date_display = ban_date.strftime('%Y-%m-%d %H:%M:%S')
            else:
                ban_date_display = str(ban_date) if ban_date else "Unknown"
            banned_list_msg += (
                f"{i}. **User ID:** `{user_id}`\n"
                f"   **Username:** @{username}\n"
                f"   **Reason:** {ban_reason}\n"
                f"   **Banned by:** {banned_by}\n"
                f"   **Date:** {ban_date_display}\n\n"
            )
        banned_list_msg += f"**Total banned users:** {len(banned_users)}"
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh List", callback_data="refresh_banned_list")],
            [InlineKeyboardButton("🗑️ Clear All Bans", callback_data="clear_all_bans_confirm")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(banned_list_msg, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error in banned command: {e}")
        await update.message.reply_text("❌ An error occurred while fetching banned users list.", parse_mode=ParseMode.MARKDOWN)

@admin_only
async def find_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "🔎 **Usage:** `/find <user_id>`\n\n"
            "Example: `/find 123456789`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. Must be a number.")
        return

    user_data = db.get_user(target_id)
    if not user_data:
        await update.message.reply_text("❌ User not found in database.")
        return

    earnings = db.get_user_earnings_summary(target_id)
    payment = db.get_user_payment(target_id)
    contents = db.get_user_contents(target_id)
    content_stats = db.get_content_stats_by_user(target_id)
    ban_status = db.is_user_banned(target_id)

    payment_info = "Not set"
    if payment:
        method = payment['payment_method']
        details = payment['payment_details']
        masked = details[-4:] if len(details) > 4 else details
        payment_info = f"{method} - ...{masked}"

    channel_status = "✅ Verified" if user_data.get('has_joined_all_channels') else "❌ Not verified"

    ban_info = "✅ Active"
    if ban_status:
        ban_info = (
            f"🚫 **BANNED**\n"
            f"   **Reason:** {escape_md(user_data.get('ban_reason', 'No reason'))}\n"
            f"   **Date:** {escape_md(str(user_data.get('ban_date', 'Unknown')))}\n"
            f"   **Banned by:** `{escape_md(str(user_data.get('banned_by', 'Unknown')))}`"
        )

    content_breakdown = ""
    for ctype in ContentType:
        count = content_stats.get(ctype.value, 0)
        if count > 0:
            emoji = {'file':'📄','video':'🎬','audio':'🎵','photo':'🖼','text':'📝','batch':'📦'}.get(ctype.value,'📁')
            content_breakdown += f"   {emoji} {ctype.value.title()}: {count}\n"

    recent_ids = [c['content_id'] for c in contents[:5]]

    # withdrawal stats
    pipeline = [
        {"$match": {"user_id": target_id}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}}
    ]
    withdraw_stats = {doc["_id"]: doc["count"] for doc in withdrawals_col.aggregate(pipeline)}
    total_withdrawals = sum(withdraw_stats.values())

    pending_w = withdraw_stats.get('pending', 0)
    completed_w = withdraw_stats.get('completed', 0)
    rejected_w = withdraw_stats.get('rejected', 0)

    msg = (
        f"🔎 **ADMIN USER INSPECTION PANEL**\n\n"
        f"👤 **Basic Info**\n"
        f"   🆔 **User ID:** `{target_id}`\n"
        f"   👤 **Username:** @{escape_md(user_data.get('username', 'N/A'))}\n"
        f"   📅 **Join Date:** {escape_md(str(user_data.get('join_date', 'N/A')))}\n"
        f"   📢 **Channel Status:** {channel_status}\n"
        f"   🚫 **Ban Status:** {ban_info}\n\n"
        f"💰 **Earnings**\n"
        f"   💵 **Total Balance:** `${earnings.get('balance',0):.2f}`\n"
        f"   • Referral: `${earnings.get('referral_earnings',0):.2f}`\n"
        f"   • View: `${earnings.get('view_earnings',0):.2f}`\n"
        f"   • Total Earnings: `${earnings.get('total_earnings',0):.2f}`\n"
        f"   • Total Withdrawn: `${earnings.get('total_withdrawn',0):.2f}`\n"
        f"   👥 **Referrals:** {earnings.get('total_referrals',0)}\n"
        f"   👁 **Paid Views:** {earnings.get('total_views',0)}\n\n"
        f"📤 **Content**\n"
        f"   📈 **Total Uploads:** {len(contents)}\n"
        f"{content_breakdown}"
        f"   **Recent Content IDs:**\n"
    )
    if recent_ids:
        for cid in recent_ids:
            msg += f"      • `{cid}`\n"
    else:
        msg += "      No uploads\n"

    msg += (
        f"\n💳 **Payment Method**\n"
        f"   `{payment_info}`\n\n"
        f"🏦 **Withdrawal History**\n"
        f"   **Total Requests:** {total_withdrawals}\n"
        f"   ⏳ Pending: {pending_w}\n"
        f"   ✅ Completed: {completed_w}\n"
        f"   ❌ Rejected: {rejected_w}"
    )

    keyboard = []
    if ban_status:
        keyboard.append([InlineKeyboardButton("🟢 Unban User", callback_data=f"admin_unban_{target_id}")])
    else:
        keyboard.append([InlineKeyboardButton("🔴 Ban User", callback_data=f"admin_ban_{target_id}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def handle_admin_user_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if user.id not in ADMIN_IDS:
        await query.answer("⛔ Admin only!", show_alert=True)
        return

    data = query.data
    if not (data.startswith("admin_ban_") or data.startswith("admin_unban_")):
        return

    parts = data.split("_")
    action = parts[1]  # "ban" or "unban"
    target_id = int(parts[2])

    if action == "ban":
        reason = "Banned via admin panel"
        success = db.ban_user(target_id, user.id, reason)
        if success:
            await query.edit_message_text(
                f"✅ User `{target_id}` has been **banned**.\n\n"
                f"Use `/find {target_id}` to see updated info.",
                parse_mode=ParseMode.MARKDOWN
            )
            try:
                await context.bot.send_message(
                    target_id,
                    "🚫 **Account Banned**\n\n"
                    "Your account has been restricted from uploading content.\n"
                    f"Reason: {reason}"
                )
            except Exception:
                pass
        else:
            await query.edit_message_text(f"❌ Failed to ban user `{target_id}`.", parse_mode=ParseMode.MARKDOWN)

    elif action == "unban":
        success = db.unban_user(target_id)
        if success:
            await query.edit_message_text(
                f"✅ User `{target_id}` has been **unbanned**.\n\n"
                f"Use `/find {target_id}` to see updated info.",
                parse_mode=ParseMode.MARKDOWN
            )
            try:
                await context.bot.send_message(
                    target_id,
                    "✅ **Account Unbanned**\n\n"
                    "You can now upload content again."
                )
            except Exception:
                pass
        else:
            await query.edit_message_text(f"❌ Failed to unban user `{target_id}`.", parse_mode=ParseMode.MARKDOWN)

# ========================
# MENU KEYBOARD BUILDERS
# ========================
def main_menu_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        ["📤 Upload", "📥 Get File"],
        ["👤 Profile", "💰 Earnings"],
        ["⚙ Settings", "❓ Help"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def earnings_menu_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        ["💰 Balance", "👥 Referrals"],
        ["💳 Withdraw"],
        ["🔙 Back"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def settings_menu_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        ["💳 Payment Method"],
        ["🌐 Language"],
        ["🔙 Back"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ========================
# UPLOAD PROGRESS FUNCTIONS
# ========================
async def show_upload_progress(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> Message:
    msg = await context.bot.send_message(chat_id, "📤 Uploading Content...\n\n▓░░░░░░░░░ 10%")
    return msg

async def upload_progress_task(context: ContextTypes.DEFAULT_TYPE, message: Message):
    steps = [20, 30, 40, 50, 60, 70, 80, 90, 100]
    for percent in steps:
        if not context.user_data.get('upload_in_progress', False):
            break
        try:
            bar = '▓' * (percent // 10) + '░' * (10 - percent // 10)
            await message.edit_text(f"📤 Uploading Content...\n\n{bar} {percent}%")
        except:
            pass
        await asyncio.sleep(0.5)

# ========================
# BALANCE COMMAND
# ========================
async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if await check_maintenance(update, context):
        return
    if user.id not in ADMIN_IDS and await require_channel_join(update, context):
        return
    balance = db.get_user_balance(user.id)
    await update.message.reply_text(
        f"💰 **Your Balance**\n\n"
        f"💵 **Available Balance:** `${balance:.4f}`\n\n"
        f"Use /withdraw to cash out.",
        parse_mode=ParseMode.MARKDOWN
    )

# ========================
# ADMIN SETMOD COMMAND
# ========================
@admin_only
async def setmod_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global UPLOAD_MODE
    if not context.args:
        await update.message.reply_text(f"Current upload mode: {UPLOAD_MODE}\nUsage: /setmod private|public")
        return
    mode = context.args[0].lower()
    if mode not in ("private", "public"):
        await update.message.reply_text("Invalid mode. Use 'private' or 'public'.")
        return
    UPLOAD_MODE = mode
    await update.message.reply_text(f"✅ Upload mode set to {mode.upper()}")

# ========================
# CALLBACK QUERY HANDLER
# ========================
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    await query.answer()

    data = query.data

    if data == "protection_protected":
        if 'pending_batch' in context.user_data:
            await complete_batch_upload(update, context, protection_mode='protected')
            return
        elif 'pending_upload' in context.user_data:
            content_data = context.user_data['pending_upload']
            content_data['protection_mode'] = 'protected'
            await complete_upload(update, context, content_data)
            return
        else:
            await query.edit_message_text("❌ Upload session expired. Please send your content again.")
            return

    if data == "protection_unprotected":
        if 'pending_batch' in context.user_data:
            await complete_batch_upload(update, context, protection_mode='unprotected')
            return
        elif 'pending_upload' in context.user_data:
            content_data = context.user_data['pending_upload']
            content_data['protection_mode'] = 'unprotected'
            await complete_upload(update, context, content_data)
            return
        else:
            await query.edit_message_text("❌ Upload session expired. Please send your content again.")
            return

    if data == "cancel_upload":
        context.user_data.pop('pending_upload', None)
        context.user_data.pop('pending_batch', None)
        if context.user_data.get('upload_in_progress'):
            context.user_data['upload_in_progress'] = False
            progress_msg = context.user_data.get('upload_progress_msg')
            if progress_msg:
                try:
                    await progress_msg.edit_text("❌ Upload cancelled.")
                except:
                    pass
        await query.edit_message_text("❌ Upload cancelled. You can send content again anytime.")
        return

    if data.startswith("wd_"):
        await handle_withdrawal_action(update, context)
        return

    if data.startswith("admin_ban_") or data.startswith("admin_unban_"):
        await handle_admin_user_action(update, context)
        return

    if data == "recheck_membership":
        has_joined = await check_channel_membership(user.id, context)
        if has_joined:
            db.update_user_channel_status(user.id, True)
            welcome_msg = (
                f"✅ **Welcome {user.first_name}!**\n\n"
                "You have successfully joined all required channels.\n\n"
                "**Content Sharing Bot**\n\n"
                "📤 **Upload any content:**\n"
                "• Files, Videos, Audio\n"
                "• Photos, Text\n"
                "• **Batch Upload** (use /batch)\n\n"
                "🆔 **Get a unique Content ID**\n"
                "📤 **Share with anyone**\n"
                f"⏰ **Auto-deletes after {AUTO_DELETE_SECONDS//3600} hour(s)**\n\n"
                "**Simply send me any content to get started!**"
            )
            keyboard = [
                [InlineKeyboardButton("📤 Upload Content", callback_data="upload_help")],
                [InlineKeyboardButton("👤 My Profile", callback_data="profile")],
                [InlineKeyboardButton("❓ Help", callback_data="help")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                welcome_msg,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await query.answer(
                "❌ You haven't joined all required channels yet!\n"
                "Please join ALL channels and try again.",
                show_alert=True
            )
        return

    if data == "upload_help":
        await query.edit_message_text(
            "📤 **How to upload content:**\n\n"
            "Simply send me:\n"
            "• Any file (document)\n"
            "• Video\n"
            "• Audio\n"
            "• Photo\n"
            "• Text message\n\n"
            "For multiple files, use /batch to start batch mode, then send files, and finish with /done.\n\n"
            "I'll generate a unique Content ID!",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "profile":
        try:
            earnings = db.get_user_earnings_summary(user.id)
            payment = db.get_user_payment(user.id)
            payment_info = "Not set"
            if payment:
                method = payment['payment_method']
                details = payment['payment_details']
                masked = details[-4:] if len(details) > 4 else details
                payment_info = f"{method} - ...{masked}"

            profile_msg = (
                f"👤 **Your Profile**\n\n"
                f"🆔 **User ID:** `{user.id}`\n"
                f"👤 **Username:** @{escape_md(user.username) or 'Not set'}\n"
                f"💰 **Available Balance:** `${earnings.get('balance',0):.2f}`\n"
                f"💳 **Payment:** `{payment_info}`\n\n"
                f"Use /profile for full details."
            )
            keyboard = [
                [InlineKeyboardButton("💳 Set Payment", callback_data="set_payment")],
                [InlineKeyboardButton("💰 Withdraw", callback_data="withdraw_help")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(profile_msg, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Error in profile callback: {e}")
            await query.edit_message_text("❌ Error loading profile.", parse_mode=ParseMode.MARKDOWN)
        return

    if data == "help":
        help_text = (
            "❓ **Help & Guide**\n\n"
            "**Available Commands:**\n"
            "• `/start` - Start the bot\n"
            "• `/get <id>` - Get content by secret ID\n"
            "• `/profile` - Your profile & earnings\n"
            "• `/delete <id>` - Delete your content\n"
            "• `/withdraw` - Withdraw earnings\n"
            "• `/setpayment` - Set payment method\n"
            "• `/batch` - Start batch upload\n"
            "• `/done` - Finish batch upload\n"
            "• `/help` - This help message\n\n"
            "**Simply send any content to upload it!**"
        )
        await query.edit_message_text(help_text, parse_mode=ParseMode.MARKDOWN)
        return

    if data == "delete_content_help":
        await query.edit_message_text(
            "🗑️ **Delete Content**\n\n"
            "To delete your uploaded content:\n"
            "1. Use `/delete <content_id>`\n"
            "2. You can only delete your own uploads\n"
            "3. Find your Content IDs in your profile\n\n"
            "Example: `/delete abc123xyz456`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data.startswith("view_uploads_"):
        user_id = int(data.split("_")[2])
        if user.id != user_id and user.id not in ADMIN_IDS:
            await query.answer("❌ Access denied!", show_alert=True)
            return
        user_contents = db.get_user_contents(user_id)
        if not user_contents:
            await query.edit_message_text("📭 No uploads found for this user.", parse_mode=ParseMode.MARKDOWN)
            return
        uploads_text = f"📁 **Uploads for User {user_id}**\n\n"
        for i, content in enumerate(user_contents[:20], 1):
            protection_emoji = "🔒" if content.get('protection_mode') == 'protected' else "🔓"
            uploads_text += (
                f"{i}. **ID:** `{content['content_id']}`\n"
                f"   **Type:** {content['content_type']}\n"
                f"   **Protection:** {protection_emoji}\n"
                f"   **Date:** {content['upload_timestamp']}\n\n"
            )
        if len(user_contents) > 20:
            uploads_text += f"... and {len(user_contents) - 20} more"
        await query.edit_message_text(uploads_text, parse_mode=ParseMode.MARKDOWN)
        return

    if data == "set_payment":
        await query.edit_message_text(
            "💳 To set your payment method, use the command:\n/setpayment",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "withdraw_help":
        await query.edit_message_text(
            "💰 To withdraw your earnings, use:\n`/withdraw <amount>`\n\n"
            "First set your payment method with `/setpayment`.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "refresh_banned_list":
        if user.id not in ADMIN_IDS:
            await query.answer("❌ Admin only!", show_alert=True)
            return
        banned_users = db.get_banned_users()
        if not banned_users:
            await query.edit_message_text("✅ **No banned users found.**\n\nAll users are currently allowed to upload content.", parse_mode=ParseMode.MARKDOWN)
            return
        banned_list_msg = "🚫 **Banned Users List**\n\n"
        for i, banned_user in enumerate(banned_users, 1):
            user_id = banned_user['user_id']
            username = banned_user.get('username') or "No username"
            ban_reason = banned_user.get('ban_reason') or "No reason"
            banned_by = banned_user.get('banned_by') or "Unknown"
            ban_date = banned_user.get('ban_date')
            if isinstance(ban_date, datetime):
                ban_date_display = ban_date.strftime('%Y-%m-%d %H:%M:%S')
            else:
                ban_date_display = str(ban_date) if ban_date else "Unknown"
            banned_list_msg += (
                f"{i}. **User ID:** `{user_id}`\n"
                f"   **Username:** @{username}\n"
                f"   **Reason:** {ban_reason}\n"
                f"   **Banned by:** {banned_by}\n"
                f"   **Date:** {ban_date_display}\n\n"
            )
        banned_list_msg += f"**Total banned users:** {len(banned_users)}"
        await query.edit_message_text(banned_list_msg, parse_mode=ParseMode.MARKDOWN)
        await query.answer("✅ List refreshed!", show_alert=False)
        return

    if data == "clear_all_bans_confirm":
        if user.id not in ADMIN_IDS:
            await query.answer("❌ Admin only!", show_alert=True)
            return
        banned_users = db.get_banned_users()
        total_banned = len(banned_users)
        if total_banned == 0:
            await query.answer("No banned users to clear!", show_alert=True)
            return
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, Clear All", callback_data="clear_all_bans"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_clear_bans")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"⚠️ **Confirm Clear All Bans**\n\n"
            f"Are you sure you want to unban ALL {total_banned} users?\n\n"
            f"This action cannot be undone!",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "clear_all_bans":
        if user.id not in ADMIN_IDS:
            await query.answer("❌ Admin only!", show_alert=True)
            return
        banned_users = db.get_banned_users()
        total_banned = len(banned_users)
        if total_banned == 0:
            await query.edit_message_text("✅ No banned users to clear.", parse_mode=ParseMode.MARKDOWN)
            return
        success_count = 0
        for banned_user in banned_users:
            if db.unban_user(banned_user['user_id']):
                success_count += 1
        await query.edit_message_text(
            f"✅ **All bans cleared successfully!**\n\n"
            f"**Total unbanned:** {success_count}/{total_banned}\n\n"
            f"All users can now upload content again.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "cancel_clear_bans":
        if user.id not in ADMIN_IDS:
            await query.answer("❌ Admin only!", show_alert=True)
            return
        await query.edit_message_text("❌ Operation cancelled.\n\nNo bans were cleared.", parse_mode=ParseMode.MARKDOWN)
        return

# ========================
# MESSAGE HANDLER FOR MENU BUTTONS
# ========================
async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user

    if text == "📤 Upload":
        await update.message.reply_text("📤 Send me the file, video, audio, photo, or text you want to upload.")
        return
    elif text == "📥 Get File":
        context.user_data["awaiting_secret"] = True
        await update.message.reply_text("🔑 Please send the Secret ID.")
        return
    elif text == "👤 Profile":
        context.args = []
        await profile_command(update, context)
        return
    elif text == "💰 Earnings":
        await update.message.reply_text(
            "💰 **Earnings Menu**\n\nSelect an option:",
            reply_markup=earnings_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    elif text == "⚙ Settings":
        await update.message.reply_text(
            "⚙ **Settings Menu**\n\nSelect an option:",
            reply_markup=settings_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    elif text == "🔙 Back":
        await update.message.reply_text(
            "🔙 Main Menu",
            reply_markup=main_menu_keyboard()
        )
        return
    elif text == "💰 Balance":
        await balance_command(update, context)
        return
    elif text == "👥 Referrals":
        await update.message.reply_text(
            f"♻️Your referral link:\n"
            f"https://t.me/{(await context.bot.get_me()).username}?start={user.id}\n\n"
            f"You earn ${float(db.get_setting('referral_reward','0.01')):.2f} per new user who joins via your link and verifies."
        )
        return
    elif text == "💳 Withdraw":
        await withdraw_command(update, context)
        return
    elif text == "💳 Payment Method":
        await setpayment_start(update, context)
        return
    elif text == "🌐 Language":
        await update.message.reply_text("🌐 Only English Language Is Available.")
        return
    elif text == "❓ Help":
        await help_command(update, context)
        return
    else:
        if context.user_data.get("awaiting_secret"):
            content_id = text.strip()
            context.args = [content_id]
            await get_content_command(update, context)
            context.user_data["awaiting_secret"] = False
            return
        await handle_upload(update, context)

# ========================
# MESSAGE HANDLER
# ========================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_maintenance(update, context):
        return
    if await check_ban_status(update, context):
        return

    user = update.effective_user
    if user.id not in ADMIN_IDS:
        if await require_channel_join(update, context):
            return

    if update.message and update.message.text and update.message.text.startswith('/'):
        return

    if update.message and update.message.text:
        text = update.message.text.strip()
        if context.user_data.get("awaiting_secret"):
            if re.match(r'^[a-zA-Z0-9_\-]{8,25}$', text):
                context.args = [text]
                context.user_data["awaiting_secret"] = False
                await get_content_command(update, context)
                return
            else:
                await update.message.reply_text("❌ Invalid Secret ID format. Please try again.")
                return
        else:
            if re.match(r'^[a-zA-Z0-9_\-]{8,25}$', text):
                context.args = [text]
                await get_content_command(update, context)
                return

    await handle_upload(update, context)

# ========================
# MAIN APPLICATION (FIXED)
# ========================
def main():
    print("=" * 50)
    print("🤖 Starting Advanced Content Bot (MongoDB Atlas)...")
    print(f"📱 Bot Token: {BOT_TOKEN[:10]}...")
    print(f"👑 Admins: {len(ADMIN_IDS)}")
    print(f"📢 Force Join Channels: {len(FORCE_JOIN_CHANNELS)}")
    print(f"🔒 Backup Channel: {BACKUP_CHANNEL_ID}")
    print(f"💾 Database: MongoDB Atlas -> {client.address}")
    print(f"⏰ Auto-delete: {AUTO_DELETE_SECONDS // 3600} hour(s)")
    print("=" * 50)

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("get", get_content_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("delete", delete_content_command))
    application.add_handler(CommandHandler("withdraw", withdraw_command))
    application.add_handler(CommandHandler("batch", batch_command))
    application.add_handler(CommandHandler("done", done_command))

    payment_conv = ConversationHandler(
        entry_points=[CommandHandler("setpayment", setpayment_start)],
        states={
            SET_PAYMENT_METHOD: [CallbackQueryHandler(setpayment_method, pattern=r"^pay_")],
            SET_PAYMENT_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, setpayment_details)]
        },
        fallbacks=[CommandHandler("cancel", setpayment_cancel),
                   CallbackQueryHandler(setpayment_cancel, pattern="pay_cancel")],
        allow_reentry=True
    )
    application.add_handler(payment_conv)

    application.add_handler(CommandHandler("upload", handle_upload))
    application.add_handler(CommandHandler("maintenance", maintenance_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("adms", broadcast_command))
    application.add_handler(CommandHandler("settime", settime_command))
    application.add_handler(CommandHandler("ban", ban_command))
    application.add_handler(CommandHandler("unban", unban_command))
    application.add_handler(CommandHandler("banned", banned_command))
    application.add_handler(CommandHandler("withdrawals", withdrawals_command))
    application.add_handler(CommandHandler("setreward", setreward_command))
    application.add_handler(CommandHandler("setminwithdraw", setminwithdraw_command))
    application.add_handler(CommandHandler("find", find_command))
    application.add_handler(CommandHandler("setmod", setmod_command))

    menu_options = [
        "📤 Upload", "📥 Get File", "👤 Profile", "💰 Earnings",
        "💳 Withdraw", "👥 Referrals", "⚙ Settings", "❓ Help",
        "💰 Balance", "💳 Payment Method", "🌐 Language", "🔙 Back"
    ]
    application.add_handler(MessageHandler(filters.Text(menu_options), handle_menu_buttons))

    application.add_handler(MessageHandler(
        filters.TEXT | filters.PHOTO | filters.VIDEO |
        filters.AUDIO | filters.Document.ALL,
        handle_message
    ))

    application.add_handler(CallbackQueryHandler(handle_callback_query))

    async def post_init(app: Application):
        await set_command_scopes(app)
    application.post_init = post_init

    print("✅ Bot started successfully!")
    print("📡 Listening for updates...")
    application.run_polling()

if __name__ == '__main__':
    main()