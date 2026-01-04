"""Upload custom emoji to Discord server."""
import asyncio
import base64
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import discord

async def upload_emoji(image_path: str, emoji_name: str):
    token = os.getenv("TRIPPIXN_BOT_TOKEN")
    guild_id = int(os.getenv("TRIPPIXN_GUILD_ID", 0))
    
    if not token or not guild_id:
        print("Missing TRIPPIXN_BOT_TOKEN or TRIPPIXN_GUILD_ID")
        return
    
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    
    @client.event
    async def on_ready():
        try:
            guild = client.get_guild(guild_id)
            if not guild:
                print(f"Guild {guild_id} not found")
                await client.close()
                return
            
            # Read image
            with open(image_path, "rb") as f:
                image_data = f.read()
            
            # Upload emoji
            emoji = await guild.create_custom_emoji(name=emoji_name, image=image_data)
            print(f"Uploaded: <:{emoji.name}:{emoji.id}>")
            print(f"ID: {emoji.id}")
            
        except discord.Forbidden:
            print("Bot lacks permission to create emojis")
        except discord.HTTPException as e:
            print(f"HTTP error: {e}")
        except Exception as e:
            print(f"Error: {e}")
        finally:
            await client.close()
    
    await client.start(token)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python upload_emoji.py <image_path> <emoji_name>")
        sys.exit(1)
    
    asyncio.run(upload_emoji(sys.argv[1], sys.argv[2]))
