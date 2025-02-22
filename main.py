from firebase_db import save_subscription, load_subscriptions, remove_expired_subscriptions
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import BadRequest
from datetime import datetime, timedelta
import json
import os
from apscheduler.schedulers.background import BackgroundScheduler
import asyncio

# from keep_alive import keep_alive
# keep_alive()

from dotenv import load_dotenv
load_dotenv()


TOKEN = os.getenv('TOKEN')
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID'))
PRIVATE_CHANNEL_ID = int(os.getenv('PRIVATE_CHANNEL_ID'))
MSG_DELETE_TIME = int(os.getenv('MSG_DELETE_TIME'))  # Default to 0 if not set
# The number of members needed to trigger the reward
PAYMENT_URL = os.getenv('PAYMENT_URL')
canva_url = os.getenv('canva_url')
PAYPAL_API_BASE = os.getenv('PAYPAL_API_BASE')
PAYPAL_CLIENT_ID = os.getenv('PAYPAL_CLIENT_ID')
PAYPAL_SECRET = os.getenv('PAYPAL_SECRET')
PAYMENT_CAPTURED_DETAILS_URL = os.getenv('PAYMENT_CAPTURED_DETAILS_URL')

subscription_data = {}
user_data = {}
codes_data = {}
CODES_FILE = "codes.json"
payment_status = False


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

message = '''
🔰<b>Get Canva Pro at Unbeatable Prices!</b>🔰

Welcome to Canva Pro Bot😃 🚀

 🌐Fully Automated: Make the payment and get instant access—no need to contact anyone!

<b>📚How to buy Canva Pro using this bot:</b>
1️⃣ Start the Bot 🤖
2️⃣ Click on "Make Payment for Canva Pro"
3️⃣ Choose your subscription plan
4️⃣ Join our Premium Channel
5️⃣ Open the app or type /check from the menu
6️⃣ Click "Access Canva Pro Link"
7️⃣ Sign In or Sign Up to your Canva account
8️⃣ You're now a member of the Edu Team Panel! 🎉

For assistance, feel free to contact us at @coding_services.
'''

indian_plan = """
<b>We offer two flexible plans to fit your needs:</b>

✅ Monthly Plan – Rs 69/-
✅ Annual Plan – Rs 299/-
"""

non_indian_plan = """
<b>We offer two flexible plans to fit your needs:</b>

✅ Monthly Plan – $2
✅ Annual Plan   – $6 
"""

# ------------------ fetching Payment details made by user------------------ #
def fetch_payment_details(chat_id,payment_amount):
    response = requests.get(url=PAYMENT_CAPTURED_DETAILS_URL)
    try:
        response.raise_for_status()
        data = response.json()
        for entry in data:
            if entry['user_Id'] == chat_id:
                if entry['amount'] == str(payment_amount):
                    return entry
        # print("No payment details found! ")
    except requests.exceptions.HTTPError as err:
        print("HTTP Error:", err)

# ------------------ Periodic Task: Check Expired Subscriptions ------------------ #
async def check_expired_subscriptions(context: ContextTypes.DEFAULT_TYPE):
    remove_expired_subscriptions()  # Remove expired entries from Firestore
    subscription_data = load_subscriptions()  # Refresh from Firebase
    now = datetime.now()
    expired_users = []
    for chat_id, details in list(subscription_data.items()):
        expiry_value = details["expiry"]
        if isinstance(expiry_value, str):
            expiry_date = datetime.strptime(expiry_value, "%Y-%m-%d %H:%M:%S")
        else:
            expiry_date = expiry_value
        if expiry_date < now:
            try:
                await context.bot.ban_chat_member(PRIVATE_CHANNEL_ID, chat_id, until_date=now)
                await context.bot.unban_chat_member(PRIVATE_CHANNEL_ID, chat_id)
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"<b>🔰SUBSCRIPTION EXPIRED🔰</b>\n\n"
                         f"📌 <a href='tg://user?id={chat_id}'>{subscription_data[chat_id]['name']}</a> "
                         f"removed from Shared Instructor Bot channel.",
                    parse_mode="HTML"
                )
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="<b>🔰SUBSCRIPTION EXPIRED🔰</b>\n\nPlz, type /start command to make the payment",
                    parse_mode="HTML"
                )
                logger.info(f"Removed expired user {chat_id} from the private channel.")
            except Exception as e:
                logger.error(f"Failed to remove/unban user {chat_id}: {e}")
            expired_users.append(chat_id)
    for chat_id in expired_users:
        del subscription_data[chat_id]


# PayPal API utility functions
def get_paypal_access_token():
    url = f"{PAYPAL_API_BASE}/v1/oauth2/token"
    headers = {"Accept": "application/json", "Accept-Language": "en_US"}
    data = {"grant_type": "client_credentials"}
    response = requests.post(url, headers=headers, data=data, auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET))
    response.raise_for_status()
    return response.json()["access_token"]


def create_paypal_payment(amount):
    access_token = get_paypal_access_token()
    url = f"{PAYPAL_API_BASE}/v2/checkout/orders"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
    data = {
        "intent": "CAPTURE",
        "purchase_units": [{"amount": {"currency_code": "USD", "value": f"{amount:.2f}"}}],
        "application_context": {
            "return_url": "https://codingservices2020.github.io/Checkout-Page/",
            "cancel_url": "https://t.me/Testing233535Bot"
        }
    }
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    order = response.json()
    approve_url = next(link["href"] for link in order["links"] if link["rel"] == "approve")
    return order["id"], approve_url


def capture_payment(order_id):
    access_token = get_paypal_access_token()
    url = f"{PAYPAL_API_BASE}/v2/checkout/orders/{order_id}/capture"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
    response = requests.post(url, headers=headers)
    response.raise_for_status()
    return response.json()

# Function to delete a specific message
async def delete_message(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    chat_id = job_data['chat_id']
    message_id = job_data['message_id']
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Message {message_id} deleted successfully in chat {chat_id}.")
    except Exception as e:
        logger.error(f"Failed to delete message {message_id} in chat {chat_id}: {e}")

# Modify the `start` function to schedule message deletion
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Determine the source of the request (message or callback query)
        if update.message:
            user_id = update.message.from_user.id
            chat_id = update.message.chat.id
        elif update.callback_query:
            user_id = update.callback_query.from_user.id
            chat_id = update.callback_query.message.chat.id
            await update.callback_query.answer()  # Acknowledge the callback query
        else:
            raise AttributeError("Unable to determine the context of the request.")

        # Check if the user is a member of the private channel
        chat_member = await context.bot.get_chat_member(PRIVATE_CHANNEL_ID, user_id)
        is_premium = chat_member.status in ["member", "administrator", "creator"]

        button_text = "Access Canva Pro Link" if is_premium else "Click here to Buy"
        button = InlineKeyboardButton(
            button_text,
            web_app=WebAppInfo(url=canva_url) if is_premium else None,
            callback_data="buy_canva_pro" if not is_premium else None,
        )

        keyboard = [[button]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if is_premium:
            sent_message = await context.bot.send_message(
                chat_id,
                "You are already a premium member! Click the button below to access the Canva Pro joining link:",
                reply_markup=reply_markup,
            )
            # Schedule the message deletion after MSG_DELETE_TIME
            context.job_queue.run_once(
                delete_message,
                when=MSG_DELETE_TIME,  # MSG_DELETE_TIME in seconds
                data={"chat_id": chat_id, "message_id": sent_message.message_id},
            )
        else:
            await context.bot.send_message(
                chat_id,
                message,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
    except BadRequest as e:
        logger.error(f"BadRequest Error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {type(e).__name__} - {e}")

async def buy_canva_pro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("For Indian Customers 🇮🇳", callback_data="india")],
        [InlineKeyboardButton("For Non-Indian Customers", callback_data="non_india")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "Please select an option based on your country or region. This will help us provide you with payment methods suitable for your location.",
        reply_markup=reply_markup
    )


async def handle_customer_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id

    # Initialize user data for the chat ID if not already present
    if chat_id not in user_data:
        user_data[chat_id] = {}

    if query.data == "non_india":
        user_data[chat_id]["region"] = "Non-India"
        keyboard = [
            [InlineKeyboardButton("Monthly ($2)", callback_data="monthly")],
            [InlineKeyboardButton("Annual ($6)", callback_data="annual")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(non_indian_plan, reply_markup=reply_markup, parse_mode="HTML")
    else:
        user_data[chat_id]["region"] = "India"
        keyboard = [
            [InlineKeyboardButton("Monthly (Rs 69/-)", callback_data="monthly")],
            [InlineKeyboardButton("Annual (Rs 299/-)", callback_data="annual")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(chat_id, indian_plan, reply_markup=reply_markup, parse_mode="HTML")



async def handle_plan_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    choice = query.data
    if user_data[chat_id]["region"] == "Non-India":
        amount = 2.00 if choice == "monthly" else 6.00
    else:
        amount = 69.00 if choice == "monthly" else 299.00
    user_data[chat_id]["amount"] = amount
    user_data[chat_id]["plan"] = "Monthly" if choice == "monthly" else "Annual"

    sent_message = await query.edit_message_text(f"Creating an invoice for {user_data[chat_id]['plan']} Plan. Please wait...")
    context.job_queue.run_once(
        delete_message,
        when=MSG_DELETE_TIME,  # MSG_DELETE_TIME in seconds
        data={"chat_id": chat_id, "message_id": sent_message.message_id},
    )

    if user_data[chat_id]["region"] == "Non-India":
        order_id, approve_url = create_paypal_payment(amount)
        user_data[chat_id]["order_id"] = order_id
    URL = approve_url if user_data[chat_id]["region"] == "Non-India" else PAYMENT_URL
    keyboard = [
        # [InlineKeyboardButton("Pay Now", web_app=WebAppInfo(url=URL))],
        [InlineKeyboardButton("Pay Now", url=URL)],
        [InlineKeyboardButton("Verify Payment", callback_data="verify_payment")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id, f"*🔰STEPS🔰*\n\n"
                                            f"1️⃣ First click on <b>Pay Now</b> button, to make the payment.\n"
                                            f"2️⃣ After making payment, you have to click on *Verify Payment* "
                                            f"button to verfity your payment and wait for few seconds. \n\n"
                                            f"*Your User ID*: `{chat_id}`\n",
                                   reply_markup=reply_markup, parse_mode="Markdown")



async def verify_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global payment_status
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    sent_message = await query.edit_message_text(f"Payment verifying. Please wait...")
    # Schedule the message deletion after MSG_DELETE_TIME
    context.job_queue.run_once(
        delete_message,
        when=MSG_DELETE_TIME,  # MSG_DELETE_TIME in seconds
        data={"chat_id": chat_id, "message_id": sent_message.message_id},
    )
    amount = int(user_data[chat_id]["amount"])
    if user_data[chat_id]["region"] == "Non-India":
        # Check if an order exists
        if "order_id" not in user_data[chat_id]:
            await query.edit_message_text("No payment found. Please start over.")
            return
        order_id = user_data[chat_id]["order_id"]
        try:

            # Verify the payment
            payment_result = capture_payment(order_id)
            if payment_result["status"] == "COMPLETED":
                user_name = payment_result['purchase_units'][0]['shipping']['name']['full_name']
                user_email = payment_result['payer']['email_address']
                payment_status = True
        except requests.exceptions.HTTPError as e:
            await query.edit_message_text(f"Payment not completed. Please try again.")
    else:
        try:
            # Verify the payment
            print(f"chat_id: {chat_id}, data type: {type(chat_id)}")
            user_id = str(chat_id)
            payment_details = fetch_payment_details(user_id, amount)

            print(payment_details)
            if payment_details:
                payment_status = True
                user_name = payment_details['name']
                user_email = payment_details.get('email', "Unknown")  # Get email, default to "Unknown"
                user_mobile = payment_details.get('mobile', "Unknown")  # Get mobile, default to "Unknown"
                paid_amount = int(payment_details['amount'])
        except requests.exceptions.HTTPError as e:
            await query.edit_message_text(f"Payment not completed. Please try again.")

    if payment_status:
        expiry_date = datetime.now() + timedelta(days=30 if user_data[chat_id]["plan"] == "Monthly" else 365)
        day = expiry_date.strftime("%Y-%m-%d")
        time_str = expiry_date.strftime("%H:%M")
        plan = user_data[chat_id]["plan"]
        # Save to Firestore with real email & mobile
        if user_data[chat_id]["region"] == "Non-India":
            currency = "USD"
            save_subscription(chat_id,amount, plan, expiry_date, currency, name=user_name, email=user_email)
        else:
            currency = "INR"
            save_subscription(chat_id,amount, plan, expiry_date, currency,name=user_name, email=user_email, mobile=user_mobile)
            DELETED_CODES_URL = f"{PAYMENT_CAPTURED_DETAILS_URL}/amount/{paid_amount}"
            requests.delete(url=DELETED_CODES_URL)

        logger.info(f"User {chat_id} subscribed to {user_data[chat_id]['plan']} plan until {expiry_date}.")

        try:
            # Generate an invite link for the private channel that expires after one use
            invite_link = await context.bot.create_chat_invite_link(
                PRIVATE_CHANNEL_ID,
                member_limit=1  # The link will expire after one use
            )
        except Exception as e:
            logger.error(f"Failed to generate/send invite link: {e}")

        keyboard = [
            [
                InlineKeyboardButton(
                    "Click here after joining channel",
                    callback_data="is_premium_member"
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id,
            f"<b>🔰PAYMENT VERIFIED🔰</b>\n\n"
                    f"🙏Thank you for making the payment.\n\n"
                    f"🚀 Here is your premium member invite link:\n{invite_link.invite_link}\n"
                    f"<b>(Valid for one-time use)</b>\n\n"
                    f"✅ After joining this channel, type /start or click on the button below to access the Canva Pro account.\n\n"
                    f"<b>🌐 Your plan will expire on {day} at {time_str}.</b>",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        logger.info(f"Invite link sent to user {query.from_user.id}.")
        # Notify admin that this user has successfully generated the channel invite link.
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"<b>🔰SUBSCRIPTION PURCHASED🔰</b>\n\n"
                 f"<b>Name:</b> <a href='tg://user?id={chat_id}'>{user_name}</a>\n"
                 f"<b>Email:</b> {user_email}\n"
                 f"<b>User ID:</b> {chat_id}\n"
                 f"<b>Expiry:</b> {day} at {time_str}",
            parse_mode="HTML"
        )
        context.job_queue.run_once(delete_message, 0, data=(sent_message.chat.id, sent_message.message_id))
    else:
        await query.edit_message_text("Payment not completed. Please try again.")


# Handle verification command
async def is_premium_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Determine if the request is from a callback query or a command
        if update.message:
            user_id = update.message.from_user.id
            chat_id = update.message.chat.id
        elif update.callback_query:
            user_id = update.callback_query.from_user.id
            chat_id = update.callback_query.message.chat.id
            await update.callback_query.answer()  # Acknowledge the callback query
        else:
            raise AttributeError("Unable to determine the context of the request.")

        # Check if the user is a member of the private channel
        chat_member = await context.bot.get_chat_member(PRIVATE_CHANNEL_ID, user_id)
        is_premium = chat_member.status in ["member", "administrator", "creator"]

        button_text = (
            "Access Canva Pro Link" if is_premium else "Make Payment for Canva Pro"
        )

        # Use WebAppInfo for Canva URL and regular URL for the payment link
        button = InlineKeyboardButton(
            button_text,
            web_app=WebAppInfo(url=canva_url) if is_premium else None,
            callback_data="start" if not is_premium else None,
        )

        keyboard = [[button]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if is_premium:
            sent_message = await context.bot.send_message(
                chat_id,
                "You are a premium member! Click the button below to access the Canva Pro joining link:",
                reply_markup=reply_markup,
            )
            # Schedule the message deletion after MSG_DELETE_TIME
            context.job_queue.run_once(
                delete_message,
                when=MSG_DELETE_TIME,  # MSG_DELETE_TIME in seconds
                data={"chat_id": chat_id, "message_id": sent_message.message_id},
            )
        else:
            await context.bot.send_message(
                chat_id,
                "You are not a premium member. You need to first make payment for the Canva Pro.",
                reply_markup=reply_markup,
            )
    except BadRequest as e:
        logger.error(f"BadRequest Error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {type(e).__name__} - {e}")


# Help command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        """
    Commands available:
    /start - Start the bot and buy Canva Pro
    /check - Check Canva Pro Subscription
    /help - Show this help message
    """
    )


def main():
    application = Application.builder().token(TOKEN).build()

    # Load subscription data on startup
    global subscription_data
    subscription_data = load_subscriptions()  # Load from Firebase

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(start, pattern="^start$"))
    application.add_handler(CallbackQueryHandler(buy_canva_pro, pattern="^buy_canva_pro$"))
    application.add_handler(CallbackQueryHandler(handle_customer_choice, pattern="^(india|non_india)$"))
    application.add_handler(CallbackQueryHandler(handle_plan_selection, pattern="^(monthly|annual)$"))
    application.add_handler(CallbackQueryHandler(verify_payment, pattern="^verify_payment$"))
    application.add_handler(CallbackQueryHandler(is_premium_member, pattern="^is_premium_member$"))
    application.add_handler(CommandHandler("check", is_premium_member))
    application.add_handler(CommandHandler("help", help_command))

    # Add periodic job to check expired subscriptions
    scheduler = BackgroundScheduler(timezone="UTC")
    # scheduler.add_job(check_expired_subscriptions, "interval", minutes=1, args=[application])
    scheduler.add_job(
        lambda: asyncio.run(check_expired_subscriptions(application)),
        "interval",
        hours=1
    )
    scheduler.start()

    # Start polling
    application.run_polling()


if __name__ == "__main__":
    main()