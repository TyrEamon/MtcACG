import os
import asyncio
import logging
import json
import random
from io import BytesIO
import aiohttp
import boto3
from aiogram import Bot
from aiogram.types import BufferedInputFile
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# --- 配置日志 ---
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# --- 1. 更加健壮的环境变量读取 ---
# 尝试从多个可能的变量名中获取 Account ID
CF_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID") or os.getenv("R2_ACCOUNT_ID") or os.getenv("CF_ACCOUNT_ID")

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID") # 先读字符串，后面转int
CF_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN") or os.getenv("CF_API_TOKEN")

# R2 配置
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET = os.getenv("R2_BUCKET_NAME")
D1_DB_ID = os.getenv("D1_DATABASE_ID")

# --- 2. 启动前检查 ---
if not CF_ACCOUNT_ID:
    logger.error("❌ 致命错误: 无法获取 Cloudflare Account ID！请检查环境变量 CLOUDFLARE_ACCOUNT_ID")
    exit(1)

if not CHANNEL_ID:
    logger.error("❌ 致命错误: 无法获取 CHANNEL_ID！")
    exit(1)

CHANNEL_ID = int(CHANNEL_ID)
R2_ENDPOINT = f"https://{CF_ACCOUNT_ID}.r2.cloudflarestorage.com"

# --- 初始化客户端 ---
bot = Bot(token=BOT_TOKEN)

# R2 客户端 (boto3)
s3_client = boto3.client(
    's3',
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY
)

# --- 核心功能函数 ---

def upload_to_r2_sync(file_data, filename):
    """同步上传函数，将在线程中运行"""
    try:
        file_data.seek(0)
        s3_client.upload_fileobj(
            file_data, 
            R2_BUCKET, 
            filename,
            ExtraArgs={'ContentType': 'image/jpeg'}
        )
        logger.info(f"✅ R2 上传成功: {filename}")
        return True
    except Exception as e:
        logger.error(f"❌ R2 上传失败: {e}")
        return False

async def save_to_d1(post_id, file_name, caption, tags):
    """写入 D1 数据库"""
    if not CF_ACCOUNT_ID:
        logger.error("❌ 无法写入 D1: Account ID 缺失")
        return

    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/d1/database/{D1_DB_ID}/query"
    headers = {
        "Authorization": f"Bearer {CF_API_TOKEN}",
        "Content-Type": "application/json"
    }
    
    # 使用 INSERT OR IGNORE 避免重复 ID 报错
    sql = "INSERT OR IGNORE INTO images (id, file_name, caption, tags, created_at) VALUES (?, ?, ?, ?, ?)"
    params = [str(post_id), file_name, caption, tags, int(asyncio.get_event_loop().time())]
    
    payload = {
        "sql": sql,
        "params": params
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            response_text = await resp.text()
            if resp.status == 200:
                logger.info(f"✅ D1 写入成功: {post_id}")
            else:
                logger.error(f"❌ D1 写入失败 (Status {resp.status}): {response_text}")

async def fetch_and_post():
    try:
        # 抓取逻辑
        api_url = "https://yande.re/post.json?limit=1&tags=order:random"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                posts = await resp.json()
                if not posts: return
                
                post = posts[0]
                # 优先用 sample_url (大图但不是原图)，没有则用 file_url
                image_url = post.get('sample_url') or post.get('file_url')
                post_id = post.get('id')
                tags = post.get('tags', '')
                file_name = f"{post_id}.jpg"

                logger.info(f"📥 下载图片: {post_id}...")

                # 下载图片
                async with session.get(image_url) as img_resp:
                    if img_resp.status != 200: return
                    img_bytes = await img_resp.read()
                    img_buffer = BytesIO(img_bytes)

        # 1. 先上传到 R2 (使用线程池避免阻塞)
        # 刚才你这里的 await 写法有问题，导致 coroutine never awaited
        await asyncio.to_thread(upload_to_r2_sync, img_buffer, file_name)

        # 2. 发送到 Telegram
        caption = f"ID: {post_id}\nTags: #{tags.replace(' ', ' #')}"
        tg_file = BufferedInputFile(img_buffer.getvalue(), filename=file_name)
        await bot.send_photo(chat_id=CHANNEL_ID, photo=tg_file, caption=caption)
        logger.info("✅ TG 发送成功")

        # 3. 最后写入 D1
        await save_to_d1(post_id, file_name, caption, tags)

    except Exception as e:
        logger.error(f"⚠️ 循环出错: {e}")

async def main():
    logger.info("🚀 Bot 已启动 (修复版 V2)...")
    logger.info(f"Using Account ID: {CF_ACCOUNT_ID}") # 打印出来看看有没有读到
    
    while True:
        await fetch_and_post()
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
