"""올팍주차:88 parking - 공연장 수용 규모·시간 기반 가상 모델.

실제 주차 기록이 아니라 인위적 규칙으로 생성한 자료를 학습합니다.
"""
from datetime import datetime, timedelta
from pathlib import Path
import random

import joblib
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split

BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "models"
MODEL_DIR.mkdir(exist_ok=True)
MODEL_PATH = MODEL_DIR / "parking_model.pkl"
random.seed(42)
features, targets = [], []
base_date = datetime(2025, 1, 1)

for _ in range(14000):
    date = base_date + timedelta(days=random.randint(0, 364))
    hour = random.randint(6, 23)
    weekday = date.weekday()
    temperature = round(random.uniform(-10, 35), 1)
    rain_probability = random.randint(0, 100)
    event_count = random.choices([0, 1, 2, 3, 4, 5], weights=[35, 25, 18, 12, 7, 3])[0]
    event_pressure = 0.0
    for _event in range(event_count):
        # 공식 공연장 수용 규모 표본. 70% 객석 점유를 가정하며 실제 관객수가 아님.
        capacity = random.choice([15000, 5003, 3000, 1184, 237])
        size = capacity * 0.70 / 10000
        start_hour = random.choice([11, 14, 16, 17, 18, 19, 20])
        distance = hour - start_hour
        if -2 <= distance <= 0:
            proximity = 1.0 if distance >= -1 else 0.65
        elif 0 < distance <= 2:
            proximity = 0.55
        elif 2 < distance <= 4:
            proximity = 0.2
        else:
            proximity = 0.0
        event_pressure += size * proximity
    event_pressure = round(min(5.0, event_pressure), 2)

    # 이 점수식은 주차장 관측 데이터에 근거한 식이 아닌 시연용 가정입니다.
    score = 20.0
    if 9 <= hour <= 11:
        score += 16
    if 17 <= hour <= 20:
        score += 26
    if weekday >= 5:
        score += 14
    score += min(event_count, 5) * 1.5 + event_pressure * 22
    if rain_probability >= 70:
        score -= 7
    if temperature < -5 or temperature > 32:
        score -= 4
    score += random.uniform(-3.5, 3.5)
    features.append([hour, weekday, temperature, rain_probability, event_count, event_pressure])
    targets.append(float(np.clip(score, 0, 99.9)))

X = np.asarray(features, dtype=float)
y = np.asarray(targets, dtype=float)
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
# 무료 배포 서버의 제한된 빌드 메모리에서도 학습 가능하도록 축소한 시연 모델.
model = RandomForestRegressor(n_estimators=64, max_depth=12, min_samples_leaf=3, random_state=42, n_jobs=1)
model.fit(X_train, y_train)
mae = mean_absolute_error(y_test, model.predict(X_test))
joblib.dump({"version": 4, "model": model, "feature_names": [
    "hour", "weekday", "temperature", "rain_probability", "event_count", "event_pressure"
]}, MODEL_PATH)
print("공식 공연장 수용 규모·공연 건수·시작 시간 기반 시뮬레이션 모델 학습 완료")
print(f"가상 테스트 MAE: {mae:.2f}%p (실제 주차 예측 성능이 아닙니다)")
print(f"저장 위치: {MODEL_PATH}")
