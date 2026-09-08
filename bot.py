import os
import PyPDF2
import re
import pickle
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Store extracted student data
STUDENT_DATA = {}
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE_DIR, "student_data_cache.pkl")


def get_default_pdf_folder():
    """Return the project-local bundled PDF folder, falling back to the legacy external folder if needed."""
    bundled_folder = os.path.join(BASE_DIR, "NSP_data")
    if os.path.exists(bundled_folder):
        return bundled_folder

    legacy_folder = r"c:\Users\Aditya\Downloads\NSP_data"
    if os.path.exists(legacy_folder):
        return legacy_folder

    return bundled_folder

def save_cache():
    """Save student data to cache file"""
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(STUDENT_DATA, f)
        logger.info(f"✅ Cache saved successfully! File: {CACHE_FILE}")
    except Exception as e:
        logger.error(f"❌ Error saving cache: {e}")

def cache_is_stale():
    """Return True when the PDF source files are newer than the cached extracted data."""
    if not os.path.exists(CACHE_FILE):
        return True

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
    if not os.path.exists(pdf_folder):
        logger.error(f"❌ PDF folder not found: {pdf_folder}")
        return False
    
    pdf_files = [f for f in os.listdir(pdf_folder) if f.endswith('.pdf')]
    
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

    if os.path.exists(CACHE_FILE):
        logger.info(f"🧹 Manual refresh: deleting old cache before rebuilding from PDFs: {CACHE_FILE}")
        try:
            os.remove(CACHE_FILE)
            logger.info(f"✅ Old cache deleted successfully: {CACHE_FILE}")
        except Exception as e:
            logger.warning(f"⚠️ Could not remove old cache: {e}")
    else:
        logger.info(f"🧹 Manual refresh: no old cache found; rebuilding from PDFs: {CACHE_FILE}")

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
        if not cache_is_stale():
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
        if pdf_file.endswith('.pdf'):
            pdf_path = os.path.join(pdf_folder, pdf_file)
            faculty = pdf_file.replace('.pdf', '').upper()
            
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
    welcome_text = """

   🎓 NSP ELIGIBILITY STATUS BOT 🎓    
     National Scholarship Portal        


✨ **Welcome to NSP Status Bot!**

This bot helps you check your NSP eligibility status instantly. 

📋 **How to use:**
1️⃣ Click on "Check Status" below
2️⃣ Enter your Roll Code
3️⃣ Enter your Roll Number
4️⃣ Get your complete details & NSP eligibility status

🎯 **Features:**
✅ Instant eligibility verification
✅ Complete student information
✅ Category and scholarship details
✅ Fast and secure

Let's get started! 👇
    """
    
    keyboard = [
        [KeyboardButton("✅ Check Status")],
        [KeyboardButton("ℹ️ About"), KeyboardButton("📞 Help")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    help_text = """
📖 **HELP GUIDE**

**How to Check Your Status:**
1. Click "Check Status"
2. Enter your Roll Code (e.g., 17089)
3. Enter your Roll Number (e.g., 26020020)
4. Your complete details will be displayed
5. Check your NSP Eligibility Status

**What Information You'll Get:**
📌 Full Name
📌 Date of Birth
📌 Father's Name
📌 Gender
📌 Category
📌 Faculty
📌 Marks & Percentage
📌 **NSP Status: ELIGIBLE** ✅

**Still need help?**
Contact: +918936088565
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """About command"""
    about_text = """
**About NSP Status Bot**

This bot is designed to help students check their National Scholarship Portal (NSP) eligibility status.

**Supported Categories:**
🎓 Arts
🔬 Science
💼 Commerce

All data is sourced from official NSP databases and Bihar School Examination Board records.

**Version:** 1.0
**Developed for:** Cyber Station Internet Cafe
    """
    await update.message.reply_text(about_text, parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot status"""
    status_text = f"""
📊 **BOT STATUS**

✅ **Bot Status:** Running
📦 **Total Students Loaded:** {len(STUDENT_DATA)}
💾 **Cache File:** {CACHE_FILE}
📂 **Cache Exists:** {'Yes ✅' if os.path.exists(CACHE_FILE) else 'No ❌'}

**System:**
- Using {'Cached' if os.path.exists(CACHE_FILE) else 'Fresh'} data
- Ready to serve queries
    """
    await update.message.reply_text(status_text, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user messages"""
    text = update.message.text
    
    if text == "✅ Check Status":
        await update.message.reply_text("📝 Please enter your **Roll Code**:\n(Example: 17089)", parse_mode='Markdown')
        context.user_data['step'] = 1
        
    elif text == "ℹ️ About":
        await about_command(update, context)
        
    elif text == "📞 Help":
        await help_command(update, context)
        
    elif context.user_data.get('step') == 1:
        context.user_data['roll_code'] = text.strip()
        await update.message.reply_text("📝 Now enter your **Roll Number**:\n(Example: 26020020)", parse_mode='Markdown')
        context.user_data['step'] = 2
        
    elif context.user_data.get('step') == 2:
        context.user_data['roll_number'] = text.strip()
        student_key = f"{context.user_data['roll_code']}_{context.user_data['roll_number']}"
        
        logger.info(f"🔍 Searching for: {student_key}")
        
        if student_key in STUDENT_DATA:
            student = STUDENT_DATA[student_key]
            detail_text = f"""

         📋 STUDENT DETAILS 📋         

👤 **Name:** {student['StudentName']}
🔢 **Roll Code:** {student['RollCode']}
🆔 **Roll Number:** {student['RollNumber']}
📅 **Year of Passing:** {student['Year']}
🎂 **Date of Birth:** {student['DOB']}
👨 **Father's Name:** {student['FatherName']}
⚧️ **Gender:** {student['Gender']}
📂 **Category:** {student['CasteCategory']}
♿ **Physically Challenged:** {student['PhysicallyChallenged']}
🎓 **Faculty:** {student['Faculty']}
📊 **Full Marks:** {student['FullMarks']}
📈 **Total Marks:** {student['TotalMarks']}
📉 **Percentage/Grade:** {student['Percentage']}


NSP STATUS: ELIGIBLE ✅           
Congratulations on your eligibility!🎉  

📢 Join our WhatsApp community:
🔗 Group: https://chat.whatsapp.com/JzN8HTpzs7I2aWwEqIpmeX
🔗 Channel: https://whatsapp.com/channel/0029Vb8LQWm4CrfnJ7Jg923v

            """
            await update.message.reply_text(detail_text, parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ **Student Not Found!**\n\nRoll Code: {context.user_data['roll_code']}\nRoll Number: {context.user_data['roll_number']}\n\nPlease verify your details and try again.", parse_mode='Markdown')
        
        context.user_data['step'] = 0

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"❌ Error occurred: {context.error}")

def main():
    """Start the bot using bundled project data by default."""
    pdf_folder = get_default_pdf_folder()

    if not bootstrap_student_data(pdf_folder):
        return

    # Create bot application
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable is required")

    app = Application.builder().token(token).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    
    logger.info("✅ Bot started successfully!")
    logger.info(f"📊 Ready with {len(STUDENT_DATA)} student records\n")
    app.run_polling()

if __name__ == "__main__":
    main()