**English** | [简体中文](README_zh.md) | [日本語](README_ja.md) | [한국어](README_ko.md)

# video-autotag — first-pass tags for a video library, without watching every file

My local library kept growing and my tagging discipline didn't. Hundreds of files, most of them named like `final_v2.mp4`, and library tools like Stash are only as good as the tags you feed them — which I never got around to typing in.

So I wrote the lazy version: point this at a folder, it watches a few frames of each video for you and writes down what it saw. Not final tags — a first draft you can skim and fix, instead of a blank page.

## How it works

1. **ffmpeg** pulls N stills spread evenly across each video (ffprobe gets the duration and resolution first).
2. **CLIP** (`openai/clip-vit-base-patch32`, running locally via transformers) scores every frame against a tag vocabulary — plain zero-shot classification, no training, no API key.
3. Scores inside one category compete with each other (indoor vs outdoor, close-up vs wide shot), each frame votes, and I keep the **best score per label across frames**. Anything at or above the threshold lands in the output.

For every video you get a sidecar file, `movie.mp4` → `movie.tags.json`:

```json
{
  "file": "dark_text.mp4",
  "duration_sec": 6.0,
  "resolution": "640x360",
  "frames_sampled": 5,
  "model": "openai/clip-vit-base-patch32",
  "threshold": 0.55,
  "tags": [
    {"label": "indoor", "category": "setting", "score": 0.9634},
    {"label": "dark lighting", "category": "lighting", "score": 0.8482}
  ],
  "all_scores": { "indoor": 0.9634, "outdoor": 0.0001, "...": "..." }
}
```

That example is real output, from a synthetic test clip (black frames, white text). `all_scores` keeps every label's score, not just the winners, so you can re-threshold later without re-running the model.

## Install

You need Python 3.10+ and ffmpeg/ffprobe on your PATH.

```bash
# CPU-only torch first — much smaller than the default CUDA build
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

The first run downloads the CLIP model from HuggingFace (about 580 MB, one time). After that everything runs offline, on CPU, on your machine. Nothing about your library leaves the box.

## Usage

```bash
# a whole folder (recursive), sidecars next to each video
python autotag.py /path/to/library

# one file, pickier threshold, more frames
python autotag.py movie.mp4 --frames 8 --threshold 0.7

# plus one summary CSV for the whole run
python autotag.py /path/to/library --out-csv summary.csv
```

| Flag | Default | What it does |
|---|---|---|
| `--frames` | 5 | stills sampled per video |
| `--threshold` | 0.55 | minimum score for a tag to be kept |
| `--tags` | `tags.json` next to the script | vocabulary file to use |
| `--out-csv` | off | write a summary CSV (file, duration, resolution, tags) |

## Make the vocabulary yours

`tags.json` is the whole personality of this tool. It ships with neutral scene/composition labels — setting, shot type, lighting, camera, people count — because that's what I needed sorted first. Edit it freely:

```json
{
  "setting": [
    {"label": "indoor", "prompt": "an indoor scene inside a room"},
    "outdoor"
  ]
}
```

- Labels are grouped in **categories**; scores only compete inside a category, so keep mutually exclusive things together.
- A bare string works as both label and prompt. The `{"label", "prompt"}` form lets you phrase the prompt like a caption — CLIP scores noticeably better with a natural sentence than with a lone keyword.
- Add your own categories for whatever your library actually contains. The shipped vocabulary is a starting point, not a taxonomy of anything.

## Where the tags go

The sidecar JSON is deliberately boring: filename, duration, resolution, tags with scores. I use it as a reference sheet when importing into Stash and similar library tools — check the suggested tags, keep the good ones, delete the nonsense, done in seconds per file instead of minutes.

## Honest limitations

- Zero-shot classification is a heuristic. It is good at "indoor, dark, close-up" and genuinely bad at anything that needs context, story, or taste. Treat output as a draft and eyeball it before it touches your real library.
- Tag quality lives and dies with your vocabulary and threshold. A label that isn't in `tags.json` can never be predicted, and a badly phrased prompt scores badly.
- CLIP ViT-B/32 is a small model from 2021. It runs anywhere, but don't expect miracles on fine-grained distinctions.
- CPU speed is fine for this job — a few seconds per short video once the model is loaded — but a library of thousands of long files will take a while. Sample more frames (`--frames`) for long videos whose content changes a lot.

## License

MIT. See [LICENSE](LICENSE).
