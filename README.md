# TileMap Downloader

## Installation
1. Python 3.6+
2. `pip install requests`

## Usage
1. `python tile_downloader.py --list-regions` - List regions
2. `python tile_downloader.py qatar` - Download specific region
3. `python server.py` - Start server
4. `http://localhost:8000/index.html` - Open in browser

## Configuration
Edit regions and settings in `config.json`:
- Region coordinates (bbox)
- Zoom levels
- Server list
- Download settings

## Files
- `tile_downloader.py` - Config-based downloader
- `server.py` - Web server
- `index.html` - Map viewer
- `config.json` - Region and server settings
