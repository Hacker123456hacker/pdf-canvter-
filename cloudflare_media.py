"""Cloudflare Workers AI image generation for YouTube scenes."""
import os
import time
from pathlib import Path

import requests
from PIL import Image


def generate_cloudflare_images(data, work_dir):
    """Generate scene images through a secured Cloudflare Worker, retrying transient failures."""
    endpoint = os.getenv("CLOUDFLARE_IMAGE_WORKER_URL", "").strip()
    token = os.getenv("CLOUDFLARE_IMAGE_TOKEN", "").strip()
    if not endpoint or not token:
        print("Cloudflare Workers AI not configured; using existing image providers.")
        return []

    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    queries = data.get("visual_queries") or [data.get("title", "documentary scene")]
    image_paths = []
    for index, query in enumerate(queries[:6], 1):
        prompt = (
            f"Photorealistic cinematic documentary photograph about {query}. "
            "Accurate real-world details, professional natural lighting, clear main subject, "
            "vertical 9:16 composition, no text, no captions, no watermark, no logos."
        )
        for attempt in range(1):
            try:
                response = requests.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {token}"},
                    json={"prompt": prompt, "steps": 4},
                    timeout=(10, 60),
                )
                if response.status_code in (429, 500, 502, 503, 504) and attempt < 0:
                    print(
                        f"Cloudflare image {index}: temporary HTTP {response.status_code}; "
                        f"retry {attempt + 1}/2"
                    )
                    time.sleep(2 ** (attempt + 1))
                    continue
                if not response.ok:
                    detail = response.text[:500].replace("\\n", " ")
                    raise RuntimeError(f"Worker HTTP {response.status_code}: {detail}")
                content_type = response.headers.get("content-type", "").lower()
                if not content_type.startswith("image/"):
                    raise RuntimeError(
                        f"Worker returned non-image response ({content_type}): "
                        f"{response.text[:500]}"
                    )
                path = work / f"cloudflare_image_{index:02d}.jpg"
                path.write_bytes(response.content)
                with Image.open(path) as image:
                    image.verify()
                image_paths.append(path)
                print(f"Cloudflare Workers AI image saved: {path.name} ({len(response.content)} bytes)")
                break
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt < 0:
                    print(f"Cloudflare image {index}: connection/timeout; retry {attempt + 1}/2 ({exc})")
                    time.sleep(2 ** (attempt + 1))
                    continue
                print(f"WARNING: Cloudflare image {index} failed after retries; fallback provider will be used: {exc}")
            except Exception as exc:
                print(f"WARNING: Cloudflare image {index} failed; fallback provider will be used: {exc}")
                break
    print(f"Cloudflare Workers AI images: {len(image_paths)} / requested {min(len(queries), 6)}")
    return image_paths
