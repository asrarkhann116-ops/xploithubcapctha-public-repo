import multiprocessing
import uvicorn
import sys
import os

# Ensure UTF-8 output encoding on Windows consoles
if sys.stdout.encoding != 'utf-8':
    sys.reconfigure(encoding='utf-8')

def run_web():
    print("[SERVER] Starting Xploit Unblocker Web & API Server on http://0.0.0.0:8000...")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)

def run_bot():
    print("[BOT] Starting Xploit Unblocker Discord Bot...")
    try:
        import discord_bot
    except Exception as e:
        print(f"[BOT] Discord bot offline or token unconfigured: {e}")

if __name__ == "__main__":
    p_web = multiprocessing.Process(target=run_web)
    p_bot = multiprocessing.Process(target=run_bot)

    p_web.start()
    p_bot.start()

    try:
        p_web.join()
        p_bot.join()
    except KeyboardInterrupt:
        print("\nStopping all services...")
        p_web.terminate()
        p_bot.terminate()
