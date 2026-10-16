"""번호별 다음 회차 출현 점수 추정 + 가중 비복원 추출 추천 + 백그라운드 재학습."""

import base64
import json
import os
import pickle
import threading
import time

import numpy as np

# =============================================================================
# [한 줄 스위치] 모델 백엔드 선택
#   "xgboost" : XGBClassifier(n_estimators=40, max_depth=3, tree_method='hist')
#   "sklearn" : sklearn.ensemble.HistGradientBoostingClassifier  ← xgboost NDK 빌드 실패 시
#   "numpy"   : 순수 numpy 로지스틱 회귀 (추가 의존성 0, 어떤 APK에서도 동작)
# 선택한 라이브러리를 import할 수 없으면 xgboost → sklearn → numpy 순서로 자동 폴백한다.
# =============================================================================
MODEL_BACKEND = "xgboost"
# MODEL_BACKEND = "sklearn"
# MODEL_BACKEND = "numpy"

NUM_COUNT = 45
PICK = 6
FEATURE_NAMES = [
    "recent_freq_5",
    "recent_freq_10",
    "recent_freq_20",
    "cycles_since_last",
    "total_freq_ratio",
]
MIN_HISTORY = 10          # 최소 이만큼의 과거 회차가 쌓인 시점부터 학습 샘플로 사용
SOFTMAX_TEMPERATURE = 1.5  # 클수록 균등(다양성↑), 작을수록 고득점 번호 집중
NORMALIZATION = "softmax"  # "softmax" | "minmax"
MODEL_FILENAME = "lotto_model.json"
META_FILENAME = "lotto_model.meta.json"


# ----------------------------------------------------------------- features
def presence_matrix(draws):
    """draws: [[n1..n6], ...] (회차 오름차순) → (T, 45) 0/1 행렬."""
    P = np.zeros((len(draws), NUM_COUNT), dtype=np.float32)
    for t, nums in enumerate(draws):
        P[t, np.asarray(nums, dtype=int) - 1] = 1.0
    return P


def build_feature_tensor(P):
    """
    F[t] = 회차 t "직전까지"(0..t-1)의 통계로 만든 45x5 Feature.
    t = 0..T 이므로 F[T]는 다음(미래) 회차 예측용 Feature.
    """
    T = P.shape[0]
    cum = np.vstack([np.zeros((1, NUM_COUNT), dtype=np.float32), np.cumsum(P, axis=0)])
    F = np.zeros((T + 1, NUM_COUNT, len(FEATURE_NAMES)), dtype=np.float32)
    last_seen = np.full(NUM_COUNT, -1, dtype=np.int64)

    for t in range(T + 1):
        for j, w in enumerate((5, 10, 20)):
            F[t, :, j] = cum[t] - cum[max(0, t - w)]
        # 한 번도 안 나온 번호는 전체 경과 회차 수(t)를 미출현 기간으로 사용
        F[t, :, 3] = np.where(last_seen >= 0, t - 1 - last_seen, t)
        F[t, :, 4] = cum[t] / t if t > 0 else 0.0
        if t < T:
            last_seen[P[t] > 0] = t
    return F


def build_training_set(draws):
    P = presence_matrix(draws)
    F = build_feature_tensor(P)
    T = P.shape[0]
    start = min(MIN_HISTORY, max(1, T - 1))
    X = F[start:T].reshape(-1, len(FEATURE_NAMES))
    y = P[start:T].reshape(-1).astype(np.int32)
    return X, y, F[T]


# ----------------------------------------------------------------- backends
class XGBBackend:
    """XGBClassifier 와 동일 설정을 네이티브 API로 사용(XGBClassifier 는 scikit-learn 설치를 요구함)."""
    name = "xgboost"
    PARAMS = {
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "max_depth": 3,
        "eta": 0.1,
        "tree_method": "hist",
        "nthread": 2,
    }
    N_ESTIMATORS = 40

    def __init__(self):
        import xgboost
        self._xgb = xgboost
        self.model = None

    def fit(self, X, y):
        dtrain = self._xgb.DMatrix(X, label=y)
        self.model = self._xgb.train(self.PARAMS, dtrain, num_boost_round=self.N_ESTIMATORS)

    def predict(self, X):
        return self.model.predict(self._xgb.DMatrix(X))

    def save(self, path):
        self.model.save_model(path)  # 확장자 .json → XGBoost 네이티브 JSON 포맷

    def load(self, path):
        self.model = self._xgb.Booster(model_file=path)


class SklearnBackend:
    name = "sklearn"

    def __init__(self):
        from sklearn.ensemble import HistGradientBoostingClassifier
        self._cls = HistGradientBoostingClassifier
        self.model = None

    def fit(self, X, y):
        self.model = self._cls(max_iter=40, max_depth=3, learning_rate=0.1)
        self.model.fit(X, y)

    def predict(self, X):
        return self.model.predict_proba(X)[:, 1]

    def save(self, path):
        payload = base64.b64encode(pickle.dumps(self.model)).decode("ascii")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"backend": self.name, "pickle_b64": payload}, f)

    def load(self, path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.model = pickle.loads(base64.b64decode(data["pickle_b64"]))


class NumpyLogisticBackend:
    """의존성 없는 L2 로지스틱 회귀(배치 경사하강). 최후의 폴백."""
    name = "numpy"

    def __init__(self, epochs=400, lr=0.1, l2=1e-3):
        self.epochs, self.lr, self.l2 = epochs, lr, l2
        self.mean = self.std = self.w = None
        self.b = 0.0

    def fit(self, X, y):
        X = X.astype(np.float64)
        y = y.astype(np.float64)
        self.mean = X.mean(axis=0)
        self.std = X.std(axis=0) + 1e-8
        Z = (X - self.mean) / self.std
        n, d = Z.shape
        self.w = np.zeros(d)
        p0 = np.clip(y.mean(), 1e-4, 1 - 1e-4)
        self.b = float(np.log(p0 / (1 - p0)))
        for _ in range(self.epochs):
            p = 1.0 / (1.0 + np.exp(-(Z @ self.w + self.b)))
            g = p - y
            self.w -= self.lr * (Z.T @ g / n + self.l2 * self.w)
            self.b -= self.lr * float(g.mean())

    def predict(self, X):
        Z = (X.astype(np.float64) - self.mean) / self.std
        return 1.0 / (1.0 + np.exp(-(Z @ self.w + self.b)))

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "backend": self.name,
                    "mean": self.mean.tolist(),
                    "std": self.std.tolist(),
                    "w": self.w.tolist(),
                    "b": self.b,
                },
                f,
            )

    def load(self, path):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        self.mean = np.array(d["mean"])
        self.std = np.array(d["std"])
        self.w = np.array(d["w"])
        self.b = float(d["b"])


_BACKENDS = {"xgboost": XGBBackend, "sklearn": SklearnBackend, "numpy": NumpyLogisticBackend}
_FALLBACK_ORDER = ["xgboost", "sklearn", "numpy"]


def iter_backends(preferred=MODEL_BACKEND):
    """선호 백엔드부터 import 가능한 백엔드 인스턴스를 차례로 생성."""
    order = [preferred] + [b for b in _FALLBACK_ORDER if b != preferred]
    for name in order:
        try:
            yield _BACKENDS[name]()
        except Exception:  # ImportError, 네이티브 라이브러리 로드 실패(OSError) 등
            continue


def create_backend(preferred=MODEL_BACKEND):
    for backend in iter_backends(preferred):
        return backend
    raise RuntimeError("사용 가능한 모델 백엔드가 없습니다.")


# --------------------------------------------------------------- sampling
def normalize_scores(scores, method=NORMALIZATION, temperature=SOFTMAX_TEMPERATURE):
    s = np.asarray(scores, dtype=np.float64)
    if method == "minmax":
        span = s.max() - s.min()
        w = (s - s.min()) / span if span > 1e-12 else np.ones_like(s)
        w = w + 0.05  # 최저점 번호도 0이 아닌 확률 유지
    else:
        z = (s - s.mean()) / (s.std() + 1e-12)
        z = z / temperature
        w = np.exp(z - z.max())
    return w / w.sum()


def weighted_games(weights, n_games=5, rng=None, max_attempts=200):
    """가중치 기반 비복원 추출로 서로 다른 6개 번호 조합 n_games개 생성(각 게임 오름차순)."""
    rng = rng or np.random.default_rng()
    games, seen = [], set()
    attempts = 0
    while len(games) < n_games:
        picks = rng.choice(NUM_COUNT, size=PICK, replace=False, p=weights)
        game = tuple(sorted(int(i) + 1 for i in picks))
        attempts += 1
        if game in seen and attempts < max_attempts:
            continue
        seen.add(game)
        games.append(list(game))
    return games


# ----------------------------------------------------------------- engine
class LottoEngine:
    def __init__(self, storage, model_dir, backend=MODEL_BACKEND):
        self.storage = storage
        self.model_dir = model_dir
        self.model_path = os.path.join(model_dir, MODEL_FILENAME)
        self.meta_path = os.path.join(model_dir, META_FILENAME)
        self.preferred_backend = backend
        os.makedirs(model_dir, exist_ok=True)

        self._model = None
        self._meta = {}
        self._model_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._training = False
        self._pending_retrain = False

    # ------------------------------------------------------------- status
    @property
    def is_training(self):
        return self._training

    @property
    def backend_name(self):
        return self._model.name if self._model else "-"

    @property
    def meta(self):
        return dict(self._meta)

    # -------------------------------------------------------- persistence
    def load_model(self):
        """저장된 모델이 있고 백엔드가 호환되면 로드. 성공 여부 반환."""
        if not (os.path.exists(self.model_path) and os.path.exists(self.meta_path)):
            return False
        try:
            with open(self.meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            backend = _BACKENDS[meta["backend"]]()  # import 불가 시 예외 → 재학습
            backend.load(self.model_path)
        except Exception:
            return False
        with self._model_lock:
            self._model, self._meta = backend, meta
        return True

    def _save_model(self, backend, meta):
        # 임시 파일에 먼저 쓰고 os.replace로 교체 → 저장 도중 앱 종료돼도 기존 모델 보존
        tmp_model = self.model_path[:-5] + ".tmp.json"
        tmp_meta = self.meta_path + ".tmp"
        backend.save(tmp_model)
        with open(tmp_meta, "w", encoding="utf-8") as f:
            json.dump(meta, f)
        os.replace(tmp_model, self.model_path)
        os.replace(tmp_meta, self.meta_path)

    def needs_retrain(self):
        return self._model is None or self._meta.get("trained_draws") != self.storage.count_draws()

    # ---------------------------------------------------------- training
    def retrain(self):
        """동기 학습. 학습 결과 메타 dict 반환."""
        draws = self.storage.get_number_matrix()
        if len(draws) < 2:
            raise RuntimeError("학습에 필요한 회차 데이터가 부족합니다.")
        X, y, _ = build_training_set(draws)
        t0 = time.time()
        backend, last_error = None, None
        for candidate in iter_backends(self.preferred_backend):
            try:
                candidate.fit(X, y)
                backend = candidate
                break
            except Exception as exc:  # 학습 단계에서만 드러나는 의존성 문제 → 다음 백엔드
                last_error = exc
        if backend is None:
            raise RuntimeError(f"모든 모델 백엔드 학습 실패: {last_error}")
        meta = {
            "backend": backend.name,
            "trained_draws": len(draws),
            "latest_draw_no": self.storage.latest_draw_no(),
            "samples": int(X.shape[0]),
            "train_seconds": round(time.time() - t0, 3),
            "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._save_model(backend, meta)
        with self._model_lock:
            self._model, self._meta = backend, meta
        return meta

    def retrain_async(self, on_done=None, on_error=None):
        """
        백그라운드 스레드에서 재학습. 학습 중 재요청이 오면 끝난 직후 한 번 더 학습한다.
        콜백은 백그라운드 스레드에서 호출되므로 UI 측에서 메인 스레드로 넘겨야 한다.
        """
        with self._state_lock:
            if self._training:
                self._pending_retrain = True
                return False
            self._training = True

        def worker():
            while True:
                meta, error = None, None
                try:
                    meta = self.retrain()
                except Exception as exc:
                    error = exc
                with self._state_lock:
                    again = self._pending_retrain
                    self._pending_retrain = False
                    if not again:
                        self._training = False
                if error is None:
                    if on_done:
                        on_done(meta)
                elif on_error:
                    on_error(error)
                if not again:
                    return

        threading.Thread(target=worker, name="lotto-retrain", daemon=True).start()
        return True

    # -------------------------------------------------------- prediction
    def predict_scores(self):
        """1~45번 각각의 다음 회차 출현 점수(길이 45 배열, index 0 = 1번)."""
        draws = self.storage.get_number_matrix()
        P = presence_matrix(draws)
        next_features = build_feature_tensor(P)[-1]
        with self._model_lock:
            model = self._model
        if model is not None:
            try:
                return np.asarray(model.predict(next_features), dtype=np.float64)
            except Exception:
                pass
        # 모델 준비 전(최초 학습 중) 휴리스틱 점수
        f = next_features
        return 0.4 * f[:, 4] + 0.3 * f[:, 2] / 20 + 0.2 * f[:, 1] / 10 + 0.1 * f[:, 0] / 5

    def generate_recommendations(self, n_games=5, save=True, rng=None):
        """(target_draw_no, games, scores) 반환. games: [[6개 오름차순], ...]."""
        scores = self.predict_scores()
        weights = normalize_scores(scores)
        games = weighted_games(weights, n_games=n_games, rng=rng)
        target = self.storage.latest_draw_no() + 1
        if save:
            self.storage.save_recommendation(target, games)
        return target, games, scores
