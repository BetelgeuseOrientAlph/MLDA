import json
import re
import subprocess
import logging
import time
import os

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

logging.basicConfig(level=logging.INFO)

def clean_asterisks(text: str) -> str:
    text_no_markdown = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text_no_markdown = text_no_markdown.replace("**", "")
    return text_no_markdown

def run_deepseek(prompt: str, request_timestamp: float, context: ContextTypes.DEFAULT_TYPE) -> str | None:

    # (NEW) Check if there's already a newer request
    if context.user_data.get("last_request_time", 0) > request_timestamp:
        logging.info("Skipping: Found a newer request.")
        return None
    # (NEW) Or if there's a newer success
    if context.user_data.get("last_success_time", 0) > request_timestamp:
        logging.info("Skipping: Found a newer success.")
        return None

    command = ["ollama", "run", "deepseek-r1:8b", prompt]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120
        )
    except subprocess.TimeoutExpired:
        logging.info("Error: DeepSeek took too long to respond.")
        return None
    except Exception as e:
        logging.info(f"Unexpected error running DeepSeek: {e}")
        return None

    # If the model call failed
    if result.returncode != 0:
        err = result.stderr.strip()
        logging.info(f"Error calling DeepSeek model: {err}")
        return None

    raw_response = result.stdout.strip()

    logging.info("===== DeepSeek Raw Output =====\n" + raw_response + "\n================================")

    # (NEW) After generation, check again for stale
    if context.user_data.get("last_request_time", 0) > request_timestamp:
        logging.info("Skipping: A newer request happened during generation.")
        return None
    if context.user_data.get("last_success_time", 0) > request_timestamp:
        logging.info("Skipping: A newer success happened during generation.")
        return None

    response_no_think = re.sub(r"<think>.*?</think>", "", raw_response, flags=re.DOTALL)
    final_text = response_no_think.strip()
    return final_text if final_text else None

def build_prompt(patient_info: dict) -> str:
    bp = patient_info.get("blood_pressure", "")
    glucose = patient_info.get("blood_glucose", "")
    stress = patient_info.get("stress_level", "")

    prompt = f"""
    You are a telehealth AI. The patient data is as follows:
    - Blood Pressure: {bp}
    - Blood Glucose: {glucose}
    - Stress Level: {stress} (out of 10)

    Evaluate the patient's health status and provide advice, going through each vital sign.
    Avoid chain-of-thought or hidden reasoning.
    """
    return prompt.strip()

def parse_patient_data(text: str) -> dict:
    bp_pattern      = r"blood\s*pressure\s*:\s*([^\n]+)"
    glucose_pattern = r"blood\s*glucose\s*:\s*([^\n]+)"
    stress_pattern  = r"stress\s*level\s*:\s*([^\n]+)"

    bp_match      = re.search(bp_pattern, text, re.IGNORECASE)
    glc_match     = re.search(glucose_pattern, text, re.IGNORECASE)
    stress_match  = re.search(stress_pattern, text, re.IGNORECASE)

    patient_info = {}
    if bp_match or glc_match or stress_match:
        if bp_match:
            patient_info["blood_pressure"] = bp_match.group(1).strip()
        if glc_match:
            patient_info["blood_glucose"] = glc_match.group(1).strip()
        if stress_match:
            patient_info["stress_level"] = stress_match.group(1).strip()

    return patient_info

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Respond to /start command."""
    await update.message.reply_text(
        "Hello! I'm your Telehealth AI assistant.\n"
        "Type /begin when you’re ready to provide your health data.",
        parse_mode=None
    )

async def begin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to Happy Healthy Heart by CloseAI!\n\n"
        "Please provide your information for example:\n\n"
        "(You can just copy the chat bubble below and alter the data)",
        parse_mode=None
    )
    await update.message.reply_text(
        "Blood pressure: 120/100\nBlood glucose: 100\nStress level: 2/10",
        parse_mode=None
    )

async def handle_patient_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text messages that are NOT commands."""
    user_text = update.message.text.strip()
    logging.info(f"===== USER INPUT =====\n{user_text}\n======================")

    request_timestamp = time.time()
    context.user_data["last_request_time"] = request_timestamp

    try:
        patient_info = json.loads(user_text)
        if not isinstance(patient_info, dict):
            raise ValueError("Not a dict.")
    except (json.JSONDecodeError, ValueError):
        patient_info = parse_patient_data(user_text)

    if not patient_info:
        logging.warning("Could not parse user input.")
        await update.message.reply_text("I couldn't understand your input. Please try again.")
        return

    prompt = build_prompt(patient_info)
    ai_response = run_deepseek(prompt, request_timestamp, context)

    if ai_response is None:
        return

    context.user_data["last_success_time"] = request_timestamp

    ai_response = clean_asterisks(ai_response)
    logging.info(f"DeepSeek final response: {ai_response}")
    await update.message.reply_text(ai_response)

def main():
    telegram_token = "7730767667:AAF3tLHJ_y2ojx6ZmmMRvCYCmJnbL7gGcpo"
    app = ApplicationBuilder().token(telegram_token).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("begin", begin_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_patient_info))

    print("Bot is running... Press Ctrl+C to stop.")
    app.run_polling()

if __name__ == "__main__":
    main()
