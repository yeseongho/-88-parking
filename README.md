# 올팍주차:88 parking

올림픽공원 공개 주차대수와 공연 정보, 기상 예보, AI 기반 혼잡도 추정 기능을 연결한 개인 포트폴리오 프로젝트입니다. 올림픽공원 공식 홈페이지가 아닙니다. 주차대수 API의 원본 센서 갱신 시각과 실제 주차 가능 대수는 확인할 수 없습니다.

## 배포 구성

- 프론트엔드: GitHub Pages (`index.html`, `config.js`)
- 백엔드: Render Web Service (`backend/main.py`)
- AI 시뮬레이션 모델: Render 빌드 시 `backend/train_model.py` 실행
- 데이터베이스: `backend/data/parking_observations.sqlite3` (Render 무료 서버에서는 영구 보존되지 않음)

## 배포 순서

1. 이 폴더의 **내용물**을 GitHub 저장소 `yeseongho/-88-parking` 최상위에 업로드합니다. `.env`, 기존 `*.sqlite3`, 모델 `*.pkl` 파일은 업로드하지 않습니다.
2. GitHub 저장소 **Settings > Pages > Build and deployment**에서 **Deploy from a branch**, **main**, **/(root)** 를 선택합니다.
3. [Render](https://dashboard.render.com/)에서 저장소 연결 후 **Blueprint**를 선택하거나 `render.yaml`의 설정대로 새 Web Service를 만듭니다. Render가 자동으로 model을 빌드합니다.
4. Render에 환경변수 `OLPARK_PERFORMANCE_API_KEY`, `KMA_API_KEY`가 필요한 경우 **Environment** 탭에서 기존 인증키를 추가합니다. 키를 GitHub 코드에 붙여넣지 마세요.
5. 생성된 Render API의 `https://...onrender.com` 주소를 루트 `config.js`의 `window.OLPARK_API_BASE`에 입력해 GitHub에 다시 커밋합니다.
6. 사이트를 열어 주차현황, 공연, 날씨, AI 예측이 정상 연결되는지 확인합니다.

## 로컬 실행

백엔드 폴더에서:

```powershell
pip install -r requirements.txt
python train_model.py
python -m uvicorn main:app --reload --port 8000
```

별도 터미널에서 프로젝트 최상위 폴더에서:

```powershell
python -m http.server 8765
```

`http://127.0.0.1:8765`에 접속합니다.

## 무료 배포의 데이터 보존 한계

**중요:** Render 무료 웹서버는 접속이 없을 때 중지되며 내부 저장소가 영구적이지 않습니다. 따라서 SQLite로 수집한 기록은 재시작·재배포 시 유실될 수 있고, 1년 자동 학습을 무료 Render만으로 보장할 수 없습니다. 장기 누적 학습을 하려면 별도의 영구 저장소와 백업 체계를 구축해야 합니다.

예측 결과는 공식 API의 실측 구역별 주차 가능 공간이 아닙니다. 학습 데이터가 쌓여도 별도 오차 검증 없이는 정확도를 보장하지 않습니다.
