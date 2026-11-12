"""Hugging Face Inference Providers integration for AI YouTube videos."""
import os
from pathlib import Path

def _setting(name, default):
    return os.getenv(name, default).strip()

def generate_huggingface_assets(data, config, work_dir):
    """Generate scene images and one opening motion clip; gracefully fall back."""
    hf_cfg = config.get("huggingface", {})
    if not hf_cfg.get("enabled", True):
        print("Hugging Face media generation disabled.")
        return [], None
    token = _setting("HF_TOKEN", "")
    if not token:
        print("WARNING: HF_TOKEN missing; using Wikimedia/still-scene fallback.")
        return [], None
    try:
        from huggingface_hub import InferenceClient
    except ImportError as exc:
        print(f"WARNING: huggingface_hub unavailable: {exc}")
        return [], None
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    queries = data.get("visual_queries") or [data.get("title", "technology")]
    image_paths, video_path = [], None
    image_model = _setting("HF_IMAGE_MODEL", hf_cfg.get("image_model", "black-forest-labs/FLUX.1-dev"))
    video_model = _setting("HF_VIDEO_MODEL", hf_cfg.get("video_model", "Wan-AI/Wan2.2-TI2V-5B"))
    if hf_cfg.get("generate_images", True):
        client = InferenceClient(api_key=token)
        count = max(0, min(8, int(hf_cfg.get("images_per_video", 6))))
        for index, query in enumerate(queries[:count], 1):
            prompt = (f"Photorealistic cinematic documentary photograph about {query}; professional natural "
                      "lighting, clear subject, vertical 9:16 composition, no text, no captions, no watermark, no logos.")
            try:
                image = client.text_to_image(prompt=prompt, model=image_model)
                path = work / f"hf_image_{index:02d}.png"
                image.save(path)
                image_paths.append(path)
                print(f"Hugging Face image saved: {path.name}")
            except Exception as exc:
                print(f"WARNING: Hugging Face image {index} failed; fallback photo will be used: {exc}")
    if hf_cfg.get("generate_video", True):
        try:
            provider = _setting("HF_VIDEO_PROVIDER", hf_cfg.get("video_provider", "fal-ai"))
            client = InferenceClient(provider=provider, api_key=token)
            prompt = (f"Cinematic realistic documentary B-roll for a Hindi YouTube Short about "
                      f"{data.get('title', 'technology')}. Show {queries[0]}. Smooth natural camera movement, "
                      "professional lighting, vertical 9:16 framing, no text, no logos, no watermark.")
            result = client.text_to_video(prompt, model=video_model)
            video_bytes = result if isinstance(result, (bytes, bytearray)) else bytes(result)
            if not video_bytes:
                raise RuntimeError("Provider returned an empty video.")
            video_path = work / "hf_generated_clip.mp4"
            video_path.write_bytes(video_bytes)
            print(f"Hugging Face video clip saved ({len(video_bytes)} bytes).")
        except Exception as exc:
            print(f"WARNING: Hugging Face video generation failed; still scenes will be used: {exc}")
            video_path = None
    return image_paths, video_path
