import os
import re
import threading
from fastapi import FastAPI
import uvicorn

from pyrogram import Client, filters
from imdb import search_movie, get_movie
from database import files

# ===== ENV =====
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

# ===== BOT =====
app = Client("moviebot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ===== WEB =====
web = FastAPI()

# ===== UTILS =====
def format_size(size):
    for unit in ['B','KB','MB','GB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024

def clean_title(name):
    name = re.sub(r'\.(mkv|mp4|avi)', '', name)
    name = re.sub(r'S\d+E\d+', '', name)
    return name.replace(".", " ").strip()

# ===== IMDb =====
async def fetch_imdb(title):
    try:
        results = await search_movie(title)
        if not results:
            return {}

        movie_id = results[0]["id"]
        data = await get_movie(movie_id)

        return {
            "title": data.get("TITLE"),
            "rating": data.get("RATING"),
            "story": data.get("STORY_LINE"),
            "poster": data.get("IMG_POSTER"),
            "imdb_id": data.get("IMDB_ID")
        }
    except:
        return {}

# =========================
# 📦 SAVE FILE
# =========================
@app.on_message(filters.chat(CHANNEL_ID) & (filters.video | filters.document))
async def save_file(client, message):
    try:
        file = message.video or message.document
        file_name = file.file_name or "file"
        file_size = format_size(file.file_size)

        file_id = str(message.id)

        if await files.find_one({"file_id": file_id}):
            return

        title = clean_title(file_name)
        imdb = await fetch_imdb(title)

        data = {
            "file_id": file_id,
            "message_id": message.id,
            "chat_id": message.chat.id,
            "file_name": file_name,
            "size": file_size,
            "title": title,
            "imdb": imdb
        }

        await files.insert_one(data)

        bot_username = (await client.get_me()).username
        link = f"https://t.me/{bot_username}?start={file_id}"

        await message.reply_text(f"""📦 FILE SAVED

🎬 {file_name}
⭐ {imdb.get("rating", "N/A")}

🔗 {link}
""")

    except Exception as e:
        print("ERROR:", e)


# =========================
# 🔗 GET FILE
# =========================
@app.on_message(filters.command("start"))
async def start(client, message):
    args = message.text.split()

    if len(args) > 1:
        file_id = args[1]

        data = await files.find_one({"file_id": file_id})

        if data:
            await client.copy_message(
                chat_id=message.chat.id,
                from_chat_id=data["chat_id"],
                message_id=data["message_id"]
            )
        else:
            await message.reply_text("❌ File not found")
    else:
        await message.reply_text("👋 Send link")


# =========================
# 🌐 WEBSITE
# =========================

@web.get("/")
async def home():
    movies = []
    async for f in files.find().sort("_id", -1).limit(50):
        movies.append({
            "name": f["file_name"],
            "size": f["size"],
            "link": f"/movie/{f['file_id']}"
        })
    return {"movies": movies}


@web.get("/movie/{file_id}")
async def movie(file_id: str):
    data = await files.find_one({"file_id": file_id})

    if not data:
        return {"error": "Not found"}

    bot_username = (await app.get_me()).username

    return {
        "file_id": data["file_id"],
        "file_name": data["file_name"],
        "size": data["size"],
        "telegram_link": f"https://t.me/{bot_username}?start={file_id}",
        "imdb": data.get("imdb", {})
    }


@web.get("/search")
async def search(q: str):
    results = []

    async for f in files.find({"title": {"$regex": q, "$options": "i"}}):
        results.append({
            "name": f["file_name"],
            "link": f"/movie/{f['file_id']}"
        })

    return {"results": results}


# =========================
# 🚀 RUN
# =========================
def run_web():
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(web, host="0.0.0.0", port=port)

threading.Thread(target=run_web).start()

app.run()
