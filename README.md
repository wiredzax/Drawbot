Readme.md
# Drawbot

Drawbot is a Discord bot that generates images using a ComfyUI API. It supports text-to-image generation, image-to-image transformations, depth map creation, collaborative canvas editing, and user stats tracking across guilds. This is a framework for you to customize with your own ComfyUI supported models and workflows—see the configuration section below!

## Features
- **Text-to-Image**: Generate images from text prompts with `draw`.
- **Image-to-Image**: Transform images with `img2img`, `!upscale`, or `!inpaint`.
- **Depth Maps**: Create depth maps from images with `!depth`.
- **Collaborative Canvas**: Edit a shared canvas with `!startcanvas` and `!addcanvas`.
- **Stats & Leaderboards**: Track usage with `!stats` and `!leaderboard`.
- **Custom Models**: Configure your own ComfyUI models for generation.

## Prerequisites
- **Python**: Version 3.8 or higher.
- **ComfyUI Server**: A running instance of [ComfyUI](https://github.com/comfyanonymous/ComfyUI) for image generation.
- **Discord Bot Token**: Obtain from the [Discord Developer Portal](https://discord.com/developers/applications).
- **Git**: For cloning the repository.
- **Other**: requirements.txt Is included for all other dependencies needed for the bot.

## Installation
Follow these steps to set up Drawbot on your system:

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/wiredzax/Drawbot.git
   cd Drawbot

2. make a venv
   ```
   py -m venv [venv] & activate venv & pip install -r requirements.txt

3. Copy .env.example to .env and edit:

   ```
   cp .env.example .env

Edit .env with your settings
   ```
DISCORD_BOT_TOKEN=your_discord_bot_token_here
COMFYUI_API_URL=http://127.0.0.1:8188  # Your ComfyUI server URL
PREFERENCES_FILE=user_preferences.json
DB_PATH=guild_stats.db
WORKFLOWS_PATH=workflows
IMAGE_OUTPUT_PATH=generated_images
API_TIMEOUT=120
MAX_BATCH_SIZE=5
VRAM_THRESHOLD_GB=20
STATIC_WIDTH=1024
STATIC_HEIGHT=1024
MAX_IMAGE_DIMENSION=3000
ADMIN_ROLE_ID=your_role_id_here
```

4. Configure ComfyUI Models:
   - Edit config/available_models.py to add your ComfyUI model names and filenames:
```python
# config/available_models.py
# Note: These are placeholders. Replace with your own ComfyUI model names and filenames.
AVAILABLE_MODELS = {
    "your_model_name": "your_model_filename.safetensors",
    "another_model": "another_model_file.safetensors",
    # Add more as needed
}
```
   - Syntax: 
   Keys are model names users can specify (e.g., `draw a cat model:your_model_name`), and values are the exact filenames in your ComfyUI models/checkpoints/ directory.
   
   I have supplied some model names that can be found online in the "available_models.py file, if you do not have those files please add your own.

Update config/default_model.py to set the default model (must match a key from AVAILABLE_MODELS):

```python
# config/default_model.py
DEFAULT_MODEL = "your_model_name"
```
5. Run the Bot:

   -Ensure your ComfyUI server is running (default: http://127.0.0.1:8188).

   -Start the bot:

   ```bash
   python main.py

## Usage
Once the bot is running and added to your Discord server, try these commands:

**`draw <prompt>`**: Generate an image from a text prompt.  
- Example: draw a cat  
- With model: draw a cat model:your_model_name
- With parameters: draw a cat steps:50 cfg:7.5

**`img2img`**: Transform an attached or replied-to image.  
- Example: Simply upload an image and `<prompt>` as a message or reply to an image with `<prompt>` ex. a futuristic city to make an image  

**`!upscale`**: Upscale an attached or replied-to image.  
 - Example: Reply to an image with !upscale  

**`!inpaint <prompt>`**: Edit an image with a mask (white areas edited).  
 - Example: Reply to an image, attach a mask, and type !inpaint a dragon  

**`!depth`**: Generate a depth map from an attached or replied-to image.  
 - Example: Attach an image and type !depth colorize:yes method:spectral  

**`!startcanvas <prompt>`**: Start a collaborative canvas.  
 - Example: !startcanvas a forest  

**`!addcanvas <prompt>`**: Add to the canvas with a mask.  
 - Example: Attach a mask and type !addcanvas a river  

**`!showcanvas`**: Display the current canvas.  

**`!stats`**: View your generation stats (images, time, etc.).  

**`!leaderboard`**: See the top creators in your guild.  

**`!models`**: List available model names from AVAILABLE_MODELS.  

- **Admin Commands**: Guild owners or the bot owner can run these initially:

  - **`!addadmin <user>`**: Add an admin to `admins.json` (first run this as guild/bot owner).

  - **`!removeadmin <user>`**: Remove an admin from `admins.json`.

  - **`!listadmins`**: List admins in `admins.json`.

  - **`!reload [cog]`**: Reload a cog or all cogs.

  - **`!shutdown`**: Shut down the bot.

## Configuration

- **Models**: Customize `config/available_models.py` with your ComfyUI models.

- **Parameters**: Adjust settings via `.env` (e.g., `STATIC_WIDTH`, `MAX_BATCH_SIZE`) or per-command (e.g., `steps:50`).

- **Admin Role**: Set `ADMIN_ROLE_ID` in `.env` to a Discord role ID. Users with this role gain admin privileges.

- **Workflows**: Place your ComfyUI workflow YAML files in the `workflows/` directory.

## Notes
**ComfyUI Dependency**: You must have a ComfyUI server running with compatible models. The placeholders in available_models.py are examples—replace them with your own.

**VRAM Monitoring**: The bot checks GPU VRAM usage (requires gputil) and aborts if it exceeds VRAM_THRESHOLD_GB.

**Stats**: Guild-specific stats are stored in guild_stats.db (excluded from the repo).

**Guild limit**: This bot is not coded in such a way that it will not work with Discord's API limits for bots. Discord does limit the bot intents after you reach their "max guild" mark, please refer to Discord's Developer portal for more information. 
Other aspects of how the bot saves stats and prefrences will also need to be changed if you are reaching the limits of what the code can do. 
SQLite3 is used to store stats on images prompted, total generation time, etc. This can be a bottleneck.  

## Contributing

Feel free to fork this repo, make improvements, and submit pull requests! Report issues or suggestions in the GitHub Issues tab.

## License

This project is licensed under the MIT License—see the LICENSE file for details.

## Acknowledgments

Built with [discord.py](https://github.com/Rapptz/discord.py) and [ComfyUI](https://github.com/comfyanonymous/ComfyUI).
