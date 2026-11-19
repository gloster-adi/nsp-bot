# NSP Status Bot

A Python Telegram bot that looks up student records from locally supplied PDF files. Users must join the configured Telegram channel before using the bot.

## Features

- Looks up records using roll code and roll number
- Shows available student, faculty, marks, and percentage fields
- Checks membership in a configured Telegram channel
- Caches parsed PDF records locally to speed up restarts
- Provides `/start`, `/help`, `/about`, and `/status` commands

## Requirements

- Python 3
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- Authorized PDF data files placed in a local `NSP_data` directory

## Setup

1. Clone the repository and create a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   On macOS or Linux:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install the Python dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Create a `.env` file from the example:

   ```powershell
   Copy-Item .env.example .env
   ```

   On macOS or Linux:

   ```bash
   cp .env.example .env
   ```

4. Set `BOT_TOKEN` in `.env`. Set `CHANNEL_USERNAME` to the channel users must join. The bot must be able to check membership in that channel.

5. Create `NSP_data` beside `bot.py` and place the authorized PDF files there. The PDFs are intentionally excluded from Git because they contain personal student information.

6. Start the bot:

   ```bash
   python bot.py
   ```

On the first start, the bot parses the PDFs and creates `student_data_cache.pkl`. It stores verified Telegram user IDs in `bot_users.json`. Both files are local and excluded from Git.

## Bot commands

| Command | Description |
| --- | --- |
| `/start` | Check channel membership and open the bot menu |
| `/help` | Show instructions |
| `/about` | Show bot information |
| `/status` | Show runtime and loaded-data counts |

Users can then select **Check Status**, enter their roll code, and enter their roll number.

## Configuration

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `BOT_TOKEN` | Yes | Not set | Telegram bot token |
| `CHANNEL_USERNAME` | No | `@cyberstcafe` | Channel required for access |
| `USERS_FILE` | No | `bot_users.json` | Path used to store verified Telegram user IDs |

## Tests

Install `pytest` and run the test suite:

```bash
python -m pip install pytest
python -m pytest
```

## Data and privacy

The PDF source files and runtime data are not included in this repository. Only use datasets you are authorized to process, keep them private, and do not commit them or the bot token. The bot displays personal information from the supplied PDFs, so deploy it only in accordance with applicable privacy requirements.
