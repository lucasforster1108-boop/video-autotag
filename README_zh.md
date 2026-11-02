[English](README.md) | **简体中文** | [日本語](README_ja.md) | [한국어](README_ko.md)

# video-autotag —— 不用挨个点开，先给视频库打一轮草稿标签

我的本地片库一直在涨，我的打标签自觉性一直没跟上。几百个文件，一大半叫 `final_v2.mp4` 这种名字，而 Stash 这类片库工具好不好用全看标签喂得勤不勤——我反正是没勤过。

所以我写了个偷懒版：把文件夹丢给它，它替你每个视频看几帧，把看到的东西记下来。不是最终标签，是草稿——你扫一眼改一改就行，总比对着空白标签栏发呆强。

## 怎么干活的

1. **ffmpeg** 在每个视频里均匀抽 N 帧（ffprobe 先拿时长和分辨率）。
2. **CLIP**（`openai/clip-vit-base-patch32`，用 transformers 在本地跑）拿每一帧去和一份标签词表逐项打分——纯零样本分类，不训练，不要 API key。
3. 同一类别里的标签互相竞争（室内 vs 室外、特写 vs 远景这样），每帧都投票，我取**每个标签在所有帧里的最高分**。达到阈值的才进结果。

每个视频生成一个 sidecar 文件，`movie.mp4` → `movie.tags.json`：

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

这段是真实输出，测的是一段合成测试视频（黑底白字）。`all_scores` 里保留了所有标签的分数，不只是入选的——之后想换个阈值，不用重跑模型。

## 安装

需要 Python 3.10+，以及 PATH 里能找到 ffmpeg / ffprobe。

```bash
# 先装 CPU 版 torch，比默认的 CUDA 版小得多
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

第一次运行会从 HuggingFace 下载 CLIP 模型（约 580 MB，只下一次）。之后全程离线、CPU 运行、就在你自己机器上，你的片库信息不会出这台机器。

## 用法

```bash
# 整个文件夹（递归），sidecar 写在每个视频旁边
python autotag.py /path/to/library

# 单个文件，阈值挑剔一点，帧多抽几张
python autotag.py movie.mp4 --frames 8 --threshold 0.7

# 再加一份全程汇总 CSV
python autotag.py /path/to/library --out-csv summary.csv
```

| 参数 | 默认 | 作用 |
|---|---|---|
| `--frames` | 5 | 每个视频抽几帧 |
| `--threshold` | 0.55 | 标签入选的最低分 |
| `--tags` | 脚本旁边的 `tags.json` | 用哪份词表 |
| `--out-csv` | 关 | 输出汇总 CSV（文件名、时长、分辨率、标签） |

## 词表要改成你自己的

`tags.json` 决定了这个工具的全部性格。默认词表是中性的场景/构成类标签——场景、景别、光线、机位、人数——因为我最先要理顺的就是这些。随便改：

```json
{
  "setting": [
    {"label": "indoor", "prompt": "an indoor scene inside a room"},
    "outdoor"
  ]
}
```

- 标签按**类别**分组，分数只在类别内部竞争，所以互斥的东西要放在同一组。
- 只写一个字符串也行，它同时当标签名和提示词。用 `{"label", "prompt"}` 这种写法可以把 prompt 写成一句自然的话——CLIP 对完整句子的打分明显比对单个关键词准。
- 按你片库里真正有的东西加类别。默认词表只是个起点，不是什么分类学标准。

## 标签拿去干嘛

sidecar JSON 故意做得很朴素：文件名、时长、分辨率、带分数的标签。我是把它当参考表用的——导入 Stash 之类的片库工具时照着看，对的留下，离谱的删掉，每个文件几秒钟搞定，不用再花几分钟。

## 说实话的部分（局限性）

- 零样本分类是启发式的。它擅长「室内、暗光、特写」这类画面事实，对任何需要上下文、剧情、审美的东西是真的不行。输出当草稿，进你正经片库之前先过一眼。
- 标签质量完全取决于你的词表和阈值。`tags.json` 里没有的标签永远预测不出来，prompt 写得烂分数就烂。
- CLIP ViT-B/32 是 2021 年的小模型，哪儿都能跑，但细粒度区分别指望有奇迹。
- CPU 速度对这个活儿够用——模型加载完后，短视频每个几秒钟——但几千个长文件的大片库会跑挺久。内容变化大的长视频可以多抽几帧（`--frames`）。

## License

MIT，见 [LICENSE](LICENSE)。
