[app]
title = Lotto Offline
package.name = lottooffline
package.domain = org.yongseok
source.dir = .
source.include_exts = py,png,jpg,kv,json,csv,ttf,ttc,otf,txt
source.exclude_dirs = bin,.buildozer,__pycache__,venv,.venv,tools
source.exclude_patterns = requirements.txt,README.md
version = 1.0.0

icon.filename = %(source.dir)s/assets/icon.png
presplash.filename = %(source.dir)s/assets/presplash.png
android.presplash_color = #F2F4F6

# ---------------------------------------------------------------------------
# requirements (ml_engine.MODEL_BACKEND 와 짝을 맞춘다)
#
# [기본 / 권장] 순수 numpy 백엔드 — python-for-android 공식 레시피만 사용, 빌드 안정적.
#   MODEL_BACKEND 가 "xgboost" 여도 APK 안에 xgboost 가 없으면 자동으로 numpy 로 폴백한다.
#   sqlite3 는 p4a 에서 별도 레시피라 빠지면 기기에서 storage.py import 시 앱이 종료된다.
requirements = python3,kivy==2.3.0,numpy,sqlite3
#
# [xgboost] p4a 에 xgboost 레시피가 없어 C++/OpenMP NDK 크로스컴파일이 필요(대부분 실패).
#   직접 레시피를 작성할 경우에만 사용:
# requirements = python3,kivy==2.3.0,numpy,sqlite3,xgboost
#
# [sklearn] HistGradientBoostingClassifier 사용 시 (ml_engine.py: MODEL_BACKEND = "sklearn")
#   scipy 가 Fortran 툴체인을 요구하므로 최신 p4a(develop) + 충분한 빌드 시간 필요:
# requirements = python3,kivy==2.3.0,numpy,sqlite3,scipy,scikit-learn,joblib,threadpoolctl
# ---------------------------------------------------------------------------

orientation = portrait
fullscreen = 0

# 완전 오프라인 앱: INTERNET 등 어떤 권한도 요청하지 않는다(DB/모델은 앱 전용 저장소 사용).
# android.permissions =

android.api = 34
android.minapi = 24
android.ndk = 25b
android.accept_sdk_license = True
# Galaxy S24 / Fold 등 최근 기기는 64비트 전용. 구형 32비트 기기까지 지원하려면 armeabi-v7a 추가
android.archs = arm64-v8a
android.allow_backup = True
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
