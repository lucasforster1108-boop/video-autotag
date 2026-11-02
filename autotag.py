#!/usr/bin/env python3
"""
video-autotag — zero-shot auto-tagging for a local video library.

Samples a few frames from each video, scores them against an editable tag
vocabulary with CLIP (openai/clip-vit-base-patch32), and writes a sidecar
<name>.tags.json next to every video. Optionally writes one summary CSV.

Nothing leaves your machine except the one-time model download from
HuggingFace. The tags are a first draft for tools like Stash — review them
before trusting them.

Usage:
    python autotag.py <folder-or-file> [--frames 5] [--threshold 0.55]
                        [--tags tags.json] [--out-csv summary.csv]
"""

import argparse
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".ts", ".wmv", ".flv"}
MODEL_ID = "openai/clip-vit-base-patch32"


# --------------------------------------------------------------------------
# ffprobe / ffmpeg helpers
# --------------------------------------------------------------------------

def probe_video(path: Path):
    """Return (duration_sec, 'WxH') or (None, None) if ffprobe can't read it."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-show_entries", "format=duration",
        "-of", "json", str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        data = json.loads(out.stdout)
        duration = float(data["format"]["duration"])
        stream = data["streams"][0]
        return duration, f"{stream['width']}x{stream['height']}"
    except Exception:
        return None, None


def extract_frames(path: Path, duration: float, n_frames: int, out_dir: Path):
    """Grab n_frames stills, spread evenly across the video."""
    frames = []
    for i in range(n_frames):
        ts = duration * (i + 0.5) / n_frames
        out_file = out_dir / f"frame_{i:03d}.jpg"
        cmd = [
            "ffmpeg", "-v", "error", "-ss", f"{ts:.3f}", "-i", str(path),
            "-frames:v", "1", "-vf", "scale='min(640,iw)':-2",
            "-q:v", "3", str(out_file),
        ]
        subprocess.run(cmd, capture_output=True, timeout=120)
        if out_file.exists() and out_file.stat().st_size > 0:
            frames.append(out_file)
    return frames


# --------------------------------------------------------------------------
# vocabulary
# --------------------------------------------------------------------------

def load_vocabulary(tags_path: Path):
    """
    tags.json format:
        { "category": [ "label", {"label": "...", "prompt": "..."}, ... ], ... }

    Returns (categories, flat) where categories is {category: [(label, prompt)]}
    and flat is [(category, label, prompt)] in file order.
    """
    raw = json.loads(tags_path.read_text(encoding="utf-8"))
    categories, flat = {}, []
    for category, entries in raw.items():
        items = []
        for entry in entries:
            if isinstance(entry, str):
                label, prompt = entry, entry
            else:
                label = entry["label"]
                prompt = entry.get("prompt", label)
            items.append((label, prompt))
            flat.append((category, label, prompt))
        categories[category] = items
    return categories, flat


# --------------------------------------------------------------------------
# CLIP scoring
# --------------------------------------------------------------------------

class Tagger:
    def __init__(self):
        # Imported here so --help and probing work without torch installed.
        import torch
        from transformers import CLIPModel, CLIPProcessor

        self.torch = torch
        print(f"Loading {MODEL_ID} (first run downloads ~600 MB) ...", file=sys.stderr)
        self.model = CLIPModel.from_pretrained(MODEL_ID)
        self.processor = CLIPProcessor.from_pretrained(MODEL_ID)
        self.model.eval()

    def score_frames(self, frame_paths, categories):
        """
        Per-category softmax per frame, then max across frames.

        Scores are computed inside each category (indoor vs outdoor compete,
        close-up vs wide shot compete), which keeps the numbers meaningful —
        a flat softmax over the whole vocabulary would squash everything.
        """
        torch = self.torch
        from PIL import Image

        prompts = [prompt for items in categories.values() for _, prompt in items]
        images = [Image.open(p).convert("RGB") for p in frame_paths]
        inputs = self.processor(text=prompts, images=images,
                                return_tensors="pt", padding=True)
        with torch.no_grad():
            # logits_per_image is [frames, labels] and already logit-scaled.
            # (get_text_features()/get_image_features() changed return types
            # across transformers versions; the forward output is stable.)
            logits = self.model(**inputs).logits_per_image

        scores = {}  # label -> best score across frames
        offset = 0
        for category, items in categories.items():
            k = len(items)
            cat_logits = logits[:, offset:offset + k]
            probs = cat_logits.softmax(dim=-1)
            best = probs.max(dim=0).values.tolist()
            for (label, _), score in zip(items, best):
                scores[label] = round(float(score), 4)
            offset += k
        return scores


# --------------------------------------------------------------------------
# main pipeline
# --------------------------------------------------------------------------

def collect_videos(target: Path):
    if target.is_file():
        return [target] if target.suffix.lower() in VIDEO_EXTS else []
    return sorted(p for p in target.rglob("*")
                  if p.is_file() and p.suffix.lower() in VIDEO_EXTS)


def tag_one(video: Path, tagger: Tagger, categories, n_frames: int, threshold: float):
    duration, resolution = probe_video(video)
    if duration is None:
        print(f"  skip (ffprobe can't read it): {video}", file=sys.stderr)
        return None

    with tempfile.TemporaryDirectory() as tmp:
        frames = extract_frames(video, duration, n_frames, Path(tmp))
        if not frames:
            print(f"  skip (no frames extracted): {video}", file=sys.stderr)
            return None
        scores = tagger.score_frames(frames, categories)

    label_to_cat = {label: cat for cat, items in categories.items() for label, _ in items}
    tags = [
        {"label": label, "category": label_to_cat[label], "score": score}
        for label, score in sorted(scores.items(), key=lambda kv: -kv[1])
        if score >= threshold
    ]

    sidecar = {
        "file": video.name,
        "duration_sec": round(duration, 2),
        "resolution": resolution,
        "frames_sampled": len(frames),
        "model": MODEL_ID,
        "threshold": threshold,
        "tags": tags,
        "all_scores": scores,
    }
    out_path = video.with_suffix(".tags.json")
    # with_suffix replaces .mp4; for names like a.b.mp4 it gives a.b.tags.json — fine
    out_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8")
    return sidecar


def main():
    ap = argparse.ArgumentParser(
        description="Zero-shot auto-tagging for a local video library (CLIP + ffmpeg).")
    ap.add_argument("target", help="a video file or a folder (searched recursively)")
    ap.add_argument("--frames", type=int, default=5,
                    help="frames sampled per video (default 5)")
    ap.add_argument("--threshold", type=float, default=0.55,
                    help="minimum score for a tag to be kept (default 0.55)")
    ap.add_argument("--tags", default=str(Path(__file__).with_name("tags.json")),
                    help="path to the tag vocabulary JSON (default: tags.json next to this script)")
    ap.add_argument("--out-csv", default=None,
                    help="optional summary CSV path")
    args = ap.parse_args()

    target = Path(args.target)
    if not target.exists():
        sys.exit(f"no such file or folder: {target}")

    categories, _ = load_vocabulary(Path(args.tags))
    videos = collect_videos(target)
    if not videos:
        sys.exit("no video files found")
    print(f"{len(videos)} video(s), vocabulary: "
          f"{sum(len(v) for v in categories.values())} labels in {len(categories)} categories")

    tagger = Tagger()
    rows = []
    for video in videos:
        print(f"- {video}")
        result = tag_one(video, tagger, categories, args.frames, args.threshold)
        if result is None:
            continue
        rows.append({
            "file": str(video),
            "duration_sec": result["duration_sec"],
            "resolution": result["resolution"],
            "tags": "; ".join(t["label"] for t in result["tags"]),
        })
        print(f"  tags: {rows[-1]['tags'] or '(none above threshold)'}")

    if args.out_csv:
        with open(args.out_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["file", "duration_sec", "resolution", "tags"])
            writer.writeheader()
            writer.writerows(rows)
        print(f"summary written to {args.out_csv}")
    print(f"done: {len(rows)}/{len(videos)} video(s) tagged")


if __name__ == "__main__":
    main()
