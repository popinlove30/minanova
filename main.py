"""
NanoBot Telegram Webhook Server
Deploy on JustRunMy.App with Docker + Async Webhook
"""
import asyncio
import os
import json
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from aiogram import Bot, Dispatcher, types
from aiogram.types import Update
from aiogram.client.default import DefaultBotProperties
from loguru import logger

# Load nanobot
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.openai import OpenAIProvider
from nanobot.session.manager import SessionManager

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
PORT = int(os.getenv("PORT", "8080"))
NANOBOT_CONFIG_PATH = os.getenv("NANOBOT_CONFIG_PATH", "/data/config.json")
WORKSPACE_PATH = os.getenv("WORKSPACE_PATH", "/data/workspace")

# Global instances
bot: Bot = None
dispatcher: Dispatcher = None
agent_loop: AgentLoop = None
message_bus: MessageBus = None


async def load_nanobot_config() -> dict:
    """Load NanoBot configuration from config file."""
    config_path = Path(NANOBOT_CONFIG_PATH)
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {}


async def init_nanobot():
    """Initialize NanoBot agent loop."""
    global agent_loop, message_bus, bot, dispatcher
    
    # Initialize bot
    bot = Bot(
        token=TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML")
    )
    dispatcher = Dispatcher()
    
    # Load config
    config = await load_nanobot_config()
    
    # Setup workspace
    workspace = Path(WORKSPACE_PATH)
    workspace.mkdir(parents=True, exist_ok=True)
    
    # Initialize message bus
    message_bus = MessageBus()
    
    # Initialize provider (OpenRouter as default)
    provider_config = config.get("providers", {}).get("openrouter", {})
    provider = OpenAIProvider(
        api_key=provider_config.get("apiKey", ""),
        base_url="https://openrouter.ai/api/v1"
    )
    
    # Get model config
    agent_config = config.get("agents", {}).get("defaults", {})
    model = agent_config.get("model", "anthropic/claude-3.5-sonnet")
    
    # Create agent loop
    agent_loop = AgentLoop(
        bus=message_bus,
        provider=provider,
        workspace=workspace,
        model=model,
        max_iterations=40,
        context_window_tokens=65536,
    )
    
    logger.info(f"NanoBot initialized with model: {model}")


async def handle_telegram_update(update: Update) -> Response:
    """Process incoming Telegram webhook update."""
    global agent_loop, message_bus
    
    # Process message through dispatcher
    await dispatcher.emit(update)
    
    # If it's a message, process with NanoBot agent
    if update.message:
        message = update.message
        
        # Skip commands (let dispatcher handle)
        if message.text and message.text.startswith('/'):
            return Response(status_code=200)
        
        # Build inbound message for NanoBot
        from nanobot.bus.events import InboundMessage
        
        inbound = InboundMessage(
            platform="telegram",
            message_id=str(message.message_id),
            sender_id=str(message.chat.id),
            sender_name=message.from_user.full_name if message.from_user else "Unknown",
            text=message.text or "",
            raw=update.model_dump(),
        )
        
        # Publish to message bus
        message_bus.publish_inbound(inbound)
        
        # Start agent processing in background
        asyncio.create_task(agent_loop.process_message(inbound))
        
        # Subscribe to outbound messages
        async with message_bus.subscribe("telegram") as queue:
            while True:
                outbound = await queue.get()
                if outbound.recipient_id == str(message.chat.id):
                    try:
                        await bot.send_message(
                            chat_id=message.chat.id,
                            text=outbound.text
                        )
                        break
                    except Exception as e:
                        logger.error(f"Failed to send message: {e}")
                        break
    
    return Response(status_code=200)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting NanoBot server...")
    await init_nanobot()
    logger.info(f"NanoBot ready on port {PORT}")
    yield
    logger.info("Shutting down NanoBot server...")


# Create FastAPI app
app = FastAPI(
    title="NanoBot Telegram Webhook",
    version="1.0.0",
    lifespan=lifespan
)


@app.post("/webhook")
async def webhook(request: Request):
    """Telegram webhook endpoint."""
    try:
        update = Update.model_validate(await request.json())
        return await handle_telegram_update(update)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "nanobot"}


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "NanoBot Telegram Bot",
        "version": "1.0.0",
        "endpoints": ["/webhook", "/health"]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        workers=1
    )
