import os
import asyncio
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types
from aiogram.types import Update

# นำเข้า Logic จากโฟลเดอร์ minanova
# สมมติว่าใน minanova มีฟังก์ชันชื่อ generate_response
from minanova.engine import generate_response 

# การตั้งค่า
TOKEN = os.getenv("TELEGRAM_TOKEN")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL") # Render จะเติมให้เองอัตโนมัติ
WEBHOOK_PATH = f"/bot/{TOKEN}"
WEBHOOK_URL = f"{RENDER_URL}{WEBHOOK_PATH}"

app = FastAPI()
bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- Telegram Logic ---
@dp.message()
async def handle_message(message: types.Message):
    # ส่งข้อความไปให้ minanova ประมวลผล
    user_input = message.text
    # เรียกใช้ฟังก์ชันจาก minanova (ใส่ await ถ้าเป็น async)
    bot_response = await generate_response(user_input) 
    await message.answer(bot_response)

# --- FastAPI / Webhook Logic ---
@app.on_event("startup")
async def on_startup():
    await bot.set_webhook(url=WEBHOOK_URL)

@app.post(WEBHOOK_PATH)
async def bot_webhook(request: Request):
    update = Update(**(await request.json()))
    await dp.feed_update(bot=bot, update=update)
    return "OK"

@app.get("/")
async def health_check():
    return {"status": "minanova is online"}
