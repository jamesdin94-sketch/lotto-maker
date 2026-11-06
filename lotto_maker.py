"""
로또 조합 메이커 V1.0  (표준 라이브러리만 사용 · 설치할 패키지 없음)
기존 ny_* 연구 코드(전략 격자 · Enigma 암호키 · AI 코어 · FT≥1 영역)를 그대로 이어받아 업그레이드한 버전.

흐름:  ① 전략을 과거 300회로 시뮬레이션  ② 당첨 횟수·당첨금 순위표  ③ 내가 전략을 고르거나 추천(1위)  ④ 번호 뽑기·저장  ⑤ 추첨 뒤 결과 확인
전략 가족:  F 필터 격자(쌍·삼중·핫·콜드·AC·직전 겹침 + FT≥1) / E Enigma 암호키(ROT·MIRROR·SUM·DIFF·BONUS·SWAP·GAP·XOR 코어) / A AI 코어 12
게임:       한국 로또 6/45(1~최신 회차 전체)  ·  뉴욕 로또 6/59(data.ny.gov 전체 이력)
정직한 한 줄: 순위 1위는 '과거에 운이 좋았던' 전략일 수 있어서, 순위를 정한 구간과 따로 떼어 둔 최근 구간(검증 구간)의 성적을 함께 보여 준다.
              로또는 매 회 독립이라 어떤 번호든 1등 확률은 같다. 오락으로, 여유 자금 안에서만.

실행:  python lotto_maker.py            (메뉴)      python lotto_maker.py --game ny   (뉴욕 6/59)
       python lotto_maker.py --update   (최신 당첨번호)   python lotto_maker.py --check  (저장한 번호 결과)
       python lotto_maker.py --weekly   (금요일 주간 분석: 지난주 성적·부진 전략 정리·이번 주 추천)   --pool (25수 풀 분석)
"""
import csv
import json
import os
import random
import sys
import urllib.request
import zlib
from collections import Counter
from itertools import combinations
from math import comb

VERSION = "1.0"   # 구조가 바뀌면 앞자리(2.0), 전략·수치만 바뀌면 소수점(1.1). CHANGELOG.md 참고
HERE = os.path.dirname(os.path.abspath(__file__))
W = 10            # '최근' = 직전 10회
SAMPLE = 2000     # 필터 격자 시뮬레이션: 회차마다 무작위 후보 수
CORE_SAMPLE = 150 # 코어 전략 시뮬레이션: 회차마다 만드는 후보 수
ROUNDS, SPLIT = 300, 200   # 시뮬레이션 회차 수 / 앞 200 = 선택 구간, 뒤 100 = 검증 구간
ENIGMA_WIN = 100  # 암호키 신뢰도를 계산하는 직전 회차 수

GAMES = {
    "kr": {"name": "한국 로또 6/45", "N": 45, "hist": "lotto_history.csv"},
    "ny": {"name": "뉴욕 로또 6/59", "N": 59, "hist": "ny_history.csv"},
}


class Game:
    def __init__(self, key):
        g = GAMES[key]
        self.key, self.name, self.N = key, g["name"], g["N"]
        self.path = os.path.join(HERE, g["hist"])
        self.cache = os.path.join(HERE, f"sim_cache_{key}.json")
        self.picks = os.path.join(HERE, f"my_picks_{key}.csv")
        self.draws = self.load()

    # draws: [(회차, 번호6, 보너스, [1~5등 당첨금] 또는 None)]
    def load(self):
        rows = []
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    amt = [int(r.get(f"a{k}") or 0) for k in range(1, 6)] if "a1" in r else None
                    rows.append((int(r["round"]), tuple(sorted(int(r[f"n{i}"]) for i in range(1, 7))), int(r["bonus"]), amt))
        rows.sort()
        return rows

    def save(self):
        with open(self.path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["round", "n1", "n2", "n3", "n4", "n5", "n6", "bonus"] + (["a1", "a2", "a3", "a4", "a5"] if self.key == "kr" else []))
            for rd, nums, b, amt in self.draws:
                w.writerow([rd, *nums, b] + ((amt or [0] * 5) if self.key == "kr" else []))

    def update(self):
        n0 = len(self.draws)
        try:
            self.update_kr() if self.key == "kr" else self.update_ny()
        except Exception as e:
            print(f"  다운로드 실패: {e}")
        self.save()
        print(f"  {len(self.draws) - n0}개 회차 추가, 마지막 회차 {self.draws[-1][0] if self.draws else '-'}")

    def update_kr(self):
        n = self.draws[-1][0] + 1 if self.draws else 1
        while True:
            req = urllib.request.Request(f"https://www.dhlottery.co.kr/lt645/selectPstLt645Info.do?srchLtEpsd={n}", headers={"User-Agent": "Mozilla/5.0"})
            lst = json.load(urllib.request.urlopen(req, timeout=20))["data"]["list"]
            if not lst or not lst[0].get("tm1WnNo"):
                break
            x = lst[0]
            self.draws.append((n, tuple(sorted(x[f"tm{i}WnNo"] for i in range(1, 7))), x["bnsWnNo"], [x.get(f"rnk{k}WnAmt") or 0 for k in range(1, 6)]))
            n += 1

    def update_ny(self):
        url = "https://data.ny.gov/resource/6nbc-h7bj.json?$limit=50000&$order=draw_date%20ASC"
        rows = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60))
        self.draws = [(i + 1, tuple(sorted(int(x) for x in r["winning_numbers"].split())), int(r["bonus"]), None) for i, r in enumerate(rows)]


# ---------------------------------------------------------------- 번호의 특징 (기존 build_ctx / combo_stats 와 같은 정의)
def context(draws, i):
    """i번째 회차 직전 W회: 쌍(FP)·삼중(FT) 집합, 번호 빈도, 직전 당첨번호"""
    fp, ft, nf = set(), set(), Counter()
    for _, nums, _, _ in draws[i - W:i]:
        fp.update(combinations(nums, 2))
        ft.update(combinations(nums, 3))
        nf.update(nums)
    return fp, ft, nf, draws[i - 1][1]


def ac_of(c):
    return len({c[j] - c[i] for i in range(6) for j in range(i + 1, 6)})   # 기존 ac_fn 정의(차이의 종류 수)


def feat(c, ctx):
    fp, ft, nf, prev = ctx
    return (sum(p in fp for p in combinations(c, 2)), sum(t in ft for t in combinations(c, 3)),
            sum(nf[n] >= 2 for n in c), sum(nf[n] == 0 for n in c), ac_of(c), len(set(c) & set(prev)))


def rank_of(c, win, bonus):
    h = len(set(c) & set(win))
    return 1 if h == 6 else 2 if h == 5 and bonus in c else 3 if h == 5 else 4 if h == 4 else 5 if h == 3 else 0


def p5_of(N):   # 장당 5등 이상 확률
    return sum(comb(6, h) * comb(N - 6, 6 - h) for h in (3, 4, 5, 6)) / comb(N, 6)


# ---------------------------------------------------------------- F 가족: 필터 격자 (기존 ny_strategy_selector 의 격자 + FT≥1 + 직전 겹침)
FP_OPT = [(0, 0), (1, 2), (2, 3), (2, 4), (3, 4), (0, 1), None]
FT_OPT = [(0, 0), (0, 1), (1, 99), None]
HOT_OPT = [(0, 1), (1, 2), (2, 3), (3, 4), (3, 5), None]
COLD_OPT = [(0, 0), (0, 1), (0, 2), None]
AC_OPT = [(8, 11), (9, 13), (7, 15), None]
OV_OPT = [(0, 1), None]
SPACES = (FP_OPT, FT_OPT, HOT_OPT, COLD_OPT, AC_OPT, OV_OPT)
LAB = ("쌍", "삼중", "핫", "콜드", "AC", "겹침")


def tag(name, o):
    return None if o is None else f"{name}≥{o[0]}" if o[1] == 99 else f"{name}={o[0]}" if o[0] == o[1] else f"{name}={o[0]}~{o[1]}"


def filter_grid():
    out = []
    for fp in FP_OPT:
        for ft in FT_OPT:
            for hot in HOT_OPT:
                for cold in COLD_OPT:
                    for ac in AC_OPT:
                        for ov in OV_OPT:
                            opts = (fp, ft, hot, cold, ac, ov)
                            parts = [tag(n, o) for n, o in zip(LAB, opts) if o]
                            out.append((opts, " + ".join(parts) if parts else "필터 없음(무작위)"))
    return out


def passes(f, opts):
    return all(o is None or o[0] <= v <= o[1] for v, o in zip(f, opts))


def eval_filters(tbl):
    """집계표 tbl[특징]=[장수,1~5등 횟수,당첨금] 에서 격자의 모든 전략 결과를 한 번에. 차원을 하나씩 걸러 가며 계산량을 줄인다."""
    res = {}

    def rec(d, subset, opts):
        if d == 6:
            res[tuple(opts)] = (sum(e[0] for _, e in subset), sum(e[1] + e[2] + e[3] + e[4] + e[5] for _, e in subset),
                                sum(e[1] + e[2] + e[3] + e[4] for _, e in subset), sum(e[6] for _, e in subset))
            return
        for o in SPACES[d]:
            rec(d + 1, subset if o is None else [(f, e) for f, e in subset if o[0] <= f[d] <= o[1]], opts + [o])
    rec(0, list(tbl.items()), [])
    return res


# ---------------------------------------------------------------- E 가족: Enigma 암호키 (기존 ny_enigma_cipher_v2 의 9개 함수를 N 에 맞게 일반화)
def make_ciphers(N):
    def rot(k):
        return lambda nums, b, pn, pb: tuple(sorted((n - 1 + k) % N + 1 for n in nums))

    def mirror(nums, b, pn, pb):
        return tuple(sorted(N + 1 - n for n in nums))

    def sum_based(nums, b, pn, pb):
        s = sum(nums)
        return tuple(sorted({(s + off) % N + 1 for off in range(-3, 4)}))

    def diff(nums, b, pn, pb):
        return tuple(sorted({abs(c - p) % N + 1 for p in pn for c in nums if abs(c - p) > 0}))[:6]

    def bonus(nums, b, pn, pb):
        return tuple(sorted({(n + b) % N + 1 for n in nums}))[:6]

    def swap(nums, b, pn, pb):
        return tuple(sorted(nums))

    def gap(nums, b, pn, pb):
        s = sorted(nums)
        out = {s[i] + (s[i + 1] - s[i]) * m for i in range(5) for m in (1, 2) if 1 <= s[i] + (s[i + 1] - s[i]) * m <= N}
        return tuple(sorted(out))[:6]

    def xor(nums, b, pn, pb):
        return tuple(sorted({n ^ b for n in nums if 1 <= (n ^ b) <= N}))[:6]
    return {"ROT+1": rot(1), "ROT+2": rot(2), "MIRROR": mirror, "SUM": sum_based, "DIFF": diff, "BONUS": bonus, "SWAP": swap, "GAP": gap, "XOR": xor}


def p_overlap2(N, m):
    """무작위로 m개를 골랐을 때 당첨번호 6개와 2개 이상 겹칠 확률"""
    if m < 2:
        return 0.0
    return 1 - sum(comb(6, h) * comb(N - 6, m - h) for h in (0, 1) if m - h >= 0) / comb(N, m)


def cipher_table(game):
    """각 암호키의 신뢰도: 직전 회차에서 만든 예측이 다음 회차와 2개 이상 겹친 비율(기존 기준) vs 무작위 기대"""
    d, out = game.draws, {}
    for name, fn in make_ciphers(game.N).items():
        hit = tot = 0
        exp = 0.0
        for j in range(1, len(d) - 1):
            try:
                pred = fn(d[j][1], d[j][2], d[j - 1][1], d[j - 1][2])
            except Exception:
                continue
            if pred:
                tot += 1
                exp += p_overlap2(game.N, len(set(pred)))
                hit += len(set(pred) & set(d[j + 1][1])) >= 2
        out[name] = (hit, tot, exp)
    return out


def enigma_core(game, i, top=5, size=8, only=None):
    """i번째 회차를 앞두고 암호키 코어 번호를 만든다. 직전 ENIGMA_WIN 회로 신뢰도를 매겨 상위 top 개 암호키의 예측을 모아 득표 상위 size 개."""
    d = game.draws
    ciphers = make_ciphers(game.N)
    names = [only] if only else None
    if names is None:
        sc = {}
        for name, fn in ciphers.items():
            hit = tot = 0
            for j in range(max(1, i - ENIGMA_WIN), i - 1):
                try:
                    pred = fn(d[j][1], d[j][2], d[j - 1][1], d[j - 1][2])
                except Exception:
                    continue
                if pred:
                    tot += 1
                    hit += len(set(pred) & set(d[j + 1][1])) >= 2
            sc[name] = hit / tot if tot else 0
        names = [n for n, _ in sorted(sc.items(), key=lambda x: -x[1])[:top]]
    votes = Counter()
    for name in names:
        try:
            votes.update(ciphers[name](d[i - 1][1], d[i - 1][2], d[i - 2][1], d[i - 2][2]))
        except Exception:
            pass
    return {n for n, _ in votes.most_common(size)}, names


# ---------------------------------------------------------------- A 가족: AI 코어 12 (기존 ny_ai_auto_selector_v2 의 점수 규칙)
def ai_core(game, i, size=12):
    nf, pf = Counter(), Counter()
    for _, nums, _, _ in game.draws[i - W:i]:
        nf.update(nums)
        pf.update(combinations(nums, 2))
    hot = dict(sorted(nf.items(), key=lambda x: -x[1])[:8])
    top_pairs = pf.most_common(3)
    score = {n: hot.get(n, 0) * 2 + (1 if nf.get(n, 0) == 0 else 0) + sum(cnt * 1.5 for p, cnt in top_pairs if n in p) for n in range(1, game.N + 1)}
    return {n for n, _ in sorted(score.items(), key=lambda x: (-x[1], x[0]))[:size]}


def sum_band(game, i):
    s = sorted(sum(x[1]) for x in game.draws[max(0, i - 300):i])
    return s[int(len(s) * 0.05)], s[int(len(s) * 0.95)]


def core_tickets(game, core, ctx, band, n, rng, mode, picks=(3, 4, 5), fixed=(), banned=(), past=frozenset(), max_overlap=6):
    """코어 번호 중심 조합(기존 generate_core_combos / generate_enigma_combos). mode: none=필터 없음 /
    enigma=FT≥1·AC 8~14·합 구간·직전 겹침≤2 / ai=쌍=0·AC 9~13·합 구간·직전 겹침≤1"""
    core_l = [x for x in sorted(core) if x not in banned and x not in fixed]
    supp = [x for x in range(1, game.N + 1) if x not in core and x not in banned and x not in fixed]
    out, tries = [], 0
    while len(out) < n and tries < 40 * n + 4000:
        tries += 1
        k = rng.choice(picks)
        base = list(fixed) + rng.sample(core_l, max(0, min(k - len(fixed), len(core_l))))
        need = 6 - len(base)
        if need < 0 or need > len(supp):
            continue
        c = tuple(sorted(base + rng.sample([x for x in supp if x not in base], need)))
        if c in past:
            continue
        if mode != "none":
            f = feat(c, ctx)
            if mode == "enigma" and not (f[1] >= 1 and 8 <= f[4] <= 14 and band[0] <= sum(c) <= band[1] and f[5] <= 2):
                continue
            if mode == "ai" and not (f[0] == 0 and 9 <= f[4] <= 13 and band[0] <= sum(c) <= band[1] and f[5] <= 1):
                continue
        if any(len(set(c) & set(o)) > max_overlap for o in out):
            continue
        out.append(c)
    return out


# ---------------------------------------------------------------- P 가족: 풀(후보 번호 묶음) 전략 — 번호를 N개 중 M개(한국 25개)로 줄인 뒤 그 안에서만 고른다
def pool_size(game):
    return 25 if game.N == 45 else 33   # 6/45 는 25수(조합 177,100개), 6/59 는 같은 비율인 33개


def pool_of(game, kind, i):
    """i번째 회차를 앞두고 '남길 번호' 풀을 만든다. 제외 점수가 높은 번호부터 지워 풀 크기만 남긴다(자체 규칙, 외부 채널 규칙 아님)."""
    d, N = game.draws, game.N
    nf = Counter()
    for _, nums, _, _ in d[i - W:i]:
        nf.update(nums)
    prev = set(d[i - 1][1])
    if kind == "pool1":    # 직전 당첨번호와 최근 과출현 번호부터 제외
        score = {n: (5 if n in prev else 0) + nf[n] for n in range(1, N + 1)}
    elif kind == "pool2":  # 최근 한 번도 안 나온 번호(콜드)부터 제외
        score = {n: (3 if nf[n] == 0 else 0) - nf[n] * 0.1 for n in range(1, N + 1)}
    elif kind == "pool3":  # 무작위 풀(대조군)
        r = random.Random(i * 7919 + N)
        score = {n: r.random() for n in range(1, N + 1)}
    else:
        raise ValueError(kind)
    drop = sorted(range(1, N + 1), key=lambda n: (-score[n], n))[:N - pool_size(game)]
    return {n for n in range(1, N + 1) if n not in drop}


CORE_STRATEGIES = [("E1", "Enigma 상위5 코어 + FT≥1·AC·합·겹침≤2", "enigma", "top", (3, 4, 5)), ("E2", "Enigma 상위5 코어 (필터 없음)", "none", "top", (3, 4, 5))]
CORE_STRATEGIES += [(f"E{i + 3}", f"Enigma {name} 코어 + 필터", "enigma", name, (3, 4, 5)) for i, name in enumerate(make_ciphers(45))]
CORE_STRATEGIES += [("A1", "AI 코어12 + 쌍=0·AC 9~13·합·겹침≤1", "ai", "", (3, 4)), ("A2", "AI 코어12 (필터 없음)", "none", "", (3, 4)),
                    ("P1", "풀(25수): 직전·과출현 제외 후 풀 안에서만", "none", "pool1", (6,)), ("P2", "풀(25수): 콜드 제외 후 풀 안에서만", "none", "pool2", (6,)),
                    ("P3", "풀(25수): 무작위 풀 안에서만 (대조군)", "none", "pool3", (6,))]


def core_of(game, sid, i, memo=None):
    """전략 sid 의 코어(또는 풀) 번호. memo 는 같은 회차에서 반복 계산을 피하기 위한 저장소(시뮬레이션용)."""
    spec = "ai" if sid[0] == "A" else next(s[3] for s in CORE_STRATEGIES if s[0] == sid)
    if memo is not None and spec in memo:
        return memo[spec]
    if spec == "ai":
        core = ai_core(game, i)
    elif spec.startswith("pool"):
        core = pool_of(game, spec, i)
    else:
        core = enigma_core(game, i, only=None if spec == "top" else spec)[0]
    if memo is not None:
        memo[spec] = core
    return core


def picks_of(sid):
    return next(s[4] for s in CORE_STRATEGIES if s[0] == sid)


# ---------------------------------------------------------------- 시뮬레이션
def simulate(game, seed=2026):
    d, N = game.draws, game.N
    rng = random.Random(seed)
    agg = [dict(), dict()]
    win_marg = [Counter() for _ in range(6)]   # 실제 당첨번호의 특징 분포 (회차마다 그 회차 직전 자료로 계산)
    core_res = {s[0]: [[0, 0, 0, 0, 0], [0, 0, 0, 0, 0]] for s in CORE_STRATEGIES}   # [구간][장수, 5등+, 4등+, 3등+, 당첨금]
    core_rr = {s[0]: [[], []] for s in CORE_STRATEGIES}
    for k, i in enumerate(range(len(d) - ROUNDS, len(d))):
        part = 0 if k < SPLIT else 1
        ctx = context(d, i)
        _, win, bonus, amt = d[i]
        tbl = agg[part]
        for dim, v in enumerate(feat(win, ctx)):
            win_marg[dim][v] += 1
        for _ in range(SAMPLE):
            c = tuple(sorted(rng.sample(range(1, N + 1), 6)))
            e = tbl.setdefault(feat(c, ctx), [0] * 7)
            e[0] += 1
            r = rank_of(c, win, bonus)
            if r:
                e[r] += 1
                if r >= 3 and amt:
                    e[6] += amt[r - 1]
        band, memo = sum_band(game, i), {}
        for sid, _, mode, _spec, picks in CORE_STRATEGIES:
            x = core_res[sid][part]
            n0, h0 = x[0], x[1]
            for c in core_tickets(game, core_of(game, sid, i, memo), ctx, band, CORE_SAMPLE, rng, mode, picks=picks):
                r = rank_of(c, win, bonus)
                x[0] += 1
                x[1] += r > 0
                x[2] += 0 < r <= 4
                x[3] += 0 < r <= 3
                x[4] += amt[r - 1] if (r >= 3 and amt) else 0
            if x[0] > n0:
                core_rr[sid][part].append([x[0] - n0, x[1] - h0])   # 회차별 (장수, 5등+ 장수): 코어 전략은 장끼리 번호를 공유해 결과가 함께 움직이므로 z 를 회차 단위로 계산한다
        if (k + 1) % 50 == 0:
            print(f"    시뮬레이션 {k + 1}/{ROUNDS} 회차 …")
    return agg, core_res, win_marg, core_rr


def build_table(game):
    d = game.draws
    last = d[-1][0]
    if os.path.exists(game.cache):
        try:
            c = json.load(open(game.cache, encoding="utf-8"))
            if c.get("last") == last and c.get("v") == VERSION:
                return c["rows"]
        except Exception:
            pass
    print(f"  {game.name}: 전략을 과거 {ROUNDS}회로 시뮬레이션합니다 (약 1~2분, 이번 회차 동안 저장됩니다).")
    agg, core_res, win_marg, core_rr = simulate(game)
    rnd_marg = [Counter() for _ in range(6)]
    for tbl in agg:
        for f, e in tbl.items():
            for dim, v in enumerate(f):
                rnd_marg[dim][v] += e[0]
    signals = {"win": [{str(k): c for k, c in m.items()} for m in win_marg], "rnd": [{str(k): c for k, c in m.items()} for m in rnd_marg]}
    fr = [eval_filters(agg[0]), eval_filters(agg[1])]
    rows, seen = [], set()
    for opts, name in sorted(filter_grid(), key=lambda x: sum(o is not None for o in x[0])):
        s, v = fr[0][tuple(opts)], fr[1][tuple(opts)]
        if s[0] < 20000 or v[0] < 10000 or (s, v) in seen:   # 통과 후보가 너무 적거나 결과가 같은 전략은 가장 단순한 하나만
            continue
        seen.add((s, v))
        rows.append({"id": "F" + str(len(rows) + 1), "name": name, "kind": "F", "opts": [list(o) if o else None for o in opts],
                     "sel": [s[0], s[1], s[2], 0, s[3]], "ver": [v[0], v[1], v[2], 0, v[3]]})
    for sid, name, mode, spec, picks in CORE_STRATEGIES:
        if core_res[sid][0][0] >= 5000 and core_res[sid][1][0] >= 2500:   # 조건을 만족하는 후보를 거의 못 만든 코어 전략은 제외
            rows.append({"id": sid, "name": name, "kind": sid[0], "opts": None, "sel": core_res[sid][0], "ver": core_res[sid][1], "rr": core_rr[sid]})
    json.dump({"last": last, "v": VERSION, "rows": rows, "signals": signals}, open(game.cache, "w", encoding="utf-8"), ensure_ascii=False)
    return rows


def zscore(hits, n, p):
    sd = (n * p * (1 - p)) ** 0.5
    return (hits - n * p) / sd if sd else 0.0


def row_z(row, part, p5):
    """z: 필터 전략은 후보 장 단위, 코어·풀 전략은 회차 단위로 계산한다(같은 회차의 장끼리 번호를 공유해 결과가 함께 움직이기 때문)."""
    rr = row.get("rr")
    if rr and len(rr[part]) >= 5:
        rates = [h / n for n, h in rr[part] if n]
        m = sum(rates) / len(rates)
        sd = (sum((x - m) ** 2 for x in rates) / (len(rates) - 1)) ** 0.5
        return (m - p5) / (sd / len(rates) ** 0.5) if sd else 0.0
    c = row["sel" if part == 0 else "ver"]
    return zscore(c[1], c[0], p5)


def show_table(game, rows, key, top=15):
    p5 = p5_of(game.N)
    rate = lambda r, k: r[k][1] / max(r[k][0], 1)
    keys = {"1": ("5등 이상 적중률", lambda r: rate(r, "sel")), "2": ("4등 이상 적중률", lambda r: r["sel"][2] / max(r["sel"][0], 1)),
            "3": ("장당 당첨금", lambda r: r["sel"][4] / max(r["sel"][0], 1)),
            "4": ("전체 300회 합산 5등 이상 적중률", lambda r: (r["sel"][1] + r["ver"][1]) / max(r["sel"][0] + r["ver"][0], 1))}
    title, fn = keys[key]
    rows = [r for r in rows if r["sel"][0] >= 5000 and r["ver"][0] >= 2500]
    best = sorted(rows, key=fn, reverse=True)[:top]
    base = next(r for r in rows if r["name"].startswith("필터 없음"))
    money = game.key == "kr"
    print(f"\n  [시뮬레이션 순위] {game.name} · 기준: {title} (선택 구간 {SPLIT}회 → 검증 구간 {ROUNDS - SPLIT}회)")
    print(f"  {'ID':>4} {'전략':<46}{'5등+률':>8}{'z':>6}{'장당금':>8} | {'검증 5등+률':>11}{'z':>6}{'장당금':>8}")
    for r in [base] + best:
        s, v = r["sel"], r["ver"]
        sm = f"{s[4] / max(s[0], 1):>8.0f}" if money else f"{'-':>8}"
        vm = f"{v[4] / max(v[0], 1):>8.0f}" if money else f"{'-':>8}"
        print(f"  {r['id']:>4} {r['name'][:44]:<46}{rate(r, 'sel'):>8.2%}{row_z(r, 0, p5):>6.1f}{sm} | {rate(r, 'ver'):>11.2%}{row_z(r, 1, p5):>6.1f}{vm}")
    print(f"  (무작위 기대 5등+률 {p5:.2%}" + (", 장당 당첨금(3~5등만) 약 220원" if money else ", 뉴욕은 당첨금 자료가 없어 횟수만 표시") + ". z=무작위 대비 표준편차 배수: 전략 수백 개 중 1등이 3~4 나오는 것은 우연으로 설명됩니다)")
    return best


def show_signals(game):
    """[신호 분석] 실제 당첨번호의 특징이 무작위 후보보다 많이/적게 나오는가 (기존 ny_deep_signal_analysis 의 '과다 표현' 분석)"""
    try:
        sg = json.load(open(game.cache, encoding="utf-8"))["signals"]
    except Exception:
        print("  시뮬레이션 결과가 없습니다. 먼저 순위표를 만드세요.")
        return
    print(f"\n  [신호 분석] 최근 {ROUNDS}회 실제 당첨번호 vs 무작위 후보 ({game.name}). 배수 = 당첨번호 비율 ÷ 무작위 비율, z = 우연으로 설명되는 정도")
    for dim, name in enumerate(LAB):
        w, r = sg["win"][dim], sg["rnd"][dim]
        nw, nr = sum(w.values()), sum(r.values())
        print(f"   ▷ {name}")
        for v in sorted(set(map(int, w)) | set(map(int, r))):
            pw, pr = w.get(str(v), 0) / nw, r.get(str(v), 0) / nr
            if pr < 0.01 and pw < 0.01:
                continue
            z = (w.get(str(v), 0) - nw * pr) / ((nw * pr * (1 - pr)) ** 0.5) if 0 < pr < 1 else 0
            print(f"      {v:>3}: 당첨 {pw:>6.1%}  무작위 {pr:>6.1%}  {pw / pr if pr else 0:>5.2f}배  z {z:>5.1f}" + ("  ←" if abs(z) >= 2 else ""))
    print("  (값이 여러 개이면 z가 2를 넘는 값이 우연히 나오기 마련입니다. 같은 값이 구간을 바꿔도 반복될 때만 의미를 둡니다)")


def show_ciphers(game):
    print(f"\n  [Enigma 암호키 신뢰도] 직전 회차에서 만든 예측이 다음 회차와 2개 이상 겹친 비율 ({game.name}, 전체 {len(game.draws)}회)")
    print(f"  {'암호키':<8}{'신뢰도':>8}{'무작위 기대':>12}{'차이 z':>8}")
    for name, (h, t, e) in sorted(cipher_table(game).items(), key=lambda x: -(x[1][0] / max(x[1][1], 1))):
        if t:
            sd = (e * (1 - e / t)) ** 0.5
            print(f"  {name:<8}{h / t:>8.1%}{e / t:>12.1%}{(h - e) / sd if sd else 0:>8.1f}")


# ---------------------------------------------------------------- 번호 뽑기
def make_tickets(game, row, n, rng, fixed=(), banned=(), i=None):
    d, N = game.draws, game.N
    i = len(d) if i is None else i   # i: 몇 번째 회차를 앞두고 뽑는가(기본=다음 회차). 지난 회차를 넣으면 그때 자료만으로 뽑아 볼 수 있다
    ctx = context(d, i)
    past = {c for _, c, _, _ in d[:i]}
    if row["kind"] == "F":
        opts = [tuple(o) if o else None for o in row["opts"]]
        pool = [x for x in range(1, N + 1) if x not in banned and x not in fixed]
        out, tries = [], 0
        while len(out) < n and tries < 600000:
            tries += 1
            c = tuple(sorted(list(fixed) + rng.sample(pool, 6 - len(fixed))))
            if c in past or not passes(feat(c, ctx), opts) or any(len(set(c) & set(o)) > 4 for o in out):
                continue
            out.append(c)
        return out, ctx, None
    mode = next(s[2] for s in CORE_STRATEGIES if s[0] == row["id"])
    core = core_of(game, row["id"], i)
    return core_tickets(game, core, ctx, sum_band(game, i), n, rng, mode, picks=picks_of(row["id"]), fixed=fixed, banned=banned, past=past, max_overlap=4), ctx, core


def show_tickets(tickets, ctx, core=None):
    if core:
        print(f"\n  코어 번호: {', '.join(map(str, sorted(core)))}")
    print()
    for i, t in enumerate(tickets, 1):
        f = feat(t, ctx)
        cc = f"코어 {len(set(t) & set(core))} · " if core else ""
        print(f"  {i:2d}.  " + "  ".join(f"{n:2d}" for n in t) + f"     {cc}쌍 {f[0]} · 삼중 {f[1]} · 핫 {f[2]} · 콜드 {f[3]} · AC {f[4]} · 겹침 {f[5]} · 합 {sum(t)}")
    print()


# ---------------------------------------------------------------- 주간 기록: 저장 → 결과 확인
def save_picks(game, target, sid, name, tickets):
    new = not os.path.exists(game.picks)
    with open(game.picks, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["target_round", "strategy_id", "strategy_name", "ticket"])
        for t in tickets:
            w.writerow([target, sid, name, "-".join(map(str, t))])
    with open(os.path.join(HERE, f"combos_{game.key}_{target}.csv"), "w", newline="", encoding="utf-8") as f:   # 기존 코드처럼 구매용 CSV 도 남긴다
        w = csv.writer(f)
        w.writerow(["순번", "전략", "n1", "n2", "n3", "n4", "n5", "n6"])
        for i, t in enumerate(tickets, 1):
            w.writerow([i, name, *t])


def check_picks(game):
    if not os.path.exists(game.picks):
        print("  저장된 번호가 없습니다. 번호를 뽑을 때 저장을 선택하세요.")
        return
    res = {r: (c, b, a) for r, c, b, a in game.draws}
    p5 = p5_of(game.N)
    by, detail = {}, {}
    with open(game.picks, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rd = int(r["target_round"])
            if rd not in res:
                continue
            t = tuple(int(x) for x in r["ticket"].split("-"))
            win, bonus, amt = res[rd]
            rk = rank_of(t, win, bonus)
            hit = len(set(t) & set(win))
            e = by.setdefault(r["strategy_name"], {"n": 0, "hits": 0, "p5": 0, "best": 0, "money": 0})
            e["n"] += 1
            e["hits"] += hit
            e["p5"] += rk > 0
            e["best"] = max(e["best"], hit)
            e["money"] += amt[rk - 1] if (rk and amt) else 0
            for lab, v in (("홀수 개수", sum(x % 2 for x in t)), ("합 구간", "~120" if sum(t) < 120 else "120~150" if sum(t) < 150 else "150~")):
                x = detail.setdefault((lab, v), [0, 0])
                x[0] += 1
                x[1] += hit
    if not by:
        print("  아직 추첨이 끝난 저장 번호가 없습니다. 추첨 뒤 [3]으로 최신 당첨번호를 받은 뒤 다시 확인하세요.")
        return
    base = 36 / game.N
    lines = [f"# 로또 조합 메이커 V{VERSION} 주간 결과 ({game.name})", "", "| 전략 | 장수 | 평균 맞힘 | 5등 이상 | 기대 | 최고 | 당첨금 합 |", "|---|---|---|---|---|---|---|"]
    print(f"\n  {'전략':<46}{'장수':>5}{'평균':>6}{'5등+':>5}{'기대':>6}{'최고':>5}{'당첨금':>12}")
    for name, e in by.items():
        print(f"  {name[:44]:<46}{e['n']:>5}{e['hits'] / e['n']:>6.2f}{e['p5']:>5}{e['n'] * p5:>6.1f}{e['best']:>5}{e['money']:>12,}")
        lines.append(f"| {name} | {e['n']} | {e['hits'] / e['n']:.2f} | {e['p5']} | {e['n'] * p5:.1f} | {e['best']} | {e['money']:,} |")
    lines += ["", "## 세부 항목별 평균 맞힌 개수", "| 항목 | 값 | 장수 | 평균 맞힘 |", "|---|---|---|---|"]
    print(f"\n  세부 항목별 평균 맞힘 (무작위 기준 {base:.2f})")
    for (lab, v), (n, hs) in sorted(detail.items(), key=lambda x: (x[0][0], str(x[0][1]))):
        print(f"   {lab:<10}{str(v):>7} {n:>5}장  평균 {hs / n:.2f}")
        lines.append(f"| {lab} | {v} | {n} | {hs / n:.2f} |")
    lines += ["", f"무작위로 찍어도 평균 맞힌 개수는 {base:.2f}개, 5등 이상 비율은 약 {p5:.1%} 입니다. 표본이 적으면 우연으로 설명됩니다."]
    with open(os.path.join(HERE, f"weekly_report_{game.key}.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n  → weekly_report_{game.key}.md 저장")


# ---------------------------------------------------------------- 풀(25수) 분석
def pool_report(game, verbose=True):
    """유튜브 등에서 매주 '25수' 처럼 번호를 줄여 주는 방식이 실제로 당첨번호를 더 많이 담는지 확인한다.
    풀 안에 든 당첨번호 평균과, 당첨번호 6개가 모두 풀 안에 든 횟수를 무작위 기대와 비교한다(최근 ROUNDS 회, 그 회차 직전 자료만 사용)."""
    d, N = game.draws, game.N
    M = pool_size(game)
    exp_mean = 6 * M / N
    exp_full = comb(M, 6) / comb(N, 6)
    out = {}
    for kind, name in (("pool1", "직전·과출현 제외"), ("pool2", "콜드 제외"), ("pool3", "무작위 풀(대조군)")):
        cnts = []
        for i in range(len(d) - ROUNDS, len(d)):
            pool = pool_of(game, kind, i)
            cnts.append(len(pool & set(d[i][1])))
        m = sum(cnts) / len(cnts)
        sd = (sum((x - m) ** 2 for x in cnts) / (len(cnts) - 1)) ** 0.5
        full = sum(1 for x in cnts if x == 6)
        out[kind] = {"name": name, "mean": m, "z": (m - exp_mean) / (sd / len(cnts) ** 0.5) if sd else 0.0, "full": full, "rounds": len(cnts)}
    if verbose:
        print(f"\n  [풀 분석] {game.name}: 번호 {N}개 중 {M}개만 남기는 풀 (조합 {comb(M, 6):,}개 = 전체의 {exp_full:.2%})")
        print(f"  무작위 기대: 풀 안의 당첨번호 평균 {exp_mean:.2f}개, 6개가 모두 풀 안에 들 확률 {exp_full:.2%} (최근 {ROUNDS}회 기준 약 {exp_full * ROUNDS:.1f}회)")
        print(f"  {'풀 만드는 방법':<20}{'당첨번호 평균':>14}{'z':>7}{'6개 모두 포함':>14}")
        for k, v in out.items():
            print(f"  {v['name']:<20}{v['mean']:>14.2f}{v['z']:>7.1f}{v['full']:>10}회")
        print("  (풀이 당첨번호를 평균보다 많이 담지 못하면 풀 안에서 고르는 것은 확률을 올리지 못하고, 6개가 모두 풀 안에 들 확률이 낮아져 오히려 1등 가능성을 줄입니다)")
    return out


def pool_input_tickets(game, pool, opts, n, rng, i=None):
    """사용자가 입력한 풀(예: 유튜브에서 받은 25수) 안에서만 번호를 뽑는다. opts 가 있으면 필터 격자 조건도 함께 적용."""
    d = game.draws
    i = len(d) if i is None else i
    ctx = context(d, i)
    past = {c for _, c, _, _ in d[:i]}
    pl = sorted(pool)
    out, tries = [], 0
    while len(out) < n and tries < 400000:
        tries += 1
        c = tuple(sorted(rng.sample(pl, 6)))
        if c in past or (opts and not passes(feat(c, ctx), opts)) or any(len(set(c) & set(o)) > 4 for o in out):
            continue
        out.append(c)
    return out, ctx


# ---------------------------------------------------------------- 주간 분석: 지난주 성적 → 부진 전략 정리 → 이번 주 추천 → 누적 기록
NEW_IN_VERSION = {"P1": "풀(25수) 전략", "P2": "풀(25수) 전략", "P3": "풀(25수) 대조군"}   # 이번 버전에서 보완·추가한 전략


def ledger_path(game):
    return os.path.join(HERE, f"ledger_{game.key}.json")


def load_ledger(game):
    if os.path.exists(ledger_path(game)):
        try:
            return json.load(open(ledger_path(game), encoding="utf-8"))
        except Exception:
            pass
    return {"oos": {}, "status": {}, "weeks": {}}


def save_ledger(game, led):
    json.dump(led, open(ledger_path(game), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def settle_picks(game, led):
    """추첨이 끝난 회차에 저장해 둔 번호를 채점해 전략별 누적 기록(진짜 '미래' 성적)에 더한다."""
    if not os.path.exists(game.picks):
        return 0
    res = {r: (c, b, a) for r, c, b, a in game.draws}
    done = 0
    with open(game.picks, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rd = int(r["target_round"])
            if rd not in res or str(rd) in led["weeks"].get("settled", []):
                continue
            t = tuple(int(x) for x in r["ticket"].split("-"))
            win, bonus, amt = res[rd]
            rk = rank_of(t, win, bonus)
            e = led["oos"].setdefault(r["strategy_id"], {"name": r["strategy_name"], "n": 0, "h5": 0, "hits": 0, "money": 0, "weeks": {}})
            e["n"] += 1
            e["h5"] += rk > 0
            e["hits"] += len(set(t) & set(win))
            e["money"] += amt[rk - 1] if (rk and amt) else 0
            w = e["weeks"].setdefault(str(rd), [0, 0])
            w[0] += 1
            w[1] += rk > 0
            done += 1
    # 이미 채점한 회차 표시: 저장된 번호의 회차 중 결과가 나온 것 모두
    settled = set(led["weeks"].get("settled", []))
    with open(game.picks, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if int(r["target_round"]) in res:
                settled.add(str(int(r["target_round"])))
    led["weeks"]["settled"] = sorted(settled)
    return done


def update_status(game, rows, led):
    """부진한 전략 정리 규칙. ① 검증 구간 z ≤ -2.5 이고 합산 5등+률이 무작위보다 낮으면 '퇴출'  ② 진짜 미래 누적(저장한 번호)이 장 2,000개 이상이고 z ≤ -2 이면 '퇴출'.
    퇴출된 전략은 순위표와 추천에서 숨긴다(기록은 남김). 규칙이 까다로운 이유: 무작위 결과로 전략을 쉽게 버리면 그것도 우연에 속는 것이기 때문."""
    p5 = p5_of(game.N)
    base = next(r for r in rows if r["name"].startswith("필터 없음"))
    brate = (base["sel"][1] + base["ver"][1]) / (base["sel"][0] + base["ver"][0])
    changes = []
    for r in rows:
        if r is base:
            continue
        zv = row_z(r, 1, p5)
        rate = (r["sel"][1] + r["ver"][1]) / max(r["sel"][0] + r["ver"][0], 1)
        reason = None
        if zv <= -2.5 and rate < brate:
            reason = f"검증 구간 z {zv:.1f}, 합산 5등+률 {rate:.2%} < 무작위 {brate:.2%}"
        o = led["oos"].get(r["id"])
        if o and o["n"] >= 2000 and zscore(o["h5"], o["n"], p5) <= -2:
            reason = f"미래 누적 {o['n']}장 z {zscore(o['h5'], o['n'], p5):.1f}"
        st = led["status"].get(r["id"])
        if reason and not st:
            led["status"][r["id"]] = {"state": "퇴출", "since": game.draws[-1][0], "name": r["name"], "reason": reason}
            changes.append((r["id"], r["name"], reason))
    return changes


def active_rows(game, rows, led):
    return [r for r in rows if led["status"].get(r["id"], {}).get("state") != "퇴출" and r["sel"][0] >= 5000 and r["ver"][0] >= 2500]


def replay_week(game, rows, weeks=4, n=40):
    """지난 weeks 개 회차를 '그 회차 이전 자료만으로' 다시 뽑아 전략별로 채점한다. 순위표를 만들 때 쓴 회차가 섞여 있으니 참고용(진짜 미래 성적은 저장한 번호로 쌓는다)."""
    d = game.draws
    targets = [len(d) - 1 - w for w in range(weeks)]
    base = next(r for r in rows if r["name"].startswith("필터 없음"))
    best = sorted(rows, key=lambda r: (r["sel"][1] + r["ver"][1]) / max(r["sel"][0] + r["ver"][0], 1), reverse=True)[:8]
    ids = {r["id"]: r for r in [base] + best + [r for r in rows if r["kind"] != "F"]}
    out = {}
    for rid, row in ids.items():
        per = []
        for i in targets:
            rng = random.Random(i * 31 + zlib.crc32(rid.encode()))
            tk, _, _ = make_tickets(game, row, n, rng, i=i)
            _, win, bonus, amt = d[i]
            hits = [len(set(t) & set(win)) for t in tk]
            rks = [rank_of(t, win, bonus) for t in tk]
            per.append({"round": d[i][0], "n": len(tk), "avg": sum(hits) / max(len(tk), 1), "best": max(hits or [0]), "h5": sum(1 for r_ in rks if r_),
                        "money": sum(amt[r_ - 1] for r_ in rks if r_ >= 3 and amt)})
        out[rid] = {"name": row["name"], "weeks": per}
    return out


def weekly(game, rows, picks_per=5):
    """금요일에 돌리는 주간 분석. 데이터 갱신 → 지난주 저장 번호 채점 → 부진 전략 정리 → 지난주 재현표 → 이번 주 추천 저장 → 리포트(md·json)."""
    led = load_ledger(game)
    p5 = p5_of(game.N)
    d = game.draws
    nxt = d[-1][0] + 1
    settled = settle_picks(game, led)
    changes = update_status(game, rows, led)
    act = active_rows(game, rows, led)
    base = next(r for r in rows if r["name"].startswith("필터 없음"))
    rp = replay_week(game, act)
    last_round, win, bonus, _ = d[-1]
    print(f"\n  ===== 주간 분석: {game.name} · 지난 회차 {last_round}회 당첨번호 {' '.join(map(str, win))} + 보너스 {bonus} =====")
    print(f"\n  [1] 지난주({last_round}회) 선택별 결과 — 그 회차 이전 자료만으로 전략마다 40장 뽑아 채점 (무작위 평균 {36 / game.N:.2f}개, 5등+ 약 {p5:.1%})")
    print(f"  {'ID':>4} {'전략':<44}{'평균 맞힘':>9}{'최고':>5}{'5등+':>6} | 최근 4주 5등+ / 기대")
    for rid, v in sorted(rp.items(), key=lambda kv: -kv[1]["weeks"][0]["avg"]):
        w0 = v["weeks"][0]
        tot_h = sum(w["h5"] for w in v["weeks"])
        tot_n = sum(w["n"] for w in v["weeks"])
        print(f"  {rid:>4} {v['name'][:42]:<44}{w0['avg']:>9.2f}{w0['best']:>5}{w0['h5']:>6} | {tot_h:>3} / {tot_n * p5:>4.1f}")
    print("  (40장 × 4주는 표본이 작아 우연의 범위입니다. 순위표를 만들 때 쓴 회차가 섞여 있어 참고용입니다)")
    oos = led["oos"]
    print("\n  [2] 진짜 미래 성적 누적 — 추첨 전에 저장해 둔 번호를 추첨 뒤 채점한 기록")
    if oos:
        print(f"  {'ID':>4} {'전략':<44}{'장수':>6}{'평균 맞힘':>9}{'5등+':>6}{'기대':>6}{'당첨금':>10}")
        for rid, e in oos.items():
            print(f"  {rid:>4} {e['name'][:42]:<44}{e['n']:>6}{e['hits'] / e['n']:>9.2f}{e['h5']:>6}{e['n'] * p5:>6.1f}{e['money']:>10,}")
    else:
        print("  아직 없습니다. 이번 주 추천 번호를 저장해 두었으니 추첨 뒤 다음 주 분석부터 쌓입니다.")
    print("\n  [3] 부진한 전략 정리와 보완")
    if changes:
        tokens = Counter(t for _, name, _ in changes for t in name.split(" + "))
        print(f"   이번 주 새로 퇴출된 전략 {len(changes)}개. 가장 많이 겹친 필터: " + ", ".join(f"{t}({c}개)" for t, c in tokens.most_common(4)))
        for rid, name, reason in sorted(changes, key=lambda x: float(x[2].split("z ")[1].split(",")[0]))[:5]:
            print(f"   퇴출  {rid} {name[:40]} — {reason}")
        print("   (나머지는 ledger 파일에 사유와 함께 기록됩니다)")
    else:
        print("   이번 주 새로 퇴출된 전략: 없음 (기준: 검증 구간 z ≤ -2.5 이고 무작위보다 낮음 / 미래 누적 2,000장 이상에서 z ≤ -2)")
    gone = [f"{k}({v['name'][:20]})" for k, v in led["status"].items()]
    print(f"   현재 퇴출 목록: {', '.join(gone) if gone else '없음'}")
    for rid, what in NEW_IN_VERSION.items():
        print(f"   이번 버전 보완: {rid} {what}")
    # 이번 주 추천: 합산 5등+률 상위 3개 + 대표 전략, 번호를 저장해 미래 성적으로 쌓는다
    rank = sorted(act, key=lambda r: (r["sel"][1] + r["ver"][1]) / max(r["sel"][0] + r["ver"][0], 1), reverse=True)
    picks = [rank[0], rank[1], rank[2]]
    ids = {r["id"]: r for r in act}
    for rid in ("E1", "A1", "P1", base["id"]):
        if rid in ids and ids[rid] not in picks:
            picks.append(ids[rid])
    saved = {}   # 이번 회차용으로 이미 저장된 번호(추첨 전에 저장한 것)는 새로 뽑지 않고 그대로 쓴다
    if os.path.exists(game.picks):
        with open(game.picks, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if int(r["target_round"]) == nxt:
                    saved.setdefault(r["strategy_id"], []).append(tuple(int(x) for x in r["ticket"].split("-")))
    rec = []
    print(f"\n  [4] 이번 주({nxt}회) 추천 번호 — 전략마다 {picks_per}장 (저장해 두면 추첨 뒤 미래 성적으로 쌓입니다)")
    for row in picks:
        if row["id"] in saved:
            tk = saved[row["id"]]
        else:
            tk, ctx, core = make_tickets(game, row, picks_per, random.Random(nxt * 97 + zlib.crc32(row["id"].encode())))
            if tk:
                save_picks(game, nxt, row["id"], row["name"], tk)
        print(f"   {row['id']} {row['name'][:50]}")
        for t in tk:
            print("      " + "  ".join(f"{x:2d}" for x in t))
        rec.append({"id": row["id"], "name": row["name"], "tickets": [list(t) for t in tk]})
    pr = pool_report(game, verbose=True)
    led["weeks"]["last_report"] = d[-1][0]
    save_ledger(game, led)
    summary = {"game": game.key, "name": game.name, "last_round": last_round, "winning": list(win), "bonus": bonus, "next_round": nxt, "version": VERSION,
               "replay": rp, "oos": oos, "changes": [list(c) for c in changes], "retired": led["status"], "new": NEW_IN_VERSION,
               "recommend": rec, "pool": pr, "p5": p5, "settled_tickets": settled}
    json.dump(summary, open(os.path.join(HERE, f"weekly_{game.key}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n  → weekly_{game.key}.json 저장 (영상·글 제작에 사용)")
    return summary


# ---------------------------------------------------------------- 화면(CMD)
def ask(msg, default):
    s = input(f"  {msg} [{default}]: ").strip()
    return s or str(default)


def pick_numbers(game, rows, best):
    by_id = {r["id"].upper(): r for r in rows}
    print("\n  전략을 고르세요.  [ID] 순위표의 ID (예: F12, E1, A1)   [r] 추천(순위표 1위)   [c] 직접 필터 만들기   [p] 받아 온 25수 풀 안에서 고르기")
    ch = ask("선택", "r")
    if ch.lower() == "p":
        nums = [int(x) for x in input(f"  풀 번호를 쉼표나 띄어쓰기로 입력 ({pool_size(game)}개 권장): ").replace(",", " ").split()]
        if len(set(nums)) < 6 or any(not 1 <= x <= game.N for x in nums):
            print("  1~%d 사이 서로 다른 번호 6개 이상을 입력해 주세요." % game.N)
            return
        sid = ask("함께 쓸 필터 전략 ID (없으면 엔터)", "")
        opts = None
        if sid and sid.upper() in by_id and by_id[sid.upper()]["kind"] == "F":
            opts = [tuple(o) if o else None for o in by_id[sid.upper()]["opts"]]
        n = int(ask("몇 장", 5))
        tickets, ctx = pool_input_tickets(game, set(nums), opts, n, random.Random())
        print(f"\n  입력한 풀 {len(set(nums))}개 · 조합 {comb(len(set(nums)), 6):,}개 (전체 {comb(game.N, 6):,}개의 {comb(len(set(nums)), 6) / comb(game.N, 6):.2%}) · {game.draws[-1][0] + 1}회용")
        show_tickets(tickets, ctx)
        print(f"  풀 안에서 고른 장도 장당 1등 확률은 1/{comb(game.N, 6):,} 로 같고, 이번 당첨번호 6개가 모두 풀 안에 있을 확률만 {comb(len(set(nums)), 6) / comb(game.N, 6):.2%} 입니다.")
        if tickets and ask("이 번호를 저장할까요? (y/n)", "y").lower() == "y":
            save_picks(game, game.draws[-1][0] + 1, "POOL", f"입력 풀 {len(set(nums))}수" + (f" + {sid.upper()}" if opts else ""), tickets)
            print("  저장했습니다.")
        return
    if ch.lower() == "c":
        def rng_in(name):
            s = input(f"  {name} 범위 (예: 0-1, 없으면 엔터): ").strip()
            if not s:
                return None
            a, _, b = s.partition("-")
            return [int(a), int(b or a)]
        opts = [rng_in(n) for n in LAB]
        row = {"id": "C", "kind": "F", "opts": opts, "name": "직접 선택: " + (" + ".join(x for x in [tag(n, tuple(o) if o else None) for n, o in zip(LAB, opts)] if x) or "필터 없음")}
    else:
        row = best[0] if ch.lower() == "r" else by_id.get(ch.upper())
        if not row:
            print("  순위표에 없는 ID 입니다.")
            return
    n = int(ask("몇 장", 5))
    fixed = tuple(int(x) for x in ask("꼭 넣을 번호(쉼표, 없으면 엔터)", "").replace(" ", "").split(",") if x)
    banned = tuple(int(x) for x in ask("빼고 싶은 번호(쉼표, 없으면 엔터)", "").replace(" ", "").split(",") if x)
    tickets, ctx, core = make_tickets(game, row, n, random.Random(), fixed, banned)
    print(f"\n  전략 {row['id']}: {row['name']}  ({game.draws[-1][0] + 1}회용)")
    show_tickets(tickets, ctx, core)
    if tickets:
        print(f"  {len(tickets)}장이 모두 1등일 확률: 장당 1/{comb(game.N, 6):,} → 합계 약 {len(tickets) / comb(game.N, 6):.7%}")
        if ask("이 번호를 저장할까요? (y/n)", "y").lower() == "y":
            save_picks(game, game.draws[-1][0] + 1, row["id"], row["name"], tickets)
            print("  저장했습니다. 추첨 뒤 [3] → [4] 로 결과를 확인하세요.")


def main():
    print(f"\n  ===== 로또 조합 메이커 V{VERSION} =====")
    print("  주의: 이 도구는 당첨 확률을 높이지 않습니다. 오락으로, 여유 자금 안에서만. 상담 1336")
    if any(a in sys.argv for a in ("--game", "--update", "--check", "--weekly", "--pool")):
        key = "ny" if "ny" in sys.argv else "kr"
    else:
        key = {"1": "kr", "2": "ny"}.get(ask("게임  1=한국 6/45  2=뉴욕 6/59", 1), "kr")
    game = Game(key)
    if len(game.draws) < 500:
        print(f"  {game.name} 당첨번호를 내려받습니다" + (" (한국은 처음에 몇 분 걸립니다)." if key == "kr" else "."))
        game.update()
    if "--update" in sys.argv:
        game.update()
        return
    if "--check" in sys.argv:
        game.update()
        check_picks(game)
        return
    print(f"  저장된 당첨번호: 1회 ~ {game.draws[-1][0]}회  ({game.name})\n")
    all_rows = build_table(game)
    if "--weekly" in sys.argv:
        game.update()
        all_rows = build_table(game)
        weekly(game, all_rows)
        return
    if "--pool" in sys.argv:
        pool_report(game)
        return
    led = load_ledger(game)
    for rid, name, reason in update_status(game, all_rows, led):
        print(f"  퇴출: {rid} {name[:40]} — {reason}")
    save_ledger(game, led)
    rows = active_rows(game, all_rows, led)
    if len(rows) < len(all_rows):
        print(f"  (퇴출된 전략 {len(led['status'])}개는 순위표에서 숨김. 목록은 ledger_{game.key}.json)")
    show_ciphers(game)
    key_sort = "1"
    best = show_table(game, rows, key_sort)
    while True:
        print("\n  [1] 번호 뽑기   [2] 순위표 기준   [3] 최신 당첨번호 받기   [4] 저장한 번호 결과   [5] 암호키 신뢰도   [6] 신호 분석   [7] 주간 분석(금요일)   [8] 25수 풀 분석   [0] 끝내기")
        m = ask("메뉴", 1)
        if m == "0":
            break
        if m == "1":
            pick_numbers(game, rows, best)
        elif m == "2":
            key_sort = ask("기준  1=5등 이상 적중률  2=4등 이상  3=장당 당첨금  4=전체 300회 합산", key_sort)
            best = show_table(game, rows, key_sort if key_sort in "1234" else "1")
        elif m == "3":
            game.update()
            all_rows = build_table(game)
            rows = active_rows(game, all_rows, load_ledger(game))
            best = show_table(game, rows, key_sort)
        elif m == "7":
            weekly(game, all_rows)
        elif m == "8":
            pool_report(game)
        elif m == "4":
            check_picks(game)
        elif m == "5":
            show_ciphers(game)
        elif m == "6":
            show_signals(game)
        else:
            print("  메뉴 번호를 입력해 주세요.")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\n  종료합니다.")
