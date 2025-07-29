import requests
import os
import time
import math
import json
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import random

# --- CONFIGURATION ---

def load_config(config_file="config.json"):
    """Load configuration from JSON file."""
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Config file {config_file} not found!")
        return None
    except json.JSONDecodeError:
        print(f"Invalid JSON in {config_file}!")
        return None

# --- TILE SERVERS ---

TILE_SERVERS = [
    {
        'name': 'CartoDB Light',
        'url': 'https://cartodb-basemaps-a.global.ssl.fastly.net/light_all/{z}/{x}/{y}.png',
        'headers': {'User-Agent': 'Multi-Tile-Downloader/1.0'},
    },
    {
        'name': 'CartoDB Dark',
        'url': 'https://cartodb-basemaps-b.global.ssl.fastly.net/dark_all/{z}/{x}/{y}.png',
        'headers': {'User-Agent': 'Multi-Tile-Downloader/1.0'},
    },
    {
        'name': 'Stamen Terrain',
        'url': 'https://stamen-tiles.a.ssl.fastly.net/terrain/{z}/{x}/{y}.png',
        'headers': {'User-Agent': 'Multi-Tile-Downloader/1.0'},
    },
    {
        'name': 'Stamen Watercolor',
        'url': 'https://stamen-tiles.a.ssl.fastly.net/watercolor/{z}/{x}/{y}.png',
        'headers': {'User-Agent': 'Multi-Tile-Downloader/1.0'},
    }
]

# --- HELPER FUNCTIONS ---

def deg2num(lat_deg, lon_deg, zoom):
    """Convert lat/lon to tile coordinates."""
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return xtile, ytile

def get_tiles_for_bbox(bbox, min_zoom, max_zoom):
    """Get all tile coordinates for given bbox and zoom range."""
    tiles = []
    min_lon, min_lat, max_lon, max_lat = bbox
    
    print("Calculating tile coordinates...")
    for zoom in range(min_zoom, max_zoom + 1):
        print(f"  Processing zoom level {zoom}...")
        min_x, max_y = deg2num(min_lat, min_lon, zoom)
        max_x, min_y = deg2num(max_lat, max_lon, zoom)
        
        zoom_tiles = 0
        for x in range(min_x, max_x + 1):
            for y in range(min_y, max_y + 1):
                tiles.append((zoom, x, y))
                zoom_tiles += 1
        
        print(f"    Zoom {zoom}: {zoom_tiles} tiles")
    
    return tiles

def create_session():
    """Create optimized session for downloads."""
    session = requests.Session()
    
    retry_strategy = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=20,
        pool_maxsize=20
    )
    
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session

# --- DOWNLOAD FUNCTIONS ---

def download_tile_from_server(tile_info, server, output_dir, retry_attempts=3, timeout=30):
    """Download a single tile from a specific server."""
    zoom, x, y = tile_info
    tile_url = server['url'].format(z=zoom, x=x, y=y)
    
    # Create directory structure
    tile_path = os.path.join(output_dir, server['name'], str(zoom), str(x))
    os.makedirs(tile_path, exist_ok=True)
    tile_filename = os.path.join(tile_path, f"{y}.png")

    # Skip if exists
    if os.path.exists(tile_filename):
        return f"Exists: {server['name']}/{zoom}/{x}/{y}"

    # Download with retry
    for attempt in range(retry_attempts):
        try:
            if attempt > 0:
                time.sleep(0.5 * attempt)
            
            session = create_session()
            response = session.get(tile_url, headers=server['headers'], timeout=timeout)
            response.raise_for_status()

            with open(tile_filename, 'wb') as f:
                f.write(response.content)
            
            return f"Downloaded: {server['name']}/{zoom}/{x}/{y}"

        except Exception as e:
            if attempt == retry_attempts - 1:
                return f"Error: {server['name']}/{zoom}/{x}/{y} - {e}"
            time.sleep(1.0)

def download_tile_multi_server(tile_info, config):
    """Download tile from multiple servers, use first successful result."""
    zoom, x, y = tile_info
    
    # Get enabled servers from config
    enabled_servers = [s for s in TILE_SERVERS if s['name'] in config['servers']]
    
    # Try each server until one succeeds
    for server in enabled_servers:
        result = download_tile_from_server(
            tile_info, 
            server, 
            config['output_dir'],
            config['retry_attempts'],
            config['timeout']
        )
        if "Downloaded:" in result or "Exists:" in result:
            return result
    
    # If all servers fail, return last error
    return f"All servers failed: {zoom}/{x}/{y}"

def check_existing_tiles(tiles, config):
    """Count existing tiles across all servers."""
    existing = 0
    enabled_servers = [s for s in TILE_SERVERS if s['name'] in config['servers']]
    
    for zoom, x, y in tiles:
        for server in enabled_servers:
            tile_path = os.path.join(config['output_dir'], server['name'], str(zoom), str(x), f"{y}.png")
            if os.path.exists(tile_path):
                existing += 1
                break  # Found in one server, no need to check others
    return existing

# --- MAIN FUNCTION ---

def download_region(region_name, config):
    """Download tiles for a specific region."""
    if region_name not in config['regions']:
        print(f"Region '{region_name}' not found in config!")
        print(f"Available regions: {list(config['regions'].keys())}")
        return False
    
    region = config['regions'][region_name]
    bbox = region['bbox']
    min_zoom = region['min_zoom']
    max_zoom = region['max_zoom']
    
    print(f"=== Downloading {region_name.upper()} ===")
    print(f"Bounding Box: {bbox}")
    print(f"Zoom Levels: {min_zoom} to {max_zoom}")
    print(f"Output Directory: {config['output_dir']}")
    print(f"Enabled Servers: {config['servers']}")
    print()
    
    # Get all tiles to download
    print("Calculating tiles...")
    all_tiles = get_tiles_for_bbox(bbox, min_zoom, max_zoom)
    total_tiles = len(all_tiles)
    
    print(f"Total tiles to download: {total_tiles}")
    
    # Check existing tiles
    existing = check_existing_tiles(all_tiles, config)
    print(f"Existing tiles: {existing}")
    print(f"Remaining to download: {total_tiles - existing}")
    print()
    
    if total_tiles == 0:
        print("No tiles to download!")
        return False
    
    # Calculate total workers
    total_workers = len(config['servers']) * config['max_workers_per_server']
    print(f"Total concurrent workers: {total_workers}")
    print()
    
    # Start download
    print("Starting multi-server download...")
    print("=" * 50)
    
    with ThreadPoolExecutor(max_workers=total_workers) as executor:
        futures = [executor.submit(download_tile_multi_server, tile, config) for tile in all_tiles]
        
        completed = 0
        for future in as_completed(futures):
            completed += 1
            result = future.result()
            
            # Progress update every 100 tiles
            if completed % 100 == 0 or completed == total_tiles:
                progress = (completed / total_tiles) * 100
                print(f"Progress: {completed}/{total_tiles} ({progress:.1f}%) - {result}")
    
    print("=" * 50)
    print("Multi-server download completed!")
    print(f"Tiles saved to: {config['output_dir']}")
    
    # Final check
    final_existing = check_existing_tiles(all_tiles, config)
    print(f"Successfully downloaded: {final_existing}/{total_tiles} tiles")
    
    # Show results by server
    print("\nResults by server:")
    for server in TILE_SERVERS:
        if server['name'] in config['servers']:
            server_tiles = 0
            for zoom, x, y in all_tiles:
                tile_path = os.path.join(config['output_dir'], server['name'], str(zoom), str(x), f"{y}.png")
                if os.path.exists(tile_path):
                    server_tiles += 1
            print(f"  {server['name']}: {server_tiles} tiles")
    
    return True

def main():
    """Main function with command line arguments."""
    parser = argparse.ArgumentParser(description='Download map tiles for specified regions')
    parser.add_argument('region', nargs='?', help='Region name to download (e.g., qatar, ankara)')
    parser.add_argument('--config', default='config.json', help='Config file path')
    parser.add_argument('--list-regions', action='store_true', help='List available regions')
    
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.config)
    if not config:
        return
    
    # List regions if requested
    if args.list_regions:
        print("Available regions:")
        for name, region in config['regions'].items():
            print(f"  {name}: {region['description']}")
        return
    
    # Download specific region
    if args.region:
        download_region(args.region, config)
    else:
        print("Please specify a region name or use --list-regions to see available regions")
        print("Example: python tile_downloader.py qatar")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDownload interrupted by user.")
    except Exception as e:
        print(f"\nError: {e}")
        print("Please check your configuration and try again.")

# --- USAGE INSTRUCTIONS ---
"""
Config-based Tile Downloader Usage:

1. Edit config.json to add your regions and settings
2. Run with specific region:
   python tile_downloader.py qatar
   
3. List available regions:
   python tile_downloader.py --list-regions
   
4. Use custom config file:
   python tile_downloader.py ankara --config my_config.json
""" 