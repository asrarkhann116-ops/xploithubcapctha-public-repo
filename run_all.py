import multiprocessing
import uvicorn
import sys
import os
import socket
import threading

# Ensure UTF-8 output encoding on Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def start_tcp_bridge(from_port: int, to_port: int):
    """
    Transparent TCP bridge: forwards incoming traffic on from_port to to_port.
    Prevents Railway 502 Bad Gateway if Railway domain routes to 8000 while
    the container is assigned $PORT (e.g. 8080).
    """
    if from_port == to_port:
        return

    def pipe(src, dst):
        try:
            while True:
                data = src.recv(16384)
                if not data:
                    break
                dst.sendall(data)
        except Exception:
            pass
        finally:
            try:
                src.close()
            except Exception:
                pass
            try:
                dst.close()
            except Exception:
                pass

    def handle_conn(client_sock):
        try:
            target_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            target_sock.connect(("127.0.0.1", to_port))
            t1 = threading.Thread(target=pipe, args=(client_sock, target_sock), daemon=True)
            t2 = threading.Thread(target=pipe, args=(target_sock, client_sock), daemon=True)
            t1.start()
            t2.start()
        except Exception:
            try:
                client_sock.close()
            except Exception:
                pass

    def listen_loop():
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("0.0.0.0", from_port))
            srv.listen(128)
            print(f"[BRIDGE] Port forwarder active: 0.0.0.0:{from_port} -> 127.0.0.1:{to_port}")
            while True:
                conn, _ = srv.accept()
                threading.Thread(target=handle_conn, args=(conn,), daemon=True).start()
        except Exception as e:
            # Port might be in use or unauthorized
            print(f"[BRIDGE] Notice: could not bind port {from_port}: {e}")

    threading.Thread(target=listen_loop, daemon=True).start()

def run_web():
    port = int(os.getenv("PORT", "8080"))
    host = os.getenv("HOST", "0.0.0.0")

    # If app is on 8080, also forward 8000 -> 8080 (handles legacy EXPOSE 8000 mappings)
    if port != 8000:
        start_tcp_bridge(8000, port)
    # If app is on 8000, also forward 8080 -> 8000 (handles Railway $PORT=8080 defaults)
    if port != 8080:
        start_tcp_bridge(8080, port)

    print(f"[SERVER] Starting Xploit Unblocker Web & API Server on http://{host}:{port}...")
    uvicorn.run("server:app", host=host, port=port, reload=False)

def run_bot():
    print("[BOT] Starting Xploit Unblocker Discord Bot...")
    try:
        import discord_bot
        discord_bot.start_bot()
    except Exception as e:
        print(f"[BOT] Discord bot offline or token unconfigured: {e}")

if __name__ == "__main__":
    # ── Step 1: Restore DB from Discord DM backup (before server/bot start) ──
    import asyncio as _asyncio
    from core.db_backup import restore_db_from_discord as _restore

    print("[STARTUP] Attempting DB restore from Discord DM...")
    try:
        restored = _asyncio.run(_restore())
        if restored:
            print("[STARTUP] ✅ DB restored from Discord DM backup.")
        else:
            print("[STARTUP] No backup found — starting fresh (DB will be initialised by server).")
    except Exception as _e:
        print(f"[STARTUP] DB restore skipped (error): {_e}")

    # ── Step 2: Start web server and Discord bot in parallel ──────────────────
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

