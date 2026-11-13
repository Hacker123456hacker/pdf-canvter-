"""Cloudflare Workers AI image generation for YouTube scenes."""
import os
from pathlib import Path

import requests
from PIL import Image


def generate_cloudflare_images(data, work_dir):
    """Generate up to 8 scene images through a secured Cloudflare Worker."""
    endpoint = os.getenv("CLOUDFLARE_IMAGE_WORKER_URL", "").strip()
    token = os.getenv("CLOUDFLARE_IMAGE_TOKEN", "").strip()
    if not endpoint or not token:
        print("Cloudflare Workers AI not configured; using existing image providers.")
        return []

    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    queries = data.get("visual_queries") or [data.get("title", "documentary scene")]
    image_paths = []
    for index, query in enumerate(queries[:8], 1):
        prompt = (
            f"Photorealistic cinematic documentary photograph about {query}. "
            "Accurate real-world details, professional natural lighting, clear main subject, "
            "vertical 9:16 composition, no text, no captions, no watermark, no logos."
        )
        try:
            response = requests.post(
                endpoint,
                headers={"Authorization": f"Bearer {token}"},
                json={"prompt": prompt, "steps": 4},
                timeout=(15, 120),
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if not content_type.startswith("image/"):
                raise RuntimeError(f"Worker returned non-image response: {response.text[:300]}")
            path = work / f"cloudflare_image_{index:02d}.jpg"
            path.write_bytes(response.content)
            with Image.open(path) as image:
                image.verify()
            image_paths.append(path)
            print(f"Cloudflare Workers AI image saved: {path.name} ({len(response.content)} bytes)")
        except Exception as exc:
            print(f"WARNING: Cloudflare image {index} failed; fallback provider will be used: {exc}")
    print(f"Cloudflare Workers AI images: {len(image_paths)} / requested {min(len(queries), 8)}")
    return image_paths
