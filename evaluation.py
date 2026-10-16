"""추천 성적 채점: 추천 시점에 저장한 5게임·45개 점수를 실제 당첨 번호와 비교하고 무작위 기준선과 대조."""

from math import comb

import numpy as np

NUM_COUNT, PICK = 45, 6
TOP_K = 15
MIN_RELIABLE_DRAWS = 30  # 이보다 적게 쌓이면 '아직 판단하기 이르다'고 안내

_TOTAL = comb(NUM_COUNT, PICK)
# 무작위 1게임에서 k개 적중할 확률 (초기하분포)
P_HITS = [comb(PICK, k) * comb(NUM_COUNT - PICK, PICK - k) / _TOTAL for k in range(PICK + 1)]
RANDOM_HITS_PER_GAME = PICK * PICK / NUM_COUNT       # 0.8
RANDOM_PRIZE_RATE = sum(P_HITS[3:])                   # 3개 이상(5등 이상) ≈ 2.38%
RANDOM_AUC = 0.5
RANDOM_TOP_K = PICK * TOP_K / NUM_COUNT               # 상위 15개 안의 당첨 번호 2.0개
RANDOM_MEAN_POSITION = (NUM_COUNT + 1) / 2            # 당첨 번호의 평균 점수 순위 23위
# 무작위 1게임 적중 개수의 분산 (초기하분포)
RANDOM_HITS_VAR = (PICK * (PICK / NUM_COUNT) * ((NUM_COUNT - PICK) / NUM_COUNT)
                   * ((NUM_COUNT - PICK) / (NUM_COUNT - 1)))

PRIZE_NAMES = {1: "1등", 2: "2등", 3: "3등", 4: "4등", 5: "5등"}


def prize_rank(hits, bonus_hit):
    """적중 개수 → 등수 (0 = 낙첨)."""
    if hits == 6:
        return 1
    if hits == 5:
        return 2 if bonus_hit else 3
    if hits == 4:
        return 4
    if hits == 3:
        return 5
    return 0


def winner_positions(scores, numbers):
    """당첨 번호 각각이 모델 점수 순위(1=최고점)에서 몇 위였는지."""
    order = np.argsort(-np.asarray(scores, dtype=float), kind="stable")
    position = np.empty(NUM_COUNT, dtype=int)
    position[order] = np.arange(1, NUM_COUNT + 1)
    return [int(position[n - 1]) for n in sorted(numbers)]


def draw_auc(scores, numbers):
    """당첨 번호(6개)가 미당첨 번호(39개)보다 높은 점수를 받았을 확률."""
    s = np.asarray(scores, dtype=float)
    mask = np.zeros(NUM_COUNT, dtype=bool)
    mask[np.asarray(numbers) - 1] = True
    pos, neg = s[mask], s[~mask]
    greater = (pos[:, None] > neg[None, :]).mean()
    ties = (pos[:, None] == neg[None, :]).mean()
    return float(greater + 0.5 * ties)


def evaluate_draw(draw_no, numbers, bonus, rec):
    """추천(rec: storage.official_recommendation 결과)을 실제 당첨 번호로 채점."""
    win = set(numbers)
    hits, ranks = [], []
    for game in rec["games"]:
        h = len(win & set(game))
        hits.append(h)
        ranks.append(prize_rank(h, bonus is not None and bonus in game))
    scores = rec.get("scores")
    return {
        "draw_no": draw_no,
        "recommendation_id": rec["id"],
        "confirmed": rec["is_confirmed"],
        "numbers": sorted(numbers),
        "bonus": bonus,
        "games": rec["games"],
        "hits": hits,
        "ranks": ranks,
        "winner_positions": winner_positions(scores, numbers) if scores else None,
        "auc": draw_auc(scores, numbers) if scores else None,
        "model_backend": rec.get("model_backend"),
        "trained_draws": rec.get("trained_draws"),
    }


def best_result_text(ev):
    """'최고 3개 적중 · 5등' 같은 한 줄 요약."""
    best = max(ev["hits"])
    won = [r for r in ev["ranks"] if r]
    rank_text = f" · {PRIZE_NAMES[min(won)]}" if won else ""
    return f"최고 {best}개 적중{rank_text}"


def hits_noise_band(games):
    """무작위로 골라도 게임당 평균 적중이 0.8 에서 이만큼(약 95%)은 흔들릴 수 있다."""
    return 2 * (RANDOM_HITS_VAR / games) ** 0.5 if games else float("inf")


def summarize(evals):
    """누적 성적과 같은 조건의 무작위 기대값."""
    if not evals:
        return None
    hits = np.array([h for ev in evals for h in ev["hits"]])
    ranks = np.array([r for ev in evals for r in ev["ranks"]])
    scored = [ev for ev in evals if ev["winner_positions"]]
    positions = np.array([p for ev in scored for p in ev["winner_positions"]])
    won = ranks[ranks > 0]
    return {
        "draws": len(evals),
        "games": int(hits.size),
        "confirmed_draws": sum(1 for ev in evals if ev["confirmed"]),
        "hits_per_game": float(hits.mean()),
        "prize_rate": float((ranks > 0).mean()),
        "prize_games": int(won.size),
        "best_rank": int(won.min()) if won.size else 0,
        "auc": float(np.mean([ev["auc"] for ev in scored])) if scored else None,
        "top_k": float((positions <= TOP_K).sum() / len(scored)) if scored else None,
        "mean_position": float(positions.mean()) if scored else None,
        "reliable": len(evals) >= MIN_RELIABLE_DRAWS,
    }
