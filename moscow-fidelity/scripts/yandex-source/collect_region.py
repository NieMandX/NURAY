#!/usr/bin/env python3
"""Collect public vmap3 containers using a configuration observed in Maps.

The container zoom is not the display detail: Maps uses z=15 containers
for the inclusive 15..21 display range. Never silently lower zmax on error.
Raw data, source configuration and manifests belong outside Git.
"""
import argparse
import concurrent.futures
import hashlib
import json
import math
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

from pyproj import Geod, Transformer
from shapely.geometry import Polygon, box

WORLD_HALF = math.pi * 6378137.0


def make_plan(lon, lat, radius, margin, zoom=15):
    geod = Geod(ellps="WGS84")
    project = Transformer.from_crs("EPSG:4326", "EPSG:3395", always_xy=True)
    ring = [geod.fwd(lon, lat, azimuth, radius + margin)[:2]
            for azimuth in range(360)]
    region = Polygon([project.transform(*point) for point in ring])
    size = WORLD_HALF * 2 / (2 ** zoom)
    left, bottom, right, top = region.bounds
    tiles = []
    for y in range(math.floor((WORLD_HALF - top) / size),
                   math.floor((WORLD_HALF - bottom) / size) + 1):
        for x in range(math.floor((left + WORLD_HALF) / size),
                       math.floor((right + WORLD_HALF) / size) + 1):
            tile = box(x * size - WORLD_HALF, WORLD_HALF - (y + 1) * size,
                       (x + 1) * size - WORLD_HALF, WORLD_HALF - y * size)
            if tile.intersects(region):
                tiles.append({"x": x, "y": y, "z": zoom,
                              "path": f"tiles/{zoom}-{x}-{y}.vmap3"})
    return {"centerLonLat": [lon, lat], "radiusMetres": radius,
            "captureMarginMetres": margin, "sourceCRS": "EPSG:3395",
            "displayZoom": 21, "containerZoom": zoom,
            "zmin": 15, "zmaxInclusive": 21, "tiles": tiles}


def tile_url(config, version, tile):
    url = config["vectorVmap3TilesTmpl"]
    values = {**tile, "rendererTiles": config["rendererTiles"],
              "lang": "ru_RU", "version": version, "zmin": 15, "zmax": 21}
    for key, value in values.items():
        url = url.replace("{{" + key + "}}", str(value))
    if "{{" in url:
        raise ValueError("Unresolved source parameter")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "core-renderer-tiles.maps.yandex.ru":
        raise ValueError("Unexpected source host")
    return url


def collect_one(root, config, version, tile):
    path = root / tile["path"]
    proof_path = path.with_suffix(".json")
    url = tile_url(config, version, tile)
    if path.exists() and proof_path.exists():
        proof = json.loads(proof_path.read_text())
        data = path.read_bytes()
        if proof.get("url") == url and hashlib.sha256(data).hexdigest() == proof.get("sha256"):
            return proof
    request = urllib.request.Request(url, headers={"Accept": "application/x-protobuf"})
    # Retry transient transfers only; don't hide a rejected or invalid request.
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                content_type = response.headers.get("Content-Type", "")
                if response.status != 200 or "protobuf" not in content_type:
                    raise ValueError(f"Unexpected tile response: {response.status} {content_type}")
                data = response.read(16 * 1024 * 1024 + 1)
                if len(data) > 16 * 1024 * 1024:
                    raise ValueError("Tile exceeds capture size guard")
            break
        except urllib.error.HTTPError:
            raise
        except (TimeoutError, urllib.error.URLError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    proof = {**tile, "url": url, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
             "contentType": content_type}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".part")
    temporary.write_bytes(data)
    temporary.replace(path)
    proof_path.write_text(json.dumps(proof, indent=2) + "\n")
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observed-config", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--radius", type=float, default=3000)
    parser.add_argument("--margin", type=float, default=100)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    if not (-180 <= args.lon <= 180 and -85 < args.lat < 85 and
            0 < args.radius <= 10000 and 0 <= args.margin <= 1000):
        parser.error("Invalid geographic extent")
    config = json.loads(args.observed_config.read_text())
    plan = make_plan(args.lon, args.lat, args.radius, args.margin)
    plan["sourceVersion"] = args.version
    root = args.output
    root.mkdir(parents=True, exist_ok=True)
    plan_path = root / "plan.json"
    if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
        raise ValueError("Capture directory already contains a different plan")
    plan_path.write_text(json.dumps(plan, indent=2) + "\n")
    (root / "source-config.json").write_text(json.dumps(config, indent=2) + "\n")
    print(f"Plan: {len(plan['tiles'])} containers; detail through zoom 21; radius {args.radius} m", flush=True)
    if not args.download:
        return
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(collect_one, root, config, args.version, tile) for tile in plan["tiles"]]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
            if len(results) % 10 == 0:
                print(f"Captured {len(results)}/{len(plan['tiles'])}", flush=True)
    results.sort(key=lambda item: (item["y"], item["x"]))
    manifest = {"complete": len(results) == len(plan["tiles"]),
                "source": "Yandex Maps vmap3", "sourceVersion": args.version,
                "bytes": sum(item["bytes"] for item in results), "files": results}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Complete: {manifest['bytes']} bytes", flush=True)


if __name__ == "__main__":
    main()
