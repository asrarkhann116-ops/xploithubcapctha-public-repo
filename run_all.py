import multiprocessing
import uvicorn
import subprocess
import sys
import os

def run_web():
    print("🚀 Starting Xploit Unblocker 95 Web & API Server on http://0.0.0.0:8000...")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)

def run_bot():
    print("🤖 Starting Xploit Unblocker Discord Bot...")
    import discord_bot

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
