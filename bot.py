import html
import json
import os
import pickle
import re
import logging

import PyPDF2
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Store extracted student data
STUDENT_DATA = {}
CACHE_FILE = os.path.join(BASE_DIR, "student_data_cache.pkl")
USERS_FILE = os.getenv("USERS_FILE", os.path.join(BASE_DIR, "bot_users.json"))
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@cyberstcafe")
CHANNEL_URL = f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"
USED_USER_IDS = set()


def load_used_users():
    """Load the unique Telegram users who passed the channel check."""
    global USED_USER_IDS

    try:
        with open(USERS_FILE, "r", encoding="utf-8") as file:
            values = json.load(file)
        if isinstance(values, list):
            USED_USER_IDS = {str(value) for value in values}
    except FileNotFoundError:
        USED_USER_IDS = set()
    except (json.JSONDecodeError, OSError) as error:
        logger.warning("Could not load user count: %s", error)
        USED_USER_IDS = set()


def record_user(user_id):
    """Record a verified user once and persist the total."""
    user_id = str(user_id)
    if user_id in USED_USER_IDS:
        return

    USED_USER_IDS.add(user_id)
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as file:
            json.dump(sorted(USED_USER_IDS), file)
    except OSError as error:
        logger.error("Could not save user count: %s", error)


def join_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Join channel", url=CHANNEL_URL)],
        [InlineKeyboardButton("I joined - Verify", callback_data="verify_membership")],
    ])


async def user_is_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check whether the user can access the bot after joining the channel."""
    user = update.effective_user
    if user is None:
        return False

    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, user.id)
    except Exception as error:
        logger.warning("Could not verify channel membership for %s: %s", user.id, error)
        return False

    return member.status in {"member", "administrator", "creator"} or (
        member.status == "restricted" and getattr(member, "is_member", False)
    )


async def ensure_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allow only channel members to use bot features."""
    if await user_is_member(update, context):
        record_user(update.effective_user.id)
        return True

    message = update.effective_message
    if message:
        await message.reply_text(
            "Please join our channel first, then tap Verify to use this bot.",
            reply_markup=join_keyboard(),
        )
    return False


def get_default_pdf_folder():
    """Return the project-local folder containing authorized PDF data."""
    return os.path.join(BASE_DIR, "NSP_data")

def save_cache():
    """Save student data to cache file"""
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(STUDENT_DATA, f)
        logger.info(f"✅ Cache saved successfully! File: {CACHE_FILE}")
    except Exception as e:
        logger.error(f"❌ Error saving cache: {e}")

def cache_is_stale(pdf_folder=None):
    """Return True when the PDF source files are newer than the cached extracted data."""
    if not os.path.exists(CACHE_FILE):
        return True

    if pdf_folder is None:
        pdf_folder = get_default_pdf_folder()
    if not os.path.exists(pdf_folder):
        return False

    pdf_mtimes = []
    for entry in os.listdir(pdf_folder):
        full_path = os.path.join(pdf_folder, entry)
        if entry.lower().endswith('.pdf') and os.path.isfile(full_path):
            pdf_mtimes.append(os.path.getmtime(full_path))

    if not pdf_mtimes:
        return False

    newest_pdf_mtime = max(pdf_mtimes)
    return newest_pdf_mtime > os.path.getmtime(CACHE_FILE)


def record_is_valid(student):
    """Keep cache validation flexible so valid saved records are not rejected on restart."""
    if not isinstance(student, dict):
        return False

    required = [
        'RollCode', 'RollNumber', 'Year', 'StudentName', 'DOB', 'FatherName',
        'Gender', 'CasteCategory', 'PhysicallyChallenged', 'Faculty',
        'FullMarks', 'TotalMarks', 'Percentage'
    ]
    if not all(key in student for key in required):
        return False

    if not str(student.get('RollCode', '')).strip().isdigit():
        return False
    if not str(student.get('RollNumber', '')).strip().isdigit():
        return False
    if not re.match(r'^\d{4}$', str(student.get('Year', ''))):
        return False
    if not str(student.get('StudentName', '')).strip():
        return False
    if not str(student.get('DOB', '')).strip():
        return False
    if not str(student.get('FatherName', '')).strip():
        return False
    if not str(student.get('Gender', '')).strip():
        return False
    if not str(student.get('CasteCategory', '')).strip():
        return False
    if not str(student.get('PhysicallyChallenged', '')).strip():
        return False
    if not str(student.get('Faculty', '')).strip():
        return False
    if not re.match(r'^\d+$', str(student.get('FullMarks', ''))):
        return False
    if not re.match(r'^\d+$', str(student.get('TotalMarks', ''))):
        return False
    if not re.match(r'^\d+(?:\.\d+)?$', str(student.get('Percentage', ''))):
        return False

    return True


def load_cache():
    """Load student data from the bundled project cache file."""
    global STUDENT_DATA

    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'rb') as f:
                STUDENT_DATA = pickle.load(f)

            if not isinstance(STUDENT_DATA, dict) or not STUDENT_DATA:
                logger.warning(f"⚠️ Cache is empty or unreadable: {CACHE_FILE}")
                return False

            invalid_sample = 0
            for student in STUDENT_DATA.values():
                if not record_is_valid(student):
                    invalid_sample += 1
                    if invalid_sample >= 1:
                        break

            if invalid_sample >= 1:
                logger.warning(f"⚠️ Cache contains malformed entries; rebuilding from PDFs.")
                STUDENT_DATA = {}
                if os.path.exists(CACHE_FILE):
                    try:
                        os.remove(CACHE_FILE)
                    except Exception:
                        pass
                return False

            logger.info(f"✅ Cache loaded successfully! Total students: {len(STUDENT_DATA)}")
            return True
        except Exception as e:
            logger.error(f"❌ Error loading cache: {e}")
            return False
    else:
        logger.warning(f"⚠️ Cache file not found: {CACHE_FILE}")
        return False

def verify_pdf_folder(pdf_folder):
    """Verify PDF folder exists and contains PDFs"""
    if not os.path.isdir(pdf_folder):
        logger.error(f"❌ PDF folder not found: {pdf_folder}")
        return False
    
    pdf_files = [f for f in os.listdir(pdf_folder) if f.lower().endswith('.pdf')]
    
    if not pdf_files:
        logger.error(f"❌ No PDF files found in: {pdf_folder}")
        return False
    
    logger.info(f"✅ Found {len(pdf_files)} PDF files: {pdf_files}")
    return True


def refresh_student_data(pdf_folder=None):
    """Force a full rebuild from the PDF folder and overwrite the saved cache."""
    global STUDENT_DATA

    if pdf_folder is None:
        pdf_folder = get_default_pdf_folder()

    logger.info("🔄 Forcing fresh rebuild from PDFs...")
    logger.info(f"📂 PDF Folder: {pdf_folder}")

    STUDENT_DATA.clear()
    if not extract_pdf_data(pdf_folder):
        logger.error("❌ Failed to load PDF data during refresh.")
        return False

    if len(STUDENT_DATA) == 0:
        logger.error("❌ No student data found during refresh.")
        return False

    return True


def bootstrap_student_data(pdf_folder=None):
    """Load cached records when the source PDFs are unchanged; otherwise rebuild from PDFs."""
    global STUDENT_DATA

    if pdf_folder is None:
        pdf_folder = get_default_pdf_folder()

    logger.info("🚀 NSP Status Bot Starting...")
    logger.info(f"📂 PDF Folder: {pdf_folder}")

    if os.path.exists(CACHE_FILE):
        if not cache_is_stale(pdf_folder):
            logger.info("📦 Cache is up to date. Reusing cached student data without reprocessing PDFs.")
            STUDENT_DATA.clear()
            if load_cache():
                return True
            logger.warning("⚠️ Cache was present but invalid; rebuilding from PDFs.")
        else:
            logger.info("🕒 Cache is stale; rebuilding student data from PDFs.")
    else:
        logger.info("📦 Cache file not found. Building student data from PDFs.")

    return refresh_student_data(pdf_folder)


def split_gender_and_category(raw_value):
    """Normalize data such as 'FemaleEWS', 'Female EWS', or 'MaleBC'."""
    value = (raw_value or '').strip()
    if not value:
        return 'N/A', 'N/A'

    match = re.match(r'^(Male|Female|Transgender|M|F)\s*(.*)$', value, flags=re.IGNORECASE)
    if match:
        gender = match.group(1).title()
        category = (match.group(2) or '').strip()
        if not category:
            return gender, 'N/A'
        category = category.replace('_', ' ')
        category_tokens = category.split()
        category = category_tokens[-1] if category_tokens else category
        category_map = {
            'GENRAL': 'General',
            'GENERAL': 'General',
            'BC': 'BC',
            'EBC': 'EBC',
            'SC': 'SC',
            'ST': 'ST',
            'EWS': 'EWS',
            'OBC': 'OBC',
            'SEBC': 'SEBC',
            'WBC': 'WBC',
        }
        normalized_category = category_map.get(category.upper(), category.title())
        return gender, normalized_category

    if ' ' in value:
        parts = value.split()
        gender = parts[0].title()
        category = parts[-1].strip()
        category_map = {
            'GENRAL': 'General',
            'GENERAL': 'General',
            'BC': 'BC',
            'EBC': 'EBC',
            'SC': 'SC',
            'ST': 'ST',
            'EWS': 'EWS',
            'OBC': 'OBC',
            'SEBC': 'SEBC',
            'WBC': 'WBC',
        }
        normalized_category = category_map.get(category.upper(), category.title())
        return gender, normalized_category

    return value.title(), 'N/A'


def parse_student_line(line, faculty):
    """Parse a single student row from the actual PDF format."""
    line = line.strip()
    if not line or not re.match(r'^\d+-\d+', line):
        return None

    try:
        # Extract roll + year at the very start.
        start_match = re.match(r'^(?P<roll>\d+-\d+)\s+(?P<year>\d{4})\s+(?P<rest>.+)$', line)
        if not start_match:
            return None

        roll_code, roll_number = start_match.group('roll').split('-', 1)
        year = start_match.group('year')
        rest = start_match.group('rest').strip()

        # Extract the fixed trailing fields: challenged, faculty, full marks, total marks, percentage.
        tail_match = re.search(
            r'(?P<challenged>YES|NO)\s+(?P<faculty>[A-Za-z]+)\s+(?P<fullmarks>\d+)\s+(?P<totalmarks>\d+)\s+(?P<percentage>\d+(?:\.\d+)?)\s*$',
            rest,
            flags=re.IGNORECASE,
        )
        if not tail_match:
            return None

        prefix = rest[:tail_match.start()].strip()
        dob_match = re.search(r'(?P<dob>\d{2}-\d{2}-\d{4})\s+(?P<afterdob>.+)$', prefix)
        if not dob_match:
            return None

        student_name = prefix[:dob_match.start()].strip()
        after_dob = dob_match.group('afterdob').strip()

        # The real PDFs often put the father name and then the merged gender/category token.
        parts = after_dob.split()
        gender_category = None
        father_name = after_dob
        for idx in range(len(parts) - 1, 0, -1):
            candidate = ' '.join(parts[idx:])
            if re.match(r'^(?:Male|Female|Transgender|M|F)(?:\s*(?:General|Genral|BC|EBC|SC|ST|EWS|OBC|SEBC|WBC|[A-Za-z]+))?$', candidate, flags=re.IGNORECASE):
                gender_category = candidate
                father_name = ' '.join(parts[:idx]).strip()
                break

        if gender_category is None:
            return None

        gender_value, category_value = split_gender_and_category(gender_category)

        student_data = {
            'RollCode': roll_code.strip(),
            'RollNumber': roll_number.strip(),
            'Year': year.strip(),
            'StudentName': student_name,
            'DOB': dob_match.group('dob').strip(),
            'FatherName': father_name,
            'Gender': gender_value,
            'CasteCategory': category_value,
            'PhysicallyChallenged': tail_match.group('challenged').strip().upper(),
            'Faculty': faculty.upper(),
            'FullMarks': tail_match.group('fullmarks').strip(),
            'TotalMarks': tail_match.group('totalmarks').strip(),
            'Percentage': tail_match.group('percentage').strip(),
        }
        return student_data
    except Exception as e:
        logger.debug(f"Parse error: {e}")
        return None

def extract_pdf_data(pdf_folder):
    """Extract student data from all PDFs in the folder"""
    global STUDENT_DATA
    
    if not verify_pdf_folder(pdf_folder):
        return False
    
    for pdf_file in os.listdir(pdf_folder):
        if pdf_file.lower().endswith('.pdf'):
            pdf_path = os.path.join(pdf_folder, pdf_file)
            faculty = os.path.splitext(pdf_file)[0].upper()
            
            logger.info(f"📄 Processing {pdf_file}...")
            
            try:
                with open(pdf_path, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    logger.info(f"   Total pages: {len(reader.pages)}")
                    
                    for page_num in range(len(reader.pages)):
                        page = reader.pages[page_num]
                        text = page.extract_text()
                        
                        if not text or len(text.strip()) < 10:
                            continue
                        
                        # Split into lines
                        lines = text.split('\n')
                        
                        # Process each line
                        for line in lines:
                            student_data = parse_student_line(line, faculty)
                            
                            if student_data:
                                student_key = f"{student_data['RollCode']}_{student_data['RollNumber']}"
                                STUDENT_DATA[student_key] = student_data
                                
                                if page_num == 0:  # Log only first page
                                    logger.debug(f"✓ Loaded: {student_key}")
                                    

            except Exception as e:
                logger.error(f"❌ Error processing {pdf_file}: {e}")
                continue
    
    logger.info(f"\n{'='*60}")
    logger.info(f"✅ Total students loaded from PDFs: {len(STUDENT_DATA)}")
    logger.info(f"{'='*60}\n")
    
    # Debug: Print first few records
    if STUDENT_DATA:
        for i, (key, student) in enumerate(list(STUDENT_DATA.items())[:3]):
            logger.info(f"📌 Sample {i+1}: {key}")
            logger.info(f"   Name: {student['StudentName']}")
            logger.info(f"   Faculty: {student['Faculty']}")
        save_cache()
        return True
    else:
        logger.warning("⚠️ No records found! Check PDF format.")
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command - Welcome message"""
    if not await ensure_access(update, context):
        return

    welcome_text = """

   🎓 NSP STUDENT RECORD BOT 🎓
     National Scholarship Portal        


✨ <b>Welcome to NSP Status Bot!</b>

This bot helps you look up your student record.

📋 <b>How to use:</b>
1️⃣ Click on "Check Status" below
2️⃣ Enter your Roll Code
3️⃣ Enter your Roll Number
4️⃣ View your available record details

🎯 <b>Features:</b>
✅ Instant student record lookup
✅ Complete student information
✅ Category and marks details
✅ Fast and secure

Let's get started! 👇
    """
    
    keyboard = [
        [KeyboardButton("✅ Check Status")],
        [KeyboardButton("ℹ️ About"), KeyboardButton("📞 Help")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='HTML')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    if not await ensure_access(update, context):
        return

    help_text = """
📖 <b>HELP GUIDE</b>

<b>How to Check Your Status:</b>
1. Click "Check Status"
2. Enter your Roll Code (e.g., 17089)
3. Enter your Roll Number (e.g., 26020020)
4. Your complete details will be displayed

<b>What Information You'll Get:</b>
📌 Full Name
📌 Date of Birth
📌 Father's Name
📌 Gender
📌 Category
📌 Faculty
📌 Marks and Percentage

<b>Still need help?</b>
Contact the channel admin for support.
    """
    await update.message.reply_text(help_text, parse_mode='HTML')

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """About command"""
    if not await ensure_access(update, context):
        return

    about_text = """
<b>About NSP Status Bot</b>

This bot looks up student records related to the National Scholarship Portal. It does not determine scholarship eligibility.

<b>Supported Categories:</b>
🎓 Arts
🔬 Science
💼 Commerce

Record data is read from the authorized PDFs configured by the bot operator.

<b>Version:</b> 1.0
<b>Developed for:</b> Cyber Station Internet Cafe
    """
    await update.message.reply_text(about_text, parse_mode='HTML')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot status"""
    if not await ensure_access(update, context):
        return

    status_text = f"""
📊 <b>BOT STATUS</b>

✅ <b>Bot Status:</b> Running
👥 <b>Users Used Bot:</b> {len(USED_USER_IDS)}
📦 <b>Total Students Loaded:</b> {len(STUDENT_DATA)}
💾 <b>Cache File:</b> {html.escape(CACHE_FILE)}
📂 <b>Cache Exists:</b> {'Yes ✅' if os.path.exists(CACHE_FILE) else 'No ❌'}

<b>System:</b>
- Using {'Cached' if os.path.exists(CACHE_FILE) else 'Fresh'} data
- Ready to serve queries
    """
    await update.message.reply_text(status_text, parse_mode='HTML')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user messages"""
    if not await ensure_access(update, context):
        return

    text = update.message.text
    
    if text == "✅ Check Status":
        await update.message.reply_text("📝 Please enter your <b>Roll Code</b>:\n(Example: 17089)", parse_mode='HTML')
        context.user_data['step'] = 1
        
    elif text == "ℹ️ About":
        await about_command(update, context)
        
    elif text == "📞 Help":
        await help_command(update, context)
        
    elif context.user_data.get('step') == 1:
        roll_code = text.strip()
        if not roll_code.isdigit():
            await update.message.reply_text("Roll Code must contain digits only. Please try again.")
            return
        context.user_data['roll_code'] = roll_code
        await update.message.reply_text("📝 Now enter your <b>Roll Number</b>:\n(Example: 26020020)", parse_mode='HTML')
        context.user_data['step'] = 2
        
    elif context.user_data.get('step') == 2:
        roll_number = text.strip()
        if not roll_number.isdigit():
            await update.message.reply_text("Roll Number must contain digits only. Please try again.")
            return
        context.user_data['roll_number'] = roll_number
        student_key = f"{context.user_data['roll_code']}_{context.user_data['roll_number']}"
        
        logger.info(f"🔍 Searching for: {student_key}")
        
        if student_key in STUDENT_DATA:
            student = STUDENT_DATA[student_key]
            detail_text = f"""

         📋 STUDENT DETAILS 📋         

👤 <b>Name:</b> {html.escape(str(student['StudentName']))}
🔢 <b>Roll Code:</b> {html.escape(str(student['RollCode']))}
🆔 <b>Roll Number:</b> {html.escape(str(student['RollNumber']))}
📅 <b>Year of Passing:</b> {html.escape(str(student['Year']))}
🎂 <b>Date of Birth:</b> {html.escape(str(student['DOB']))}
👨 <b>Father's Name:</b> {html.escape(str(student['FatherName']))}
⚧️ <b>Gender:</b> {html.escape(str(student['Gender']))}
📂 <b>Category:</b> {html.escape(str(student['CasteCategory']))}
♿ <b>Physically Challenged:</b> {html.escape(str(student['PhysicallyChallenged']))}
🎓 <b>Faculty:</b> {html.escape(str(student['Faculty']))}
📊 <b>Full Marks:</b> {html.escape(str(student['FullMarks']))}
📈 <b>Total Marks:</b> {html.escape(str(student['TotalMarks']))}
📉 <b>Percentage/Grade:</b> {html.escape(str(student['Percentage']))}


Record found. This bot does not determine NSP eligibility.

📢 Join our WhatsApp community:
🔗 Group: https://chat.whatsapp.com/JzN8HTpzs7I2aWwEqIpmeX
🔗 Channel: https://whatsapp.com/channel/0029Vb8LQWm4CrfnJ7Jg923v

            """
            await update.message.reply_text(detail_text, parse_mode='HTML')
        else:
            await update.message.reply_text(
                f"❌ <b>Student Not Found!</b>\n\n"
                f"Roll Code: {html.escape(context.user_data['roll_code'])}\n"
                f"Roll Number: {html.escape(context.user_data['roll_number'])}\n\n"
                "Please verify your details and try again.",
                parse_mode='HTML',
            )
        
        context.user_data['step'] = 0

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"❌ Error occurred: {context.error}")


async def verify_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Re-check membership after the user taps the verification button."""
    query = update.callback_query
    await query.answer()

    if not await user_is_member(update, context):
        await query.message.reply_text(
            "I could not verify your membership yet. Join the channel and tap Verify again.",
            reply_markup=join_keyboard(),
        )
        return

    record_user(update.effective_user.id)
    await query.message.reply_text("Membership verified. Send /start to use the bot.")

def main():
    """Start the bot using local PDF data."""
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable is required")

    pdf_folder = get_default_pdf_folder()
    if not bootstrap_student_data(pdf_folder):
        raise RuntimeError(f"Could not load student data from {pdf_folder}")

    load_used_users()

    # Create bot application

    app = Application.builder().token(token).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CallbackQueryHandler(verify_membership, pattern="^verify_membership$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    
    logger.info("✅ Bot started successfully!")
    logger.info(f"📊 Ready with {len(STUDENT_DATA)} student records\n")
    app.run_polling()

if __name__ == "__main__":
    main()