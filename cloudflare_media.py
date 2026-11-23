"""Cloudflare Workers AI image generation for YouTube scenes."""
import os
import time
from pathlib import Path

import requests
from PIL import Image


def generate_cloudflare_images(data, work_dir):
    """Generate scene images, retrying transient network/server failures twice."""
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
        saved_path = None
        for attempt in range(1, 3):
            path = work / f"cloudflare_image_{index:02d}.jpg"
            path.unlink(missing_ok=True)
            try:
                response = requests.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {token}"},
                    json={"prompt": prompt, "steps": 4},
                    timeout=(10, 60),
                )
                if response.status_code in (408, 429, 500, 502, 503, 504):
                    if attempt < 2:
                        print(f"Cloudflare image {index}: temporary HTTP {response.status_code}; retrying once in 3s")
                        time.sleep(3)
                        continue
                    raise RuntimeError(f"Worker temporary HTTP {response.status_code} after 2 attempts: {response.text[:300]}")
                if not response.ok:
                    raise RuntimeError(f"Worker HTTP {response.status_code}: {response.text[:300]}")
                content_type = response.headers.get("content-type", "").lower()
                if not content_type.startswith("image/"):
                    raise RuntimeError(
                        f"Worker returned non-image response ({content_type}): {response.text[:300]}"
                    )
                if not response.content:
                    raise RuntimeError("Worker returned an empty image response")
                path.write_bytes(response.content)
                with Image.open(path) as image:
                    image.verify()
                image_paths.append(path)
                saved_path = path
                print(f"Cloudflare Workers AI image saved for scene {index}: {path.name} ({len(response.content)} bytes)")
                break
            except (requests.Timeout, requests.ConnectionError) as exc:
                path.unlink(missing_ok=True)
                if attempt < 2:
                    print(f"Cloudflare image {index}: network timeout; retrying once in 3s ({exc})")
                    time.sleep(3)
                    continue
                print(f"WARNING: Cloudflare image {index} failed after 2 attempts; fallback provider will be used: {exc}")
            except Exception as exc:
                path.unlink(missing_ok=True)
                print(f"WARNING: Cloudflare image {index} failed; fallback provider will be used: {exc}")
                break
        if saved_path is None: image_paths.append(None)
    image_paths.extend([None] * max(0, min(len(queries), 6) - len(image_paths)))
    print(f"Cloudflare Workers AI images: {sum(p is not None for p in image_paths)} / requested {min(len(queries), 6)}")
    return image_paths
