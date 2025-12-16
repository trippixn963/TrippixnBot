# TrippixnBot

<div align="center">

![Python](https://img.shields.io/badge/Python-3.12-blue.svg)
![Discord.py](https://img.shields.io/badge/Discord.py-2.3.2+-green.svg)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o--mini-orange.svg)
![License](https://img.shields.io/badge/License-MIT-red.svg)

**Personal portfolio bot with AI-powered ping responder and social media downloader**

*Built for discord.gg/syria*

[![Join Discord Server](https://img.shields.io/badge/Join%20Server-discord.gg/syria-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/syria)

</div>

---

## Overview

TrippixnBot serves as a developer portfolio/status bot with real-time stats API, AI-powered ping responses, and social media downloading. It monitors developer presence and provides server statistics for external dashboards.

### Disclaimer

This bot was custom-built for **discord.gg/syria** and is provided as-is for educational purposes. **No support will be provided.**

---

## Features

### Stats API
- **Real-Time Stats** - HTTP API serving server and developer stats
- **Guild Info** - Member count, online count, boost level
- **Bot Status** - Monitors TahaBot and OthmanBot online status
- **Developer Presence** - Real-time status, avatar, banner, activities
- **Health Endpoint** - External monitoring support

### AI Ping Responder
- **AutoMod Integration** - Intercepts blocked developer pings
- **AI Responses** - GPT-4o-mini generates in-character responses
- **Context Awareness** - Fetches developer's current activity from Lanyard
- **Ping Tracking** - Escalates annoyance for repeat pingers
- **Webhook Notifications** - Alerts developer of blocked pings

### Media Downloader
- **Multi-Platform** - Instagram, Twitter/X, and TikTok support
- **Slash Command** - `/download url:` for direct downloads
- **Reply Download** - Reply "download" to any message with a link
- **Auto-Compression** - FFmpeg compresses videos over 24MB
- **Carousel Support** - Downloads all media from multi-file posts
- **Auto-Cleanup** - Deletes original messages after successful download
- **Webhook Logging** - Tracks all downloads with media info

---

## Tech Stack

- **Python 3.12+** with asyncio
- **Discord.py 2.3.2+** for Discord API
- **OpenAI GPT-4o-mini** for AI responses
- **yt-dlp** for social media downloading
- **FFmpeg** for video compression
- **aiohttp** for async HTTP requests
- **Lanyard API** for real-time Discord presence

---

## Slash Commands

| Command | Description |
|---------|-------------|
| `/download <url>` | Download media from Instagram, Twitter/X, or TikTok |
| `/translate <text> [to]` | Translate text to another language (default: English) |
| `/languages` | Show all supported languages |

## Reply Commands

| Reply With | Description |
|------------|-------------|
| `download` | Download media from a message containing a link |
| `translate` or `tr` | Translate a message to English |
| `tr ar` or `translate arabic` | Translate a message to a specific language |

---

## Architecture

```
src/
├── bot.py                  # Main bot class and event routing
├── core/                   # Configuration and logging
│   ├── config.py           # Environment-based configuration
│   └── logger.py           # Custom tree-style logging
├── commands/               # Slash commands
│   ├── download.py         # Media download command
│   └── translate.py        # Translation command
├── handlers/               # Discord event handlers
│   ├── message.py          # AI responder + reply download
│   └── ready.py            # Bot startup and stats loop
└── services/               # Business logic
    ├── ai_service.py       # OpenAI chat integration
    ├── downloader.py       # yt-dlp + FFmpeg media downloads
    ├── translate_service.py # Google Translate integration
    └── stats_api.py        # HTTP stats API server
```

---

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/stats` | Returns guild, bot, and developer statistics |
| `GET /health` | Health check for monitoring |

### Stats Response

```json
{
  "guild": {
    "name": "...",
    "member_count": 5000,
    "online_count": 300,
    "boost_level": 3,
    "boost_count": 14
  },
  "bots": {
    "taha": {"online": true},
    "othman": {"online": true}
  },
  "developer": {
    "status": "dnd",
    "avatar": "...",
    "banner": "...",
    "activities": [...]
  }
}
```

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

<div align="center">

![Developer Avatar](images/AUTHOR.jpg)

**حَـــــنَّـــــا**

*Built for discord.gg/syria*

</div>
