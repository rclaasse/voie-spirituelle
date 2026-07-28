import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


PROFILE_URL = "https://www.instagram.com/spiritualitymc/"
VIDEOS_FILE = Path("videos.json")
MAX_VIDEOS = 30

APIFY_ENDPOINT = (
    "https://api.apify.com/v2/actors/"
    "apify~instagram-scraper/"
    "run-sync-get-dataset-items"
)


def extract_shortcode(url: str) -> str:
    """Extrait le code Instagram depuis une URL /reel/CODE/."""
    path_parts = [
        part
        for part in urlparse(url).path.split("/")
        if part
    ]

    if len(path_parts) >= 2 and path_parts[0] in {
        "reel",
        "reels",
        "p",
        "tv",
    }:
        return path_parts[1]

    return ""


def normalize_instagram_url(item: dict) -> str:
    """Trouve l’URL permanente dans les différents champs Apify possibles."""
    possible_urls = [
        item.get("url"),
        item.get("postUrl"),
        item.get("permalink"),
        item.get("inputUrl"),
    ]

    for value in possible_urls:
        if (
            isinstance(value, str)
            and "instagram.com/" in value
            and any(
                marker in value
                for marker in ("/reel/", "/reels/")
            )
        ):
            return value.split("?")[0].rstrip("/") + "/"

    shortcode = (
        item.get("shortCode")
        or item.get("shortcode")
        or item.get("code")
    )

    if isinstance(shortcode, str) and shortcode.strip():
        return (
            "https://www.instagram.com/reel/"
            f"{shortcode.strip()}/"
        )

    return ""


def load_existing_videos() -> list[dict]:
    if not VIDEOS_FILE.exists():
        return []

    try:
        with VIDEOS_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        return data if isinstance(data, list) else []

    except (json.JSONDecodeError, OSError) as error:
        raise RuntimeError(
            f"Impossible de lire {VIDEOS_FILE}: {error}"
        ) from error


def fetch_latest_reels(token: str) -> list[dict]:
    actor_input = {
        "resultsType": "reels",
        "directUrls": [PROFILE_URL],
        "resultsLimit": 10,
        "addParentData": False,
    }

    request = urllib.request.Request(
        APIFY_ENDPOINT,
        data=json.dumps(actor_input).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=300,
        ) as response:
            result = json.loads(
                response.read().decode("utf-8")
            )

    except urllib.error.HTTPError as error:
        error_body = error.read().decode(
            "utf-8",
            errors="replace",
        )
        raise RuntimeError(
            f"Erreur Apify HTTP {error.code}: {error_body}"
        ) from error

    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Impossible de joindre Apify: {error}"
        ) from error

    if not isinstance(result, list):
        raise RuntimeError(
            "La réponse Apify n’est pas une liste."
        )

    reels: list[dict] = []
    seen_ids: set[str] = set()

    for item in result:
        if not isinstance(item, dict):
            continue

        url = normalize_instagram_url(item)

        if not url:
            continue

        shortcode = extract_shortcode(url)

        if not shortcode or shortcode in seen_ids:
            continue

        seen_ids.add(shortcode)

        reel = {
            "id": shortcode,
            "url": url,
        }

        timestamp = (
            item.get("timestamp")
            or item.get("takenAt")
            or item.get("date")
        )

        if isinstance(timestamp, str) and timestamp:
            reel["date"] = timestamp

        reels.append(reel)

    return reels


def merge_videos(
    latest_reels: list[dict],
    existing_videos: list[dict],
) -> list[dict]:
    merged_by_id: dict[str, dict] = {}

    for video in existing_videos + latest_reels:
        if not isinstance(video, dict):
            continue

        url = video.get("url", "")
        video_id = video.get("id") or extract_shortcode(url)

        if not video_id or not url:
            continue

        normalized = {
            "id": video_id,
            "url": url,
        }

        if video.get("date"):
            normalized["date"] = video["date"]

        merged_by_id[video_id] = normalized

    merged = list(merged_by_id.values())

    merged.sort(
        key=lambda video: video.get("date", ""),
        reverse=True,
    )

    return merged[:MAX_VIDEOS]

def main() -> int:
    token = os.environ.get("APIFY_TOKEN", "").strip()

    if not token:
        print(
            "Erreur : le secret APIFY_TOKEN est absent.",
            file=sys.stderr,
        )
        return 1

    existing_videos = load_existing_videos()
    latest_reels = fetch_latest_reels(token)

    if not latest_reels:
        print(
            "Aucun Reel récupéré. "
            "videos.json n’a pas été modifié."
        )
        return 0

    updated_videos = merge_videos(
        latest_reels,
        existing_videos,
    )

    if updated_videos == existing_videos:
        print("Aucun nouveau Reel.")
        return 0

    with VIDEOS_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            updated_videos,
            file,
            ensure_ascii=False,
            indent=2,
        )
        file.write("\n")

    existing_ids = {
        video.get("id")
        for video in existing_videos
        if isinstance(video, dict)
    }

    new_ids = [
        reel["id"]
        for reel in latest_reels
        if reel["id"] not in existing_ids
    ]

    print(
        f"{len(new_ids)} nouveau(x) Reel(s) détecté(s)."
    )
    print("videos.json a été mis à jour.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())