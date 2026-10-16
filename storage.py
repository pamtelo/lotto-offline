"""로컬 SQLite 저장소: 당첨 이력(draw_history)과 추천 이력(recommendations)."""

import json
import os
import random
import re
import sqlite3
import threading
from contextlib import contextmanager

NUM_MIN, NUM_MAX, PICK = 1, 45, 6
SEED_DRAW_COUNT = 50
SEED_CSV_NAME = "seed_history.csv"
REC_EXTRA_COLUMNS = [
    ("scores_json", "TEXT"),
    ("model_backend", "TEXT"),
    ("trained_draws", "INTEGER"),
    ("is_confirmed", "INTEGER NOT NULL DEFAULT 0"),
]


class ValidationError(ValueError):
    pass


def validate_draw(draw_no, numbers, bonus=None):
    """입력값 검증 후 (draw_no, sorted_numbers, bonus) 반환."""
    try:
        draw_no = int(draw_no)
    except (TypeError, ValueError):
        raise ValidationError("회차는 숫자여야 합니다.")
    if draw_no <= 0:
        raise ValidationError("회차는 1 이상이어야 합니다.")

    try:
        nums = [int(n) for n in numbers]
    except (TypeError, ValueError):
        raise ValidationError("당첨 번호 6개를 모두 숫자로 입력하세요.")
    if len(nums) != PICK:
        raise ValidationError("당첨 번호는 정확히 6개여야 합니다.")
    if any(n < NUM_MIN or n > NUM_MAX for n in nums):
        raise ValidationError("번호는 1~45 범위여야 합니다.")
    if len(set(nums)) != PICK:
        raise ValidationError("당첨 번호에 중복이 있습니다.")

    if bonus in (None, ""):
        bonus = None
    else:
        try:
            bonus = int(bonus)
        except (TypeError, ValueError):
            raise ValidationError("보너스 번호는 숫자여야 합니다.")
        if bonus < NUM_MIN or bonus > NUM_MAX:
            raise ValidationError("보너스 번호는 1~45 범위여야 합니다.")
        if bonus in nums:
            raise ValidationError("보너스 번호가 당첨 번호와 중복됩니다.")

    return draw_no, sorted(nums), bonus


_FIELD_SEP = re.compile(r"[,\t;\s]+")


def parse_history_file(path):
    """
    회차,n1..n6[,bonus] 형식 파일을 [(draw_no, n1..n6, bonus), ...]로 변환.
    구분자는 쉼표/탭(Excel 붙여넣기)/세미콜론/공백 모두 허용하고,
    첫 칸이 숫자가 아닌 줄(헤더, # 주석, 빈 줄)은 건너뛴다.
    잘못된 행이 있으면 줄 번호를 담은 ValidationError, 회차 중복도 오류로 처리한다.
    """
    rows, seen = [], set()
    with open(path, encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, 1):
            rec = [x for x in _FIELD_SEP.split(line.strip()) if x]
            if not rec or not rec[0].isdigit():
                continue
            if len(rec) < 7:
                raise ValidationError(f"{line_no}번째 줄: 칸이 부족합니다 ({len(rec)}칸).")
            try:
                draw_no, nums, bonus = validate_draw(
                    rec[0], rec[1:7], rec[7] if len(rec) > 7 else None
                )
            except ValidationError as exc:
                raise ValidationError(f"{line_no}번째 줄({rec[0]}회): {exc}")
            if draw_no in seen:
                raise ValidationError(f"{line_no}번째 줄: {draw_no}회차가 중복됩니다.")
            seen.add(draw_no)
            rows.append((draw_no, *nums, bonus))
    return rows


class LottoStorage:
    def __init__(self, db_path, seed_dir=None):
        self.db_path = db_path
        self.seed_dir = seed_dir or os.path.dirname(os.path.abspath(__file__))
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_schema()
        self._seed_if_empty()

    # SQLite 연결은 스레드 간 공유하지 않고 작업마다 새로 연다(백그라운드 학습 스레드 안전).
    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self):
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS draw_history (
                    draw_no    INTEGER PRIMARY KEY,
                    n1 INTEGER NOT NULL, n2 INTEGER NOT NULL, n3 INTEGER NOT NULL,
                    n4 INTEGER NOT NULL, n5 INTEGER NOT NULL, n6 INTEGER NOT NULL,
                    bonus      INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS recommendations (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_draw_no INTEGER NOT NULL,
                    games_json     TEXT NOT NULL,
                    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_rec_target
                    ON recommendations(target_draw_no);
                CREATE TABLE IF NOT EXISTS evaluations (
                    draw_no               INTEGER PRIMARY KEY,
                    recommendation_id     INTEGER,
                    confirmed             INTEGER NOT NULL DEFAULT 0,
                    numbers_json          TEXT NOT NULL,
                    bonus                 INTEGER,
                    games_json            TEXT NOT NULL,
                    hits_json             TEXT NOT NULL,
                    ranks_json            TEXT NOT NULL,
                    winner_positions_json TEXT,
                    auc                   REAL,
                    model_backend         TEXT,
                    trained_draws         INTEGER,
                    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            # 이전 버전 DB 에는 없는 컬럼을 추가 (추천 시점의 45개 점수·모델 정보·확정 여부)
            existing = {r["name"] for r in conn.execute("PRAGMA table_info(recommendations)")}
            for name, decl in REC_EXTRA_COLUMNS:
                if name not in existing:
                    conn.execute(f"ALTER TABLE recommendations ADD COLUMN {name} {decl}")
            conn.commit()

    # ---------------------------------------------------------------- seed
    def _seed_if_empty(self):
        if self.count_draws() > 0:
            return
        rows = self._load_seed_csv() or self._generate_dummy_seed()
        with self._lock, self._connect() as conn:
            with conn:
                conn.executemany(
                    "INSERT OR IGNORE INTO draw_history "
                    "(draw_no, n1, n2, n3, n4, n5, n6, bonus) VALUES (?,?,?,?,?,?,?,?)",
                    rows,
                )

    def _load_seed_csv(self):
        """앱 폴더에 seed_history.csv(draw_no,n1..n6,bonus)가 있으면 실제 데이터로 시드."""
        path = os.path.join(self.seed_dir, SEED_CSV_NAME)
        if not os.path.exists(path):
            return None
        try:
            rows = parse_history_file(path)
        except (OSError, ValidationError):
            return None
        return rows or None

    @staticmethod
    def _generate_dummy_seed():
        """콜드 스타트용 결정적(재현 가능) 더미 데이터 50회차."""
        rng = random.Random(645)
        rows = []
        for draw_no in range(1, SEED_DRAW_COUNT + 1):
            picked = rng.sample(range(NUM_MIN, NUM_MAX + 1), PICK + 1)
            nums, bonus = sorted(picked[:PICK]), picked[PICK]
            rows.append((draw_no, *nums, bonus))
        return rows

    # ---------------------------------------------------------------- draws
    def add_draw(self, draw_no, numbers, bonus=None):
        """검증 + 중복 회차 확인 + 트랜잭션 저장. 실패 시 ValidationError."""
        draw_no, nums, bonus = validate_draw(draw_no, numbers, bonus)
        with self._lock, self._connect() as conn:
            try:
                with conn:  # 트랜잭션: 성공 시 commit, 예외 시 rollback
                    exists = conn.execute(
                        "SELECT 1 FROM draw_history WHERE draw_no = ?", (draw_no,)
                    ).fetchone()
                    if exists:
                        raise ValidationError(f"{draw_no}회차는 이미 등록되어 있습니다.")
                    conn.execute(
                        "INSERT INTO draw_history "
                        "(draw_no, n1, n2, n3, n4, n5, n6, bonus) VALUES (?,?,?,?,?,?,?,?)",
                        (draw_no, *nums, bonus),
                    )
            except sqlite3.IntegrityError:
                raise ValidationError(f"{draw_no}회차는 이미 등록되어 있습니다.")
        return draw_no, nums, bonus

    def count_draws(self):
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM draw_history").fetchone()[0]

    def latest_draw_no(self):
        with self._connect() as conn:
            row = conn.execute("SELECT MAX(draw_no) FROM draw_history").fetchone()
            return row[0] or 0

    @staticmethod
    def _row_to_dict(row):
        return {
            "draw_no": row["draw_no"],
            "numbers": [row["n1"], row["n2"], row["n3"], row["n4"], row["n5"], row["n6"]],
            "bonus": row["bonus"],
            "created_at": row["created_at"],
        }

    def get_draw(self, draw_no):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM draw_history WHERE draw_no = ?", (int(draw_no),)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_draws(self, limit=None, descending=True):
        order = "DESC" if descending else "ASC"
        sql = f"SELECT * FROM draw_history ORDER BY draw_no {order}"
        params = ()
        if limit:
            sql += " LIMIT ?"
            params = (int(limit),)
        with self._connect() as conn:
            return [self._row_to_dict(r) for r in conn.execute(sql, params)]

    def get_number_matrix(self):
        """ML용: 회차 오름차순 [[n1..n6], ...] (보너스 제외)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT n1, n2, n3, n4, n5, n6 FROM draw_history ORDER BY draw_no ASC"
            ).fetchall()
        return [list(r) for r in rows]

    # ------------------------------------------------------- recommendations
    def save_recommendation(self, target_draw_no, games, scores=None,
                            model_backend=None, trained_draws=None):
        """추천 5게임과 그 시점의 45개 점수·모델 정보를 저장하고 id 반환."""
        with self._lock, self._connect() as conn:
            with conn:
                cur = conn.execute(
                    "INSERT INTO recommendations "
                    "(target_draw_no, games_json, scores_json, model_backend, trained_draws) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        int(target_draw_no),
                        json.dumps(games),
                        json.dumps([round(float(s), 6) for s in scores]) if scores is not None else None,
                        model_backend,
                        trained_draws,
                    ),
                )
                return cur.lastrowid

    @staticmethod
    def _rec_to_dict(row):
        return {
            "id": row["id"],
            "target_draw_no": row["target_draw_no"],
            "games": json.loads(row["games_json"]),
            "scores": json.loads(row["scores_json"]) if row["scores_json"] else None,
            "model_backend": row["model_backend"],
            "trained_draws": row["trained_draws"],
            "is_confirmed": bool(row["is_confirmed"]),
            "created_at": row["created_at"],
        }

    def latest_recommendation(self, target_draw_no=None):
        sql = "SELECT * FROM recommendations"
        params = ()
        if target_draw_no is not None:
            sql += " WHERE target_draw_no = ?"
            params = (int(target_draw_no),)
        sql += " ORDER BY id DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return self._rec_to_dict(row) if row else None

    def confirm_recommendation(self, rec_id):
        """해당 추천을 그 회차의 확정 세트로 지정 (회차당 하나만 확정)."""
        with self._lock, self._connect() as conn:
            with conn:
                row = conn.execute(
                    "SELECT target_draw_no FROM recommendations WHERE id = ?", (int(rec_id),)
                ).fetchone()
                if not row:
                    raise ValidationError("확정할 추천을 찾을 수 없습니다.")
                conn.execute(
                    "UPDATE recommendations SET is_confirmed = (id = ?) WHERE target_draw_no = ?",
                    (int(rec_id), row["target_draw_no"]),
                )

    def official_recommendation(self, target_draw_no):
        """
        채점 기준 추천: 확정한 세트, 없으면 그 회차에 학습된 모델로 만든 첫 추천,
        그것도 없으면 첫 추천. 여러 번 다시 뽑아도 성적이 부풀지 않도록 '마지막'이 아닌 '처음'을 쓴다.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM recommendations WHERE target_draw_no = ? "
                "ORDER BY is_confirmed DESC, (model_backend = 'heuristic') ASC, id ASC LIMIT 1",
                (int(target_draw_no),),
            ).fetchone()
        return self._rec_to_dict(row) if row else None

    # ----------------------------------------------------------- evaluations
    def save_evaluation(self, ev):
        with self._lock, self._connect() as conn:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO evaluations (draw_no, recommendation_id, confirmed, "
                    "numbers_json, bonus, games_json, hits_json, ranks_json, "
                    "winner_positions_json, auc, model_backend, trained_draws) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        ev["draw_no"],
                        ev["recommendation_id"],
                        int(ev["confirmed"]),
                        json.dumps(ev["numbers"]),
                        ev["bonus"],
                        json.dumps(ev["games"]),
                        json.dumps(ev["hits"]),
                        json.dumps(ev["ranks"]),
                        json.dumps(ev["winner_positions"]) if ev["winner_positions"] else None,
                        ev["auc"],
                        ev["model_backend"],
                        ev["trained_draws"],
                    ),
                )

    @staticmethod
    def _eval_to_dict(row):
        return {
            "draw_no": row["draw_no"],
            "recommendation_id": row["recommendation_id"],
            "confirmed": bool(row["confirmed"]),
            "numbers": json.loads(row["numbers_json"]),
            "bonus": row["bonus"],
            "games": json.loads(row["games_json"]),
            "hits": json.loads(row["hits_json"]),
            "ranks": json.loads(row["ranks_json"]),
            "winner_positions": (
                json.loads(row["winner_positions_json"]) if row["winner_positions_json"] else None
            ),
            "auc": row["auc"],
            "model_backend": row["model_backend"],
            "trained_draws": row["trained_draws"],
            "created_at": row["created_at"],
        }

    def list_evaluations(self, limit=None):
        sql = "SELECT * FROM evaluations ORDER BY draw_no DESC"
        params = ()
        if limit:
            sql += " LIMIT ?"
            params = (int(limit),)
        with self._connect() as conn:
            return [self._eval_to_dict(r) for r in conn.execute(sql, params)]
