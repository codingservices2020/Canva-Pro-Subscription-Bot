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

from keep_alive import keep_alive
keep_alive()

# from dotenv import load_dotenv
# load_dotenv()



TOKEN = os.getenv('TOKEN')
PRIVATE_CHANNEL_ID = int(os.getenv('PRIVATE_CHANNEL_ID'))
MSG_DELETE_TIME = int(os.getenv('MSG_DELETE_TIME'))  # Default to 0 if not set
# The number of members needed to trigger the reward
payment_url = os.getenv('payment_url')
canva_url = os.getenv('canva_url')
PAYPAL_API_BASE = os.getenv('PAYPAL_API_BASE')
PAYPAL_CLIENT_ID = os.getenv('PAYPAL_CLIENT_ID')
PAYPAL_SECRET = os.getenv('PAYPAL_SECRET')




# Store subscription data
subscription_data = {}
# JSON file path
SUBSCRIPTION_FILE = "subscription_data.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Store user data
user_data = {}

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


# Serialize datetime objects to strings when saving to JSON
def save_subscription_data():
    serializable_data = {
        chat_id: {
            "expiry": details["expiry"].strftime("%Y-%m-%d %H:%M:%S"),  # Convert datetime to string
            "plan": details["plan"]
        }
        for chat_id, details in subscription_data.items()
    }
    with open(SUBSCRIPTION_FILE, "w") as file:
        json.dump(serializable_data, file, indent=4)

async def on_shutdown(application):
    save_subscription_data()
    logger.info("Subscription data saved on shutdown.")

def load_subscription_data():
    if os.path.exists(SUBSCRIPTION_FILE):
        try:
            with open(SUBSCRIPTION_FILE, "r") as file:
                data = json.load(file)
                return {
                    chat_id: {
                        "expiry": datetime.strptime(details["expiry"], "%Y-%m-%d %H:%M:%S"),  # Convert string to datetime
                        "plan": details["plan"]
                    }
                    for chat_id, details in data.items()
                }
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Error loading subscription data: {e}. Resetting to an empty dictionary.")
    return {}

# Periodic task to check expired subscriptions
async def check_expired_subscriptions(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    expired_users = []
    for chat_id, details in list(subscription_data.items()):
        expiry_value = details["expiry"]
        if isinstance(expiry_value, str):
            expiry_date = datetime.strptime(expiry_value, "%Y-%m-%d %H:%M:%S")
        else:
            expiry_date = expiry_value
        if expiry_date < now:
            # Remove the user from the private channel
            try:
                await context.bot.ban_chat_member(PRIVATE_CHANNEL_ID, chat_id, until_date=now)  # Ban and then unban
                await context.bot.unban_chat_member(PRIVATE_CHANNEL_ID, chat_id)
                logger.info(f"Removed expired user {chat_id} from the private channel.")
            except Exception as e:
                logger.error(f"Failed to remove/unban user {chat_id}: {e}")
            expired_users.append(chat_id)

    # Remove expired users from subscription data
    for chat_id in expired_users:
        del subscription_data[chat_id]

    # Save updated subscription data
    save_subscription_data()


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
            "return_url": "https://codingservices2020.github.io/checkout/",
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
            [InlineKeyboardButton("Pay Now", url=payment_url)],
            [InlineKeyboardButton("Click here to proceed", callback_data="is_premium_member")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(chat_id, indian_plan, reply_markup=reply_markup, parse_mode="HTML")


async def handle_plan_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    choice = query.data
    amount = 2.00 if choice == "monthly" else 6.00
    user_data[chat_id]["amount"] = amount
    user_data[chat_id]["plan"] = "Monthly" if choice == "monthly" else "Annual"

    sent_message = await query.edit_message_text(f"Creating an invoice for {user_data[chat_id]['plan']} Plan. Please wait...")
    context.job_queue.run_once(
        delete_message,
        when=MSG_DELETE_TIME,  # MSG_DELETE_TIME in seconds
        data={"chat_id": chat_id, "message_id": sent_message.message_id},
    )

    order_id, approve_url = create_paypal_payment(amount)
    user_data[chat_id]["order_id"] = order_id
    keyboard = [
        [InlineKeyboardButton("Pay Now", web_app=WebAppInfo(url=approve_url))],
        [InlineKeyboardButton("Verify Payment", callback_data="verify_payment")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id, f"<b>🔰STEPS🔰</b>\n\n"
                                            f"1️⃣ First click on <b>Pay Now</b> button, to make the payment.\n"
                                            f"2️⃣ After making payment, you have to click on <b>Verify Payment</b> "
                                            f"button to verfity your payment and wait for few seconds. ",
                                   reply_markup=reply_markup, parse_mode="HTML")


async def verify_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    # Check if an order exists
    if "order_id" not in user_data[chat_id]:
        await query.edit_message_text("No payment found. Please start over.")
        return

    order_id = user_data[chat_id]["order_id"]
    try:
        # Verify the payment
        payment_result = capture_payment(order_id)
        #print(payment_result)
        if payment_result["status"] == "COMPLETED":
            expiry_date = datetime.now() + timedelta(days=30 if user_data[chat_id]["plan"] == "Monthly" else 365)
            subscription_data[chat_id] = {
                "expiry": expiry_date,
                "plan": user_data[chat_id]["plan"]
            }
            save_subscription_data()
            logger.info(f"User {chat_id} subscribed to {user_data[chat_id]['plan']} plan until {expiry_date}.")

            try:
                # Generate an invite link for the private channel that expires after one use
                invite_link = await context.bot.create_chat_invite_link(
                    PRIVATE_CHANNEL_ID,
                    member_limit=1  # The link will expire after one use
                )
                # print(invite_link)
                await context.bot.send_message(
                    chat_id,
                    f"<b>🔰Payment Successful!🔰</b> \n\n"
                    f"Here is your unique invite link to our private channel:\n{invite_link.invite_link}\n"
                    f"<b>(Valid for one time)</b>\n",
                    parse_mode="HTML"
                )
                logger.info(f"Invite link sent to user {query.from_user.id}.")
            except Exception as e:
                logger.error(f"Failed to generate/send invite link: {e}")
                await context.bot.send_message(
                    chat_id,
                    "An error occurred while processing your access. Please contact support."
                )
            # Send success message with access link
            keyboard = [
                [
                    InlineKeyboardButton(
                        "Click here to proceed",
                        callback_data="is_premium_member"
                    )
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id,
                "After joining the channel, click the button below to access Canva Pro.",
                reply_markup=reply_markup,
            )
        else:
            await query.edit_message_text("Payment not completed. Please try again.")
    except requests.exceptions.HTTPError as e:
        await query.edit_message_text(f"Payment not completed. Please try again.")
        # await query.edit_message_text(f"Payment verification failed: {e.response.json()}")


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
    subscription_data = load_subscription_data()

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
