[English](README.md) | [简体中文](README_zh.md) | [日本語](README_ja.md) | **한국어**

# video-autotag — 전부 열어보지 않고 라이브러리에 태그 초안 달기

로컬 라이브러리는 계속 불어나는데 태그 다는 성실함은 전혀 따라오지 못했다. 수백 개 파일, 대부분 `final_v2.mp4` 같은 이름이고, Stash 같은 라이브러리 도구는 결국 태그를 넣어줘야 쓸 만해지는데 — 그 입력을 나는 늘 미뤘다.

그래서 게으른 버전을 만들었다. 폴더를 던져주면 각 영상을 몇 프레임씩 대신 봐주고, 본 것을 적어준다. 최종 태그가 아니라, 훑어보고 고칠 수 있는 초안. 빈 태그 칸 앞에서 멍때리는 것보다는 낫다.

## 동작 방식

1. **ffmpeg**가 각 영상에서 고르게 N장의 정지 화면을 뽑는다(ffprobe가 길이와 해상도를 먼저 가져온다).
2. **CLIP**(`openai/clip-vit-base-patch32`, transformers로 로컬 실행)이 모든 프레임을 태그 어휘와 대조해 점수를 매긴다 — 학습도, API 키도 없는 제로샷 분류.
3. 같은 카테고리 안의 라벨끼리 경쟁하고(실내 vs 실외, 클로즈업 vs 와이드 샷), 프레임마다 투표해서 라벨별 **전체 프레임 중 최고 점수**를 채택한다. 임계값 이상만 결과에 들어간다.

영상마다 sidecar 파일이 생긴다. `movie.mp4` → `movie.tags.json`:

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

위 예시는 합성 테스트 영상(검은 배경에 흰 글자)에 대한 실제 출력이다. `all_scores`에는 채택된 것뿐 아니라 모든 라벨의 점수가 남아 있어서, 나중에 임계값을 바꾸고 싶어도 모델을 다시 돌릴 필요가 없다.

## 설치

Python 3.10+와 PATH에 잡히는 ffmpeg / ffprobe가 필요하다.

```bash
# CPU 전용 torch 먼저 — 기본 CUDA 빌드보다 훨씬 작다
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

첫 실행 때 HuggingFace에서 CLIP 모델을 내려받는다(약 580 MB, 한 번만). 그 이후로는 완전 오프라인, CPU만으로, 내 컴퓨터 안에서만 돈다. 라이브러리 정보가 밖으로 나갈 일은 없다.

## 사용법

```bash
# 폴더 통째로(재귀), sidecar는 각 영상 옆에
python autotag.py /path/to/library

# 파일 하나만, 임계값 까다롭게, 프레임 더 많이
python autotag.py movie.mp4 --frames 8 --threshold 0.7

# 실행 전체 요약 CSV까지
python autotag.py /path/to/library --out-csv summary.csv
```

| 옵션 | 기본값 | 하는 일 |
|---|---|---|
| `--frames` | 5 | 영상마다 뽑는 프레임 수 |
| `--threshold` | 0.55 | 태그로 채택하는 최소 점수 |
| `--tags` | 스크립트 옆의 `tags.json` | 쓸 어휘 파일 |
| `--out-csv` | 끔 | 요약 CSV(파일명, 길이, 해상도, 태그) 쓰기 |

## 어휘는 내 것으로

`tags.json`이 이 도구의 성격 전부다. 기본 어휘는 장면/구도 계열의 중립적인 라벨 — 장소, 샷 종류, 조명, 카메라, 인원수 — 내가 먼저 정리하고 싶었던 게 이거였기 때문이다. 마음껏 고쳐 쓰길:

```json
{
  "setting": [
    {"label": "indoor", "prompt": "an indoor scene inside a room"},
    "outdoor"
  ]
}
```

- 라벨은 **카테고리**로 묶고, 점수는 카테고리 안에서만 경쟁한다. 서로 배타적인 것들은 같은 그룹에 넣어야 한다.
- 문자열 하나만 써도 된다(라벨이자 프롬프트가 된다). `{"label", "prompt"}` 형식이면 프롬프트를 자연스러운 문장으로 쓸 수 있는데, CLIP은 단어 하나보다 문장에 훨씬 안정적으로 점수를 준다.
- 내 라이브러리에 실제로 있는 것에 맞춰 카테고리를 추가하면 된다. 기본 어휘는 출발점일 뿐, 어떤 분류 체계도 아니다.

## 태그는 어디에 쓰나

sidecar JSON은 일부러 심심하게 만들었다: 파일명, 길이, 해상도, 점수 달린 태그. 나는 Stash 같은 라이브러리 도구로 가져올 때 참고표로 쓴다 — 후보를 보고, 맞는 건 남기고, 엉뚱한 건 지운다. 파일당 몇 분이 몇 초가 된다.

## 솔직한 한계

- 제로샷 분류는 휴리스틱이다. "실내, 어두움, 클로즈업" 같은 화면 사실은 잘하지만, 맥락이나 이야기나 취향이 필요한 건 정말 못한다. 출력은 초안으로 취급하고, 진짜 라이브러리에 넣기 전에 눈으로 확인할 것.
- 태그 품질은 어휘와 임계값에서 결정된다. `tags.json`에 없는 라벨은 영원히 예측되지 않고, 프롬프트를 못 쓰면 점수도 못 쓴다.
- CLIP ViT-B/32는 2021년산 작은 모델이다. 어디서든 도는 대신, 세밀한 구분에서 기적은 기대하지 말 것.
- CPU 속도는 이 일에는 충분하다(모델 로드 후 짧은 영상은 개당 몇 초). 다만 수천 개의 긴 파일로 된 라이브러리는 꽤 걸린다. 내용 변화가 큰 긴 영상은 `--frames`를 늘리는 게 좋다.

## 라이선스

MIT. [LICENSE](LICENSE) 참조.
