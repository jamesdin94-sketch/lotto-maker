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
import unicodedata
import urllib.request
import zlib
from collections import Counter
from itertools import combinations
from math import comb

VERSION = "1.2"   # 구조가 바뀌면 앞자리(2.0), 전략·수치만 바뀌면 소수점(1.1). CHANGELOG.md 참고
HERE = os.path.dirname(os.path.abspath(__file__))
W = 10            # '최근' = 직전 10회
SAMPLE = 2000     # 필터 격자 시뮬레이션: 회차마다 무작위 후보 수
CORE_SAMPLE = 150 # 코어 전략 시뮬레이션: 회차마다 만드는 후보 수
ROUNDS, SPLIT = 300, 200   # 시뮬레이션 회차 수 / 앞 200 = 선택 구간, 뒤 100 = 검증 구간
ENIGMA_WIN = 100  # 암호키 신뢰도를 계산하는 직전 회차 수
RECENT = 20       # 순위표에 보여 주는 최근 회차 수 (기존 코드처럼 회차마다 RECENT_TICKETS 장을 뽑아 실제 당첨 횟수·당첨금을 센다)
RECENT_TICKETS = 50
RECENT_POOL = 6000   # 필터 전략이 회차마다 50장을 고를 무작위 후보 수(조건을 통과하는 앞쪽 50장을 사용)

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


def dw(t):
    """화면에서 차지하는 칸 수(한글·전각 문자는 2칸)."""
    return sum(2 if unicodedata.east_asian_width(c) in "WFA" else 1 for c in t)


def padr(t, w):
    return t + " " * max(0, w - dw(t))


def padl(t, w):
    return " " * max(0, w - dw(t)) + t


def cut(t, w):
    """화면 칸 수 w 안에 들어가게 자른다."""
    if dw(t) <= w:
        return t
    out, n = "", 0
    for c in t:
        if n + dw(c) > w - 1:
            break
        out, n = out + c, n + dw(c)
    return out + "~"


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
LAB = ("쌍", "삼중", "핫", "콜드", "분산", "겹침")


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
        if mode in HYB_OPTS:
            if not passes(feat(c, ctx), HYB_OPTS[mode]):
                continue
        elif mode != "none":
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


CORE_STRATEGIES = [("E1", "암호키 상위5 코어 + 삼중≥1·분산·합·겹침≤2", "enigma", "top", (3, 4, 5)), ("E2", "암호키 상위5 코어 (조건 없음)", "none", "top", (3, 4, 5))]
CIPHER_KO = {"ROT+1": "이동+1", "ROT+2": "이동+2", "MIRROR": "거울", "SUM": "합계", "DIFF": "차이", "BONUS": "보너스", "SWAP": "교환", "GAP": "간격", "XOR": "배타합"}
CORE_STRATEGIES += [(f"E{i + 3}", f"암호키 {CIPHER_KO[name]} 코어 + 조건", "enigma", name, (3, 4, 5)) for i, name in enumerate(make_ciphers(45))]
CORE_STRATEGIES += [("A1", "인공지능 코어12 + 쌍=0·분산 9~13·합·겹침≤1", "ai", "", (3, 4)), ("A2", "인공지능 코어12 (조건 없음)", "none", "", (3, 4)),
                    ("P1", "25수 풀: 직전·자주 나온 번호 빼고 풀 안에서만", "none", "pool1", (6,)), ("P2", "25수 풀: 안 나온 번호 빼고 풀 안에서만", "none", "pool2", (6,)),
                    ("P3", "25수 풀: 무작위 풀 안에서만 (비교용)", "none", "pool3", (6,))]


# H 가족: 암호키(애니그마) 코어에서 만든 조합 중, 일반 필터 조건(쌍·핫·콜드·분산·겹침)도 통과하는 것만 쓰는 하이브리드
HYB_OPTS = {"hybA": [(1, 2), None, None, None, (9, 13), (0, 1)], "hybB": [(1, 2), None, (0, 1), (0, 2), None, (0, 1)]}
HYB_TXT = {"hybA": "쌍1~2 분9~13 겹0~1", "hybB": "쌍1~2 핫0~1 콜0~2 겹0~1"}
_ci = [("top", "상위5")] + [(nm, CIPHER_KO[nm]) for nm in make_ciphers(45)]
for _k, (_spec, _ko) in enumerate(_ci):
    for _j, _m in enumerate(("hybA", "hybB")):
        CORE_STRATEGIES.append((f"H{_k * 2 + _j + 1}", f"하이브리드: 암호키 {_ko} 코어 + 일반 필터({HYB_TXT[_m]})", _m, _spec, (3, 4, 5)))


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
    core_sz = {s[0]: [] for s in CORE_STRATEGIES}   # 회차별 코어(풀) 번호 개수: 코어가 너무 작으면 장끼리 비슷해져 추천에서 뺀다
    rng2 = random.Random(seed + 1)
    recent_pool = []      # 최근 RECENT 회차: (후보 [(특징, 등수)], 그 회차 등수별 1인당 당첨금)
    core_recent = {s[0]: {"n": 0, "c": [0] * 6, "money": 0} for s in CORE_STRATEGIES}
    for k, i in enumerate(range(len(d) - ROUNDS, len(d))):
        part = 0 if k < SPLIT else 1
        ctx = context(d, i)
        _, win, bonus, amt = d[i]
        tbl = agg[part]
        for dim, v in enumerate(feat(win, ctx)):
            win_marg[dim][v] += 1
        if k >= ROUNDS - RECENT:
            pl = []
            for _ in range(RECENT_POOL):
                c = tuple(sorted(rng2.sample(range(1, N + 1), 6)))
                pl.append((feat(c, ctx), rank_of(c, win, bonus)))
            recent_pool.append((pl, amt))
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
            core = core_of(game, sid, i, memo)
            core_sz[sid].append(len(core))
            for ti, c in enumerate(core_tickets(game, core, ctx, band, CORE_SAMPLE, rng, mode, picks=picks)):
                r = rank_of(c, win, bonus)
                if k >= ROUNDS - RECENT and ti < RECENT_TICKETS:
                    cr = core_recent[sid]
                    cr["n"] += 1
                    cr["c"][r] += 1
                    if r and amt:
                        cr["money"] += amt[r - 1]
                x[0] += 1
                x[1] += r > 0
                x[2] += 0 < r <= 4
                x[3] += 0 < r <= 3
                x[4] += amt[r - 1] if (r >= 3 and amt) else 0
            if x[0] > n0:
                core_rr[sid][part].append([x[0] - n0, x[1] - h0])   # 회차별 (장수, 5등+ 장수): 코어 전략은 장끼리 번호를 공유해 결과가 함께 움직이므로 z 를 회차 단위로 계산한다
        if (k + 1) % 50 == 0:
            print(f"    시뮬레이션 {k + 1}/{ROUNDS} 회차 …")
    return agg, core_res, win_marg, core_rr, core_sz, recent_pool, core_recent


def recent_eval(recent_pool, opts):
    """최근 RECENT 회차에서, 회차마다 조건을 통과하는 후보 앞쪽 RECENT_TICKETS 장을 골랐을 때의 장수·등수별 횟수(1~5등)·당첨금."""
    n, c, money = 0, [0] * 6, 0
    for pl, amt in recent_pool:
        got = 0
        for f, rk in pl:
            if passes(f, opts):
                got += 1
                c[rk] += 1
                if rk and amt:
                    money += amt[rk - 1]
                if got == RECENT_TICKETS:
                    break
        n += got
    return {"n": n, "c": c[1:], "money": money}


SCHEMA = 6   # 캐시 형식 번호(필터 전략 ID 를 격자 번호로 고정, 코어 크기 기록)


def build_table(game):
    d = game.draws
    last = d[-1][0]
    if os.path.exists(game.cache):
        try:
            c = json.load(open(game.cache, encoding="utf-8"))
            if c.get("last") == last and c.get("v") == VERSION and c.get("schema") == SCHEMA:
                return c["rows"]
        except Exception:
            pass
    print(f"  {game.name}: 전략을 과거 {ROUNDS}회로 시뮬레이션합니다 (약 1~2분, 이번 회차 동안 저장됩니다).")
    agg, core_res, win_marg, core_rr, core_sz, recent_pool, core_recent = simulate(game)
    rnd_marg = [Counter() for _ in range(6)]
    for tbl in agg:
        for f, e in tbl.items():
            for dim, v in enumerate(f):
                rnd_marg[dim][v] += e[0]
    signals = {"win": [{str(k): c for k, c in m.items()} for m in win_marg], "rnd": [{str(k): c for k, c in m.items()} for m in rnd_marg]}
    fr = [eval_filters(agg[0]), eval_filters(agg[1])]
    rows, seen = [], {}
    gid = {tuple(o): i + 1 for i, (o, _) in enumerate(filter_grid())}   # 전략 ID 는 격자 번호로 고정(회차가 바뀌어도 같은 필터 = 같은 ID)
    for opts, name in sorted(filter_grid(), key=lambda x: sum(o is not None for o in x[0])):
        s, v = fr[0][tuple(opts)], fr[1][tuple(opts)]
        if s[0] < 20000 or v[0] < 10000:   # 통과 후보가 너무 적은 전략은 제외
            continue
        key = (s[1], v[1])                 # 적중 횟수가 같고 통과 장수도 2% 이내로 같으면 사실상 같은 전략(예: AC 7~15 는 거의 모든 후보를 통과) → 가장 단순한 하나만
        if any(abs(n - s[0]) <= 0.02 * s[0] for n in seen.get(key, [])):
            continue
        seen.setdefault(key, []).append(s[0])
        rows.append({"id": "F" + str(gid[tuple(opts)]), "name": name, "kind": "F", "opts": [list(o) if o else None for o in opts],
                     "sel": [s[0], s[1], s[2], 0, s[3]], "ver": [v[0], v[1], v[2], 0, v[3]], "rec": recent_eval(recent_pool, opts)})
    for sid, name, mode, spec, picks in CORE_STRATEGIES:
        if core_res[sid][0][0] >= 5000 and core_res[sid][1][0] >= 2500:   # 조건을 만족하는 후보를 거의 못 만든 코어 전략은 제외
            sz = core_sz[sid]
            rows.append({"id": sid, "name": name, "kind": sid[0], "opts": None, "sel": core_res[sid][0], "ver": core_res[sid][1], "rr": core_rr[sid],
                         "core_n": sum(sz) / len(sz) if sz else 0,
                         "rec": {"n": core_recent[sid]["n"], "c": core_recent[sid]["c"][1:], "money": core_recent[sid]["money"]}})
    json.dump({"last": last, "v": VERSION, "schema": SCHEMA, "rows": rows, "signals": signals}, open(game.cache, "w", encoding="utf-8"), ensure_ascii=False)
    return rows


def zscore(hits, n, p):
    sd = (n * p * (1 - p)) ** 0.5
    return (hits - n * p) / sd if sd else 0.0


def base_row(rows):
    return next(r for r in rows if r["name"].startswith("필터 없음"))


def row_z(row, part, p5, base=None):
    """z: ① 필터 전략은 '같은 후보 표본에서 필터 없이 뽑은 무작위'의 적중률을 기준으로(표본이 우연히 운 좋았던 부분을 함께 상쇄) 후보 장 단위로,
    ② 코어·풀 전략은 무작위 기대 p5 를 기준으로 회차 단위로 계산한다(같은 회차의 장끼리 번호를 공유해 결과가 함께 움직이기 때문)."""
    rr = row.get("rr")
    if rr and len(rr[part]) >= 5:
        rates = [h / n for n, h in rr[part] if n]
        m = sum(rates) / len(rates)
        sd = (sum((x - m) ** 2 for x in rates) / (len(rates) - 1)) ** 0.5
        return (m - p5) / (sd / len(rates) ** 0.5) if sd else 0.0
    k = "sel" if part == 0 else "ver"
    q = p5
    if base is not None and row is not base:
        q = base[k][1] / max(base[k][0], 1)
    return zscore(row[k][1], row[k][0], q)


def pooled_z(row, base, p5):
    """선택·검증 300회를 합친 z (필터 전략은 같은 표본의 무작위 대비, 코어 전략은 무작위 기대 대비 회차 단위)."""
    rr = row.get("rr")
    if rr and len(rr[0]) + len(rr[1]) >= 10:
        rates = [h / n for part in rr for n, h in part if n]
        m = sum(rates) / len(rates)
        sd = (sum((x - m) ** 2 for x in rates) / (len(rates) - 1)) ** 0.5
        return (m - p5) / (sd / len(rates) ** 0.5) if sd else 0.0
    n = row["sel"][0] + row["ver"][0]
    q = (base["sel"][1] + base["ver"][1]) / max(base["sel"][0] + base["ver"][0], 1)
    return zscore(row["sel"][1] + row["ver"][1], n, q)


def score_of(row, base, p5):
    """추천 점수 = (선택+검증 합산 5등+률 − 기준 적중률) − 1 표준오차. 표본이 작거나 회차마다 들쭉날쭉한 전략이 위로 올라오지 않게 한다.
    기준: 필터 전략은 같은 표본의 무작위, 코어·풀 전략은 무작위 기대(p5)."""
    rr = row.get("rr")
    if rr and len(rr[0]) + len(rr[1]) >= 10:
        rates = [h / n for part in rr for n, h in part if n]
        m = sum(rates) / len(rates)
        sd = (sum((x - m) ** 2 for x in rates) / (len(rates) - 1)) ** 0.5
        return m - p5 - sd / len(rates) ** 0.5
    n = row["sel"][0] + row["ver"][0]
    m = (row["sel"][1] + row["ver"][1]) / max(n, 1)
    ref = (base["sel"][1] + base["ver"][1]) / max(base["sel"][0] + base["ver"][0], 1)
    return m - ref - (m * (1 - m) / max(n, 1)) ** 0.5


def eligible(row):
    """추천 대상: 필터 전략, 또는 코어(풀)가 6개 이상이라 장끼리 충분히 달라지는 코어 전략"""
    return row["kind"] == "F" or row.get("core_n", 0) >= 6


def recommended(rows, p5):
    base = base_row(rows)
    pool = [r for r in rows if r is not base and eligible(r) and r["sel"][0] >= 5000 and r["ver"][0] >= 2500]
    return max(pool, key=lambda r: score_of(r, base, p5)) if pool else base


SHORT_TAG = {"쌍": "쌍", "삼중": "삼", "핫": "핫", "콜드": "콜", "분산": "분", "겹침": "겹"}
CORE_SHORT = {**{f"H{_k * 2 + _j + 1}": f"혼합 {_ko} {('쌍분겹', '쌍핫콜겹')[_j]}" for _k, (_spec, _ko) in enumerate(_ci) for _j in (0, 1)}, "E1": "암호키 상위5 코어", "E2": "암호키 상위5 (조건 없음)", "A1": "인공지능 코어12", "A2": "인공지능 코어12 (조건 없음)",
              "P1": "25수 풀 (직전 번호 뺌)", "P2": "25수 풀 (안 나온 번호 뺌)", "P3": "25수 풀 (무작위 풀)"}


def short_name(r):
    """표에 넣는 짧은 이름. 필터 전략은 '쌍1~2 핫3~4' 처럼 줄여 쓴다."""
    if r["kind"] == "F":
        parts = []
        for lab, o in zip(LAB, r["opts"]):
            if o:
                v = f"{o[0]}" if o[0] == o[1] else f"{o[0]}이상" if o[1] == 99 else f"{o[0]}~{o[1]}"
                parts.append(SHORT_TAG[lab] + v)
        return " ".join(parts) if parts else "조건 없음 (무작위)"
    if r["id"] in CORE_SHORT:
        return CORE_SHORT[r["id"]]
    return r["name"].replace(" + 조건", "")


def rec_hits(r):
    return sum(r["rec"]["c"]) if r.get("rec") else 0


def recent_best(rows):
    """최근 RECENT 회차에서 당첨 횟수(5등 이상)가 가장 많은 전략(같으면 당첨금이 큰 것). 코어 번호가 너무 적은 코어 전략은 뺀다."""
    base = base_row(rows)
    pool = [r for r in rows if r is not base and eligible(r) and r.get("rec") and r["sel"][0] >= 5000 and r["ver"][0] >= 2500]
    return max(pool, key=lambda r: (rec_hits(r), r["rec"]["money"])) if pool else base


def show_table(game, rows, key, top=30):
    p5 = p5_of(game.N)
    rate = lambda r, k: r[k][1] / max(r[k][0], 1)
    rows = [r for r in rows if r["sel"][0] >= 5000 and r["ver"][0] >= 2500]
    base = base_row(rows)
    keys = {"1": ("300회 중 순위 구간 5등 이상 적중률", lambda r: rate(r, "sel")), "2": ("순위 구간 4등 이상 적중률", lambda r: r["sel"][2] / max(r["sel"][0], 1)),
            "3": ("순위 구간 장당 당첨금", lambda r: r["sel"][4] / max(r["sel"][0], 1)),
            "4": ("300회 합산 5등 이상 적중률", lambda r: (r["sel"][1] + r["ver"][1]) / max(r["sel"][0] + r["ver"][0], 1)),
            "5": ("추천 점수 (300회 합산 5등+률 - 무작위 - 1 표준오차)", lambda r: score_of(r, base, p5) if r is not base else -1),
            "6": (f"최근 {RECENT}회 당첨 횟수가 많은 순 (같으면 당첨금)", lambda r: (rec_hits(r), r["rec"]["money"]) if r is not base else (-1, 0)),
            "7": (f"최근 {RECENT}회 당첨금이 많은 순", lambda r: r["rec"]["money"] if r is not base else -1)}
    title, fn = keys[key]
    best, seen = [], set()
    for r in sorted(rows, key=fn, reverse=True):   # 최근 20회 결과가 똑같은(같은 후보를 고른) 전략은 필터가 가장 단순한 하나만 보여 준다
        sig = (tuple(r["rec"]["c"]), r["rec"]["money"]) if r.get("rec") and r["kind"] == "F" and r is not base else None
        if sig is not None and sig in seen:
            continue
        if sig is not None:
            seen.add(sig)
        best.append(r)
        if len(best) == top:
            break
    money = game.key == "kr"
    star, diamond = recent_best(rows), recommended(rows, p5)
    print(f"\n  ===== 전략 성적표 | {game.name} | {title} =====")
    print(f"  * '최근 {RECENT}회' = 최근 {RECENT}번의 추첨마다 그 전략으로 {RECENT_TICKETS}장씩({RECENT * RECENT_TICKETS:,}장) 뽑아 실제 당첨번호와 맞춰 본 결과입니다.")
    print(f"  * 맨 왼쪽 '번호'를 기억했다가 아래 메뉴 1(번호 뽑기)에서 그 번호를 입력하면 됩니다.")
    print("  " + padl("번호", 4) + "  " + padr("전략(조건)", 30) + "| " + padl("당첨", 4) + padl("5등", 5) + padl("4등", 5) + padl("3등", 5) + padl("1,2등", 6) + padl("당첨금(원)", 12) + " | " + padr("300회(앞/뒤)", 13) + padl("점수", 6))
    extras = sorted([r for r in rows if r["kind"] in ("E", "H", "A", "P") and r not in best], key=lambda r: ("EHAP".index(r["kind"]), int(r["id"][1:])))   # 암호키·AI·25수 풀 전략은 순위와 상관없이 항상 보여 준다
    shown = [base] + best + extras

    def line(n_, mark, r):
        rc = r["rec"]["c"] if r.get("rec") else [0] * 5
        mon = f"{r['rec']['money']:,}" if money and r.get("rec") else "-"
        sc_ = f"{score_of(r, base, p5) * 100:+.2f}" if r is not base else "-"
        nm = "(비교용) " + short_name(r) if r is base else short_name(r)
        return ("  " + padl(str(n_), 4) + mark + " " + padr(cut(nm, 30), 30) + "| " + padl(str(sum(rc)), 4) + padl(str(rc[4]), 5) + padl(str(rc[3]), 5) + padl(str(rc[2]), 5) + padl(str(rc[0] + rc[1]), 6)
                + padl(mon, 12) + " | " + padr(f"{rate(r, 'sel') * 100:.2f}/{rate(r, 'ver') * 100:.2f}", 13) + padl(sc_, 6))
    for n, r in enumerate(shown):
        if extras and r is extras[0]:
            print("  --- 암호키(애니그마) · 하이브리드(암호키 + 일반 필터) · AI · 25수 풀 전략 (순위와 상관없이 항상 표시. 혼합 = 하이브리드) ---")
        print(line(n, "*" if r is star else "@" if r is diamond else " ", r))
    for mk, r, how in (("*", star, 2), ("@", diamond, 3)):   # 정렬 때문에 목록에 없는 * · @ 전략도 아래에 보여 준다(메뉴 1 -> 2 또는 3 으로 선택)
        if r not in shown:
            print(line("-", mk, r) + f"   (메뉴 1 -> {how} 번으로 선택)")
    exp = RECENT * RECENT_TICKETS * p5
    print(f"  * = 최근 {RECENT}회에 가장 많이 당첨된 전략     @ = 300회 동안 안정적이었던 전략(점수가 가장 높은 전략)")
    print("  이름 읽는 법: 쌍=같이 나온 번호 쌍 수, 삼=세 번호 묶음 수, 핫=자주 나온 번호 수, 콜=안 나온 번호 수, 분=번호가 흩어진 정도, 겹=직전 당첨번호와 겹친 수. '핫3~4'는 3~4개라는 뜻")
    print(f"  (조건 없이 {RECENT * RECENT_TICKETS:,}장을 뽑아도 평균 약 {exp:.0f}번은 당첨(5등 이상)됩니다. {RECENT}회 성적은 우연의 폭이 커서(약 +-{(exp * (1 - p5)) ** 0.5:.0f}번) 앞으로도 이어진다는 보장은 없습니다)")
    return shown


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
    print(f"\n  [암호키 신뢰도] 직전 회차 번호를 암호키로 바꿔 만든 예측이 다음 회차 당첨번호와 2개 이상 겹친 비율 ({game.name}, 전체 {len(game.draws)}회)")
    print(f"  {'암호키':<6}{'적중률':>8}{'우연 기대':>12}{'차이':>8}")
    for name, (h, t, e) in sorted(cipher_table(game).items(), key=lambda x: -(x[1][0] / max(x[1][1], 1))):
        if t:
            sd = (e * (1 - e / t)) ** 0.5
            print(f"  {CIPHER_KO.get(name, name):<6}{h / t:>8.1%}{e / t:>12.1%}{(h - e) / sd if sd else 0:>8.1f}")


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
        print(f"  {i:2d}.  " + "  ".join(f"{n:2d}" for n in t) + f"     {cc}쌍 {f[0]} · 삼중 {f[1]} · 핫 {f[2]} · 콜드 {f[3]} · 분산 {f[4]} · 겹침 {f[5]} · 합 {sum(t)}")
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
    print("\n  " + padr("전략", 44) + padl("장수", 5) + padl("평균맞힘", 9) + padl("5등이상", 8) + padl("기대", 6) + padl("최고", 5) + padl("당첨금(원)", 12))
    for name, e in by.items():
        print("  " + padr(cut(name, 42), 44) + f"{e['n']:>5}{e['hits'] / e['n']:>9.2f}{e['p5']:>8}{e['n'] * p5:>6.1f}{e['best']:>5}{e['money']:>12,}")
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
NEW_IN_VERSION = {"P1": "25수 풀 전략", "P2": "25수 풀 전략", "P3": "25수 풀 비교용", "H1": "하이브리드(암호키 코어 + 일반 필터) H1~H20"}   # 이번 버전에서 보완·추가한 전략


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
            e = led["oos"].setdefault(r["strategy_name"], {"id": r["strategy_id"], "name": r["strategy_name"], "n": 0, "h5": 0, "hits": 0, "money": 0, "weeks": {}})   # 이름으로 묶는다(ID 는 바뀔 수 있음)
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
    """부진한 전략 정리 규칙. ① 300회 합산 z ≤ -2.5 이고 검증 구간도 무작위보다 낮으면 '퇴출'  ② 진짜 미래 누적(저장한 번호)이 장 2,000개 이상이고 z ≤ -2 이면 '퇴출'.
    퇴출된 전략은 순위표와 추천에서 숨긴다(기록은 남김). 규칙이 까다로운 이유: 무작위 결과로 전략을 쉽게 버리면 그것도 우연에 속는 것이기 때문."""
    p5 = p5_of(game.N)
    base = base_row(rows)
    brate = (base["sel"][1] + base["ver"][1]) / (base["sel"][0] + base["ver"][0])
    changes = []
    for r in rows:
        if r is base:
            continue
        zp = pooled_z(r, base, p5)
        zv = row_z(r, 1, p5, base)
        rate = (r["sel"][1] + r["ver"][1]) / max(r["sel"][0] + r["ver"][0], 1)
        reason = None
        if zp <= -2.5 and zv < 0 and rate < brate:   # 300회 합산 z ≤ -2.5 이고 검증 구간도 무작위보다 낮은 전략
            reason = f"300회 합산 z {zp:.1f}, 검증 z {zv:.1f}, 합산 5등+률 {rate:.2%} < 무작위 {brate:.2%}"
        o = led["oos"].get(r["name"])
        if o and o["n"] >= 2000 and zscore(o["h5"], o["n"], p5) <= -2:
            reason = f"미래 누적 {o['n']}장 z {zscore(o['h5'], o['n'], p5):.1f}"
        if reason and r["name"] not in led["status"]:   # 퇴출 기록은 전략 이름(필터 조건)으로 남긴다: ID 가 바뀌어도 같은 전략으로 인식
            led["status"][r["name"]] = {"state": "퇴출", "since": game.draws[-1][0], "id": r["id"], "reason": reason}
            changes.append((r["id"], r["name"], reason))
    return changes


def summarize_changes(changes, brief=False):
    """새로 퇴출된 전략이 많을 때 한 줄 요약 + 가장 나쁜 5개만 보여 준다."""
    if not changes:
        return
    if brief:
        print(f"  (성적이 계속 나빴던 전략 {len(changes)}개는 이번에 표에서 뺐습니다)")
        return
    tokens = Counter(t for _, name, _ in changes for t in name.split(" + "))
    print(f"  퇴출: 새로 {len(changes)}개. 가장 많이 겹친 필터: " + ", ".join(f"{t}({c}개)" for t, c in tokens.most_common(4)))
    for rid, name, reason in sorted(changes, key=lambda x: float(x[2].split("z ")[1].split(",")[0].split(" ")[0]))[:5]:
        print(f"    {rid} {name[:44]} — {reason}")
    print("    (나머지와 사유는 ledger 파일에 기록됩니다)")


def active_rows(game, rows, led):
    return [r for r in rows if led["status"].get(r["name"], {}).get("state") != "퇴출" and r["sel"][0] >= 5000 and r["ver"][0] >= 2500]


def replay_week(game, rows, weeks=4, n=40):
    """지난 weeks 개 회차를 '그 회차 이전 자료만으로' 다시 뽑아 전략별로 채점한다. 순위표를 만들 때 쓴 회차가 섞여 있으니 참고용(진짜 미래 성적은 저장한 번호로 쌓는다)."""
    d = game.draws
    targets = [len(d) - 1 - w for w in range(weeks)]
    base = next(r for r in rows if r["name"].startswith("필터 없음"))
    best = sorted([r for r in rows if r is not base and eligible(r)], key=lambda r: score_of(r, base, p5_of(game.N)), reverse=True)[:8]
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
        for _name, e in oos.items():
            rid = e.get("id", "")
            print(f"  {rid:>4} {e['name'][:42]:<44}{e['n']:>6}{e['hits'] / e['n']:>9.2f}{e['h5']:>6}{e['n'] * p5:>6.1f}{e['money']:>10,}")
    else:
        print("  아직 없습니다. 이번 주 추천 번호를 저장해 두었으니 추첨 뒤 다음 주 분석부터 쌓입니다.")
    print("\n  [3] 부진한 전략 정리와 보완")
    if changes:
        summarize_changes(changes)
    else:
        print("   이번 주 새로 퇴출된 전략: 없음 (기준: 300회 합산 z ≤ -2.5 이고 검증 구간도 무작위보다 낮음 / 미래 누적 2,000장 이상에서 z ≤ -2)")
    gone = [f"{v.get('id', '')}({k[:20]})" for k, v in led["status"].items()]
    print(f"   현재 퇴출 목록: {', '.join(gone) if gone else '없음'}")
    for rid, what in NEW_IN_VERSION.items():
        print(f"   이번 버전 보완: {rid} {what}")
    # 이번 주 추천: 합산 5등+률 상위 3개 + 대표 전략, 번호를 저장해 미래 성적으로 쌓는다
    p5_ = p5_of(game.N)
    rank = sorted([r for r in act if r is not base and eligible(r)], key=lambda r: score_of(r, base, p5_), reverse=True)
    star = recent_best(act)
    picks = [star] + [r for r in rank if r is not star][:2]   # ★ 최근 20회 당첨 1위 + 300회 합산 추천 점수 상위 2개
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


# ---------------------------------------------------------------- 스마트 정리: 이상해 보이는 조합 거르기
def run_max(c):
    best = cur = 1
    for a, b in zip(c, c[1:]):
        cur = cur + 1 if b == a + 1 else 1
        best = max(best, cur)
    return best


def smart_rules(draws, N):
    """과거 당첨번호에서 흔한 모양만 남기는 규칙. 합 구간은 최근 300회의 5~95% 구간."""
    s_ = sorted(sum(x[1]) for x in draws[-300:])
    band = (s_[int(len(s_) * 0.05)], s_[int(len(s_) * 0.95)])
    return [("연속 번호는 2개까지 (3,4,5 같은 3연속 금지)", lambda c: run_max(c) <= 2),
            (f"합계 {band[0]}~{band[1]} (너무 작거나 큰 합 제외)", lambda c: band[0] <= sum(c) <= band[1]),
            ("홀수 1~5개 (전부 홀수/짝수 제외)", lambda c: 1 <= sum(x % 2 for x in c) <= 5),
            (f"낮은 번호(1~{N // 2}) 1~5개 (한쪽 쏠림 제외)", lambda c: 1 <= sum(x <= N // 2 for x in c) <= 5),
            ("같은 끝자리 3개까지", lambda c: max(Counter(x % 10 for x in c).values()) <= 3),
            ("같은 10단위 구간 3개까지", lambda c: max(Counter(x // 10 for x in c).values()) <= 3)]


def smart_ok(c, rules):
    return all(f(c) for _, f in rules)


def show_smart_rules(game):
    rules = smart_rules(game.draws, game.N)
    rng = random.Random(11)
    rnd = [tuple(sorted(rng.sample(range(1, game.N + 1), 6))) for _ in range(20000)]
    hist = [x[1] for x in game.draws]
    print(f"\n  ------ 스마트 정리 규칙 (이상해 보이는 조합을 미리 걸러 냅니다) ------")
    print("  " + padr("규칙", 52) + padl("과거 당첨번호 통과", 20) + padl("무작위 조합 통과", 18))
    for nm, f in rules:
        print("  " + padr(nm, 52) + padl(f"{sum(f(c) for c in hist) / len(hist) * 100:.0f}%", 20) + padl(f"{sum(f(c) for c in rnd) / len(rnd) * 100:.0f}%", 18))
    allp = lambda cs: sum(smart_ok(c, rules) for c in cs) / len(cs) * 100
    print("  " + padr("전부 통과", 52) + padl(f"{allp(hist):.0f}%", 20) + padl(f"{allp(rnd):.0f}%", 18))
    print("  * 과거 당첨번호와 무작위 조합이 거의 같은 비율로 통과합니다. 즉 이 규칙은 당첨번호를 따로 알아보지 못하고, 3연속 같은 '이상해 보이는' 모양만 정리해 줍니다. 당첨 확률은 그대로입니다.")


# ---------------------------------------------------------------- 후보 1,000개 → 2차 선별 (옵션)
POOL_N = 1000
SS_METHODS = {
    1: "서로 덜 겹치게 (번호를 넓게 흩어서)",
    2: "최근 100회에 많이 나온 번호 점수가 높은 순",
    3: "함께 나온 쌍 점수가 높은 순",
    4: "과거 당첨번호의 모양(합·홀짝·높낮이)과 비슷한 순",
    5: "금지삼중이 적은 순 (한 번도 같이 안 나온 세 번호 묶음이 적은 순)",
    6: "이미 나온 사중이 많은 순 (금지사중이 적은 순)",
    7: "금지삼중·금지사중·금지오중 기준을 내가 정해서 거르기",
    8: "후보에서 그냥 무작위로",
}


def candidate_pool(game, row, n, rng, i=None, fixed=(), banned=(), smart=False):
    """전략 조건을 만족하는 후보 n개(서로 겹침 제한 없음). i = 몇 번째 회차를 앞두고 뽑는가(기본: 다음 회차)."""
    d, N = game.draws, game.N
    i = len(d) if i is None else i
    ctx = context(d, i)
    past = {c for _, c, _, _ in d[:i]}
    rules = smart_rules(d[:i], N) if smart else None
    if row["kind"] == "F":
        opts = [tuple(o) if o else None for o in row["opts"]]
        pool_nums = [x for x in range(1, N + 1) if x not in banned and x not in fixed]
        out, seen, tries = [], set(), 0
        while len(out) < n and tries < 600000:
            tries += 1
            c = tuple(sorted(list(fixed) + rng.sample(pool_nums, 6 - len(fixed))))
            if c not in past and c not in seen and passes(feat(c, ctx), opts) and (rules is None or smart_ok(c, rules)):
                seen.add(c)
                out.append(c)
        return out
    mode = next(x[2] for x in CORE_STRATEGIES if x[0] == row["id"])
    out = core_tickets(game, core_of(game, row["id"], i), ctx, sum_band(game, i), n * (3 if smart else 1), rng, mode, picks=picks_of(row["id"]), fixed=fixed, banned=banned, past=past, max_overlap=6)
    out = list(dict.fromkeys(out))
    if rules is not None:
        out = [c for c in out if smart_ok(c, rules)]
    return out[:n]


def seen_sets(draws):
    """지금까지의 당첨 이력에서 한 번이라도 같이 나온 세·네·다섯 번호 묶음."""
    T, Q, F = set(), set(), set()
    for _, nums, _, _ in draws:
        T.update(combinations(nums, 3))
        Q.update(combinations(nums, 4))
        F.update(combinations(nums, 5))
    return T, Q, F


def forbidden_counts(c, T, Q, F):
    """(금지삼중 수 0~20, 금지사중 수 0~15, 금지오중 수 0~6): 조합 안의 묶음 중 과거에 한 번도 같이 나온 적 없는 것의 수"""
    return (sum(t not in T for t in combinations(c, 3)), sum(q not in Q for q in combinations(c, 4)), sum(f not in F for f in combinations(c, 5)))


def shape_of(c):
    g_ = [c[k + 1] - c[k] for k in range(5)]
    return (sum(c), sum(x % 2 for x in c), sum(x <= 22 for x in c), ac_of(c), max(g_))


def ss_context(draws):
    """2차 선별에 쓰는 통계(그 시점까지의 이력만): 최근 100회 번호 빈도, 쌍 빈도, 모양 평균·표준편차, 금지 조합 집합"""
    rec, pairs = Counter(), Counter()
    for k, (_, nums, _, _) in enumerate(draws):
        pairs.update(combinations(nums, 2))
        if k >= len(draws) - 100:
            rec.update(nums)
    shp = [shape_of(x[1]) for x in draws]
    mu = [sum(v[j] for v in shp) / len(shp) for j in range(5)]
    sd = [(sum((v[j] - mu[j]) ** 2 for v in shp) / len(shp)) ** 0.5 or 1 for j in range(5)]
    T, Q, F = seen_sets(draws)
    return {"rec": rec, "pairs": pairs, "mu": mu, "sd": sd, "T": T, "Q": Q, "F": F}


def diverse_pick(pool, k):
    """서로 덜 겹치게: 이미 고른 장과의 최대 겹침이 가장 작은 후보를 차례로 고른다(앞쪽 400개 후보에서)."""
    chosen = [pool[0]]
    cand = pool[1:400]
    ov = [len(set(c) & set(pool[0])) for c in cand]
    while len(chosen) < k and cand:
        j = min(range(len(cand)), key=lambda x: ov[x])
        chosen.append(cand[j])
        sset = set(cand[j])
        cand.pop(j)
        ov.pop(j)
        ov = [max(o, len(set(c) & sset)) for o, c in zip(ov, cand)]
    return chosen


def ss_select(pool, method, n, rng, st, limits=(None, None, None)):
    """후보 pool 에서 method 번 방법으로 n장을 고른다. limits=(금지삼중 최대, 금지사중 최대, 금지오중 최대), None 이면 제한 없음."""
    if not pool:
        return []
    pool = list(pool)
    rng.shuffle(pool)   # 점수가 같을 때 앞쪽이 유리해지지 않게
    if method == 1:
        return diverse_pick(pool, n)
    if method == 8:
        return pool[:n]
    if method == 7:
        keep = []
        for c in pool:
            ft, fq, ff = forbidden_counts(c, st["T"], st["Q"], st["F"])
            if all(lim is None or v <= lim for v, lim in zip((ft, fq, ff), limits)):
                keep.append(c)
        return keep[:n]
    if method == 2:
        key = lambda c: -sum(st["rec"][x] for x in c)
    elif method == 3:
        key = lambda c: -sum(st["pairs"][p_] for p_ in combinations(c, 2))
    elif method == 4:
        key = lambda c: sum(((a - m_) / s_) ** 2 for a, m_, s_ in zip(shape_of(c), st["mu"], st["sd"]))
    elif method == 5:
        key = lambda c: sum(t not in st["T"] for t in combinations(c, 3))
    else:
        key = lambda c: sum(q not in st["Q"] for q in combinations(c, 4))
    return sorted(pool, key=key)[:n]


SS_PRESETS = {"7a": ("금지삼중 2개 이하", (2, None, None)), "7b": ("금지삼중 2개 이하 + 금지사중 14개 이하", (2, 14, None)), "7c": ("금지오중 5개 이하 (나온 오중이 1개 이상)", (None, None, 5))}


SS_ORDER = ["1", "2", "3", "4", "5", "6", "7a", "7b", "7c", "8"]


def ss_tally(tk, win, bonus, amt, t):
    """고른 장 tk 를 당첨번호와 맞춰 t = [장수, 5등, 4등 이상, 당첨금] 에 더한다."""
    t[0] += len(tk)
    for c in tk:
        rk = rank_of(c, win, bonus)
        if rk:
            if rk <= 4:
                t[2] += 1
            else:
                t[1] += 1
            if amt:
                t[3] += amt[rk - 1]


def ss_recent(game, row, n, rounds=20, seed=4242, pool_n=None, smart=False):
    """최근 rounds 회 각각에서 '그 회차 이전 자료만으로' 후보 1,000개를 뽑고 방법별로 n장을 골랐을 때의 집계 {방법: [장수, 5등, 4등 이상, 당첨금]}"""
    d = game.draws
    rng = random.Random(seed)
    got = {k: [0, 0, 0, 0] for k in SS_ORDER}
    for i in range(len(d) - rounds, len(d)):
        pool = candidate_pool(game, row, pool_n or POOL_N, rng, i=i, smart=smart)
        if len(pool) < n:
            continue
        win, bonus, amt = d[i][1], d[i][2], d[i][3] if len(d[i]) > 3 else None
        st = ss_context(d[:i])
        for k in SS_ORDER:
            m, lim = (7, SS_PRESETS[k][1]) if k in SS_PRESETS else (int(k), (None, None, None))
            ss_tally(ss_select(pool, m, n, rng, st, lim), win, bonus, amt, got[k])
    return got


FB_GRID = [(a, b, c) for a in (None, 0, 1, 2, 3) for b in (None, 13, 14) for c in (None, 5)]


def fb_label(g):
    """기준 한 줄 설명: 삼중 · 사중 · 오중 (숫자 이하, 없으면 -)"""
    return "  ".join(f"{nm}{'-' if v is None else str(v) + '이하'}" for nm, v in zip(("삼중", "사중", "오중"), g))


def ss_forbid_table(game, row, n, rounds=20, seed=5151, pool_n=None, smart=False):
    """금지삼중·사중·오중 기준 30가지를 최근 rounds 회에 적용했을 때의 집계 {기준: [장수, 5등, 4등 이상, 당첨금]}"""
    d = game.draws
    rng = random.Random(seed)
    acc = {g: [0, 0, 0, 0] for g in FB_GRID}
    for i in range(len(d) - rounds, len(d)):
        pool = candidate_pool(game, row, pool_n or POOL_N, rng, i=i, smart=smart)
        if len(pool) < n:
            continue
        win, bonus, amt = d[i][1], d[i][2], d[i][3] if len(d[i]) > 3 else None
        st = ss_context(d[:i])
        info = [(c, forbidden_counts(c, st["T"], st["Q"], st["F"])) for c in pool]
        for g in FB_GRID:
            keep = [c for c, f in info if all(lim is None or v <= lim for v, lim in zip(f, g))]
            rng.shuffle(keep)
            ss_tally(keep[:n], win, bonus, amt, acc[g])
    return acc


def tally_cells(t, money=True):
    return padl(str(t[0]), 6) + padl(str(t[1] + t[2]), 6) + padl(str(t[1]), 6) + padl(str(t[2]), 8) + (padl(f"{t[3]:,}", 13) if money else "")


TALLY_HEAD = padl("뽑은장", 6) + padl("당첨", 6) + padl("5등", 6) + padl("4등이상", 8) + padl("당첨금(원)", 13)


def show_fb_table(acc, n, rounds=20):
    print(f"\n  ------ 금지삼중·사중·오중 기준 조합표 (최근 {rounds}회를 그 회차 이전 자료만으로 되돌린 결과, 회차마다 최대 {n}장) ------")
    print("  삼중·사중·오중 = 조합 속 세·네·다섯 번호 묶음 중 과거에 한 번도 같이 안 나온 묶음의 수. 숫자가 작을수록 엄격한 기준입니다.")
    print("  " + padl("번호", 4) + "  " + padr("금지삼중", 10) + padr("금지사중", 10) + padr("금지오중", 10) + TALLY_HEAD)
    for k, g in enumerate(FB_GRID, 1):
        print("  " + padl(str(k), 4) + "  " + "".join(padr("제한 없음" if v is None else f"{v}개 이하", 10) for v in g) + tally_cells(acc[g]))
    print("  * 뽑은장 = 기준을 통과한 후보가 모자라서 n장을 못 채운 회차가 있으면 그만큼 적게 뽑힌 것입니다. 당첨 = 5등 이상 장수.")


SIZE_POOLS = (30, 100, 300, 1000, 3000)
SIZE_PICKS = (5, 10, 20)
SIZE_METHODS = (("8", "무작위로"), ("5", "금지삼중 적은 순"), ("3", "쌍 점수 높은 순"))


def size_cache_path(game):
    return os.path.join(HERE, f"second_stage_size_{game.key}.json")


def size_experiment(game, rows, rounds=100, seed=909):
    """1차 후보 수(30~3,000개) × 2차 장수(5·10·20장) × 선별 방법별로, 최근 rounds 회의 당첨 집계를 낸다. 전략: ◆ 안정 추천(없으면 비교용)."""
    d = game.draws
    p5 = p5_of(game.N)
    row = recommended(rows, p5)
    rng = random.Random(seed)
    acc = {f"{pn}|{n}|{m}": [0, 0, 0, 0] for pn in SIZE_POOLS for n in SIZE_PICKS for m, _ in SIZE_METHODS}
    for i in range(len(d) - rounds, len(d)):
        win, bonus, amt = d[i][1], d[i][2], d[i][3] if len(d[i]) > 3 else None
        st = ss_context(d[:i])
        big = candidate_pool(game, row, max(SIZE_POOLS), rng, i=i)
        if len(big) < max(SIZE_POOLS) // 2:
            continue
        for pn in SIZE_POOLS:
            pool = big[:pn]
            for n in SIZE_PICKS:
                if len(pool) < n:
                    continue
                for m, _ in SIZE_METHODS:
                    ss_tally(ss_select(pool, int(m), n, rng, st), win, bonus, amt, acc[f"{pn}|{n}|{m}"])
        if (i - (len(d) - rounds) + 1) % 25 == 0:
            print(f"     {i - (len(d) - rounds) + 1}/{rounds} 회차 …")
    out = {"last": d[-1][0], "rounds": rounds, "strategy": row["name"], "acc": acc}
    json.dump(out, open(size_cache_path(game), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


def show_size_table(out):
    acc = out["acc"]
    print(f"\n  ------ 1차 후보 수 x 2차 장수 시뮬레이션 (전략: {short_name_of(out['strategy'])}, 최근 {out['rounds']}회, 회차마다 그 이전 자료만 사용) ------")
    print("  1차 = 전략으로 후보를 몇 개 뽑는가 / 2차 = 그중 몇 장을 고르는가. 칸의 숫자 = 당첨(5등 이상 장수) / 4등이상 / 당첨금(만 원)")
    head = "  " + padl("1차 후보", 8) + padl("2차 장수", 9) + "".join(padl(nm, 24) for _, nm in SIZE_METHODS)
    print(head)
    for pn in SIZE_POOLS:
        for n in SIZE_PICKS:
            line = "  " + padl(f"{pn:,}개", 8) + padl(f"{n}장", 9)
            for m, _ in SIZE_METHODS:
                t = acc.get(f"{pn}|{n}|{m}", [0, 0, 0, 0])
                line += padl(f"{t[1] + t[2]} / {t[2]} / {t[3] // 10000:,}", 24)
            print(line)
    tot = out["rounds"] * 20
    print(f"  * 같은 칸끼리는 장수가 같아서 비교할 수 있습니다. 20장 칸은 {tot:,}장이라 우연의 폭이 약 +-{(tot * 0.024) ** 0.5:.0f}번입니다. 이보다 작은 차이는 의미가 없습니다.")
    print("  * 당첨금은 3등(150만 원대) 한두 번에 크게 달라집니다. 당첨 횟수를 먼저 보고, 당첨금은 참고만 하세요.")


def short_name_of(name):
    return name.replace(" + ", " ")


def ss_cache_path(game):
    return os.path.join(HERE, f"second_stage_{game.key}.json")


def ss_experiment(game, rows, rounds=300, tickets=50, seed=777):
    """시험: 전략으로 후보 1,000개를 뽑고 2차 선별로 tickets 장을 골랐을 때의 5등 이상 적중률이 '같은 후보 풀의 평균'보다 높은가.
    회차마다 그 회차 이전 자료만 쓰고, 회차 단위로 z 를 낸다. 대상 전략: 조건 없음, ◆ 안정 추천, ★ 최근 20회 1위."""
    d = game.draws
    p5 = p5_of(game.N)
    base = base_row(rows)
    strategies = [("조건 없음(무작위)", base), ("◆ 안정 추천", recommended(rows, p5)), ("★ 최근 20회 1위", recent_best(rows))]
    out = {}
    for si, (sname, row) in enumerate(strategies):
        rng = random.Random(seed + si)
        res = {}
        print(f"  [{sname}] {row['name']}")
        start = len(d) - rounds
        for i in range(start, len(d)):
            pool = candidate_pool(game, row, POOL_N, rng, i=i)
            if len(pool) < POOL_N // 2:
                continue
            win, bonus = d[i][1], d[i][2]
            hit = {c: 1 if rank_of(c, win, bonus) else 0 for c in pool}
            prate = sum(hit.values()) / len(pool)
            st = ss_context(d[:i])
            todo = [(str(m), m, (None, None, None)) for m in (1, 2, 3, 4, 5, 6, 8)] + [(k_, 7, v[1]) for k_, v in SS_PRESETS.items()]
            for key, m, lim in todo:
                pick = ss_select(pool, m, tickets, rng, st, lim)
                if len(pick) >= 5:
                    res.setdefault(key, []).append(sum(hit[c] for c in pick) / len(pick) - prate)
            if (i - start + 1) % 50 == 0:
                print(f"     {i - start + 1}/{rounds} 회차 …")
        tab = {}
        for key, diffs in res.items():
            m_ = sum(diffs) / len(diffs)
            sdv = (sum((x - m_) ** 2 for x in diffs) / max(len(diffs) - 1, 1)) ** 0.5
            tab[key] = [m_, m_ / (sdv / len(diffs) ** 0.5) if sdv else 0.0, len(diffs)]
        out[sname] = {"strategy": row["name"], "rules": tab}
    json.dump({"last": d[-1][0], "rounds": rounds, "tickets": tickets, "strategies": out}, open(ss_cache_path(game), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


def ss_summary(game):
    """저장된 시험 결과에서 방법별 평균 차이(%p)와 평균 z. 결과가 없으면 None."""
    try:
        c = json.load(open(ss_cache_path(game), encoding="utf-8"))
    except Exception:
        return None
    agg = {}
    for v in c["strategies"].values():
        for key, (m_, z, _n) in v["rules"].items():
            agg.setdefault(key, []).append((m_, z))
    return {k: (sum(a for a, _ in v) / len(v), sum(b for _, b in v) / len(v), max(abs(b) for _, b in v)) for k, v in agg.items()}, c["rounds"]


def show_ss_experiment(game, rows, rounds=150):
    print(f"\n  후보 {POOL_N:,}개를 뽑은 뒤 2차로 고르면 후보 평균보다 5등 이상이 더 자주 나오는지 과거 {rounds}회로 시험합니다. (몇 분 걸립니다)")
    res = ss_experiment(game, rows, rounds=rounds)
    show_ss_table(res, rounds)


def show_ss_table(res, rounds):
    names = {**{str(k): v for k, v in SS_METHODS.items()}, **{k: "   " + v[0] for k, v in SS_PRESETS.items()}}
    print(f"\n  ===== 후보 1,000개 → 2차 선별 시험 (과거 {rounds}회, 같은 후보 풀의 평균과 비교) =====")
    print("  " + padr("선별 방법", 66) + "".join(padl(n_, 18) for n_ in res))
    for key in ["1", "2", "3", "4", "5", "6", "7a", "7b", "7c", "8"]:
        line = "  " + padr(cut(names[key], 64), 66)
        for v in res.values():
            m_, z, _ = v["rules"].get(key, [0, 0, 0])
            line += padl(f"{m_ * 100:+.2f}%p (z{z:+.1f})", 18)
        print(line)
    print("  (+ 이면 후보 평균보다 5등 이상이 더 자주 나왔다는 뜻. z 의 절댓값이 2 보다 작으면 우연의 범위입니다. 후보에서 그냥 무작위로 고른 8번 줄도 우연으로 이만큼 흔들립니다)")


# ---------------------------------------------------------------- 화면(CMD)
def ask(msg, default):
    s = input(f"  {msg} [{default}]: ").strip()
    return s or str(default)


def ask_int(msg, default, lo=None, hi=None):
    """숫자 하나를 입력받는다. 그냥 엔터면 [ ] 안의 기본값. 숫자가 아니거나 범위를 벗어나면 다시 묻는다."""
    while True:
        t = input(f"  {msg} [{default}]: ").strip()
        if not t:
            return default
        try:
            v = int(t)
        except ValueError:
            print("  숫자만 입력해 주세요. (예: 3)")
            continue
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            print(f"  {lo}부터 {hi}까지의 숫자를 입력해 주세요.")
            continue
        return v


def ask_opt_int(msg, lo, hi):
    """숫자 하나를 입력받되, 그냥 엔터면 None(제한 없음)."""
    while True:
        t = input(f"  {msg} [제한 없음]: ").strip()
        if not t:
            return None
        try:
            v = int(t)
        except ValueError:
            print("  숫자만 입력해 주세요.")
            continue
        if v < lo or v > hi:
            print(f"  {lo}부터 {hi}까지의 숫자를 입력해 주세요.")
            continue
        return v


def ask_nums(msg, lo, hi):
    """번호 여러 개를 띄어쓰기(또는 쉼표)로 입력받는다. 그냥 엔터면 빈 목록."""
    while True:
        t = input(f"  {msg}: ").replace(",", " ").strip()
        if not t:
            return []
        try:
            v = [int(x) for x in t.split()]
        except ValueError:
            print("  숫자만 입력해 주세요. (예: 7 14 21)")
            continue
        if any(x < lo or x > hi for x in v):
            print(f"  {lo}부터 {hi}까지의 번호만 쓸 수 있습니다.")
            continue
        return sorted(set(v))


RANGE_HINT = {"쌍": "직전 10회에 함께 나온 두 번호 쌍이 몇 개 들어가게 할지", "삼중": "직전 10회에 함께 나온 세 번호 묶음이 몇 개", "핫": "직전 10회에 2번 이상 나온 번호가 몇 개",
              "콜드": "직전 10회에 한 번도 안 나온 번호가 몇 개", "분산": "번호 사이 차이가 얼마나 다양한지(높을수록 고르게 흩어짐)", "겹침": "직전 당첨번호와 겹치는 번호가 몇 개"}


def ask_range(name):
    while True:
        t = input(f"  [{name}] {RANGE_HINT[name]}\n     '최소 최대' 두 숫자 (예: 0 1) 상관없으면 그냥 엔터: ").replace(",", " ").strip()
        if not t:
            return None
        try:
            v = [int(x) for x in t.split()]
        except ValueError:
            print("  숫자만 입력해 주세요.")
            continue
        if len(v) == 1:
            v = [v[0], v[0]]
        if len(v) != 2 or v[0] > v[1]:
            print("  작은 숫자, 큰 숫자 순서로 두 개를 입력해 주세요. (예: 0 1)")
            continue
        return v


def pick_numbers(game, rows, shown):
    p5 = p5_of(game.N)
    print("\n  ------ 어떤 방법으로 번호를 고를까요? ------")
    print("   1  표에서 마음에 드는 전략의 '번호'를 골라서   (가장 많이 씁니다)")
    print("   2  * 표시(최근 20회에 가장 많이 당첨된) 전략으로 자동으로")
    print("   3  @ 표시(300회 동안 안정적이었던) 전략으로 자동으로")
    print("   4  조건(쌍, 핫, 콜드 등)을 내가 직접 정해서")
    print("   5  다른 곳에서 받은 25개 번호 안에서만 고르기")
    print("   0  돌아가기")
    ch = ask_int("선택", 1, 0, 5)
    if ch == 0:
        return
    nxt = game.draws[-1][0] + 1
    if ch == 5:
        nums = ask_nums(f"받은 번호를 띄어서 입력 (6개 이상, 보통 {pool_size(game)}개)", 1, game.N)
        if len(nums) < 6:
            print("  번호가 6개 이상 필요합니다.")
            return
        k = ask_int("함께 쓸 전략의 표 번호 (쓰지 않으면 0)", 0, 0, len(shown) - 1)
        opts = None
        if k and shown[k]["kind"] == "F":
            opts = [tuple(o) if o else None for o in shown[k]["opts"]]
        n = ask_int("몇 장을 뽑을까요? (1장 = 1,000원)", 5, 1, 50)
        tickets, ctx = pool_input_tickets(game, set(nums), opts, n, random.Random())
        print(f"\n  입력한 번호 {len(nums)}개 · 만들 수 있는 조합 {comb(len(nums), 6):,}개 (전체 {comb(game.N, 6):,}개의 {comb(len(nums), 6) / comb(game.N, 6):.2%}) · {nxt}회용")
        show_tickets(tickets, ctx)
        print(f"  ※ 번호를 줄여서 골라도 한 장이 1등이 될 확률은 1/{comb(game.N, 6):,} 로 같습니다. 이번 당첨번호 6개가 모두 이 안에 있을 확률만 {comb(len(nums), 6) / comb(game.N, 6):.2%} 입니다.")
        if tickets and ask_int("이 번호를 저장할까요?   1=저장   2=저장 안 함", 1, 1, 2) == 1:
            save_picks(game, nxt, "POOL", f"받은 번호 {len(nums)}개 안에서" + (f" + {shown[k]['name']}" if opts else ""), tickets)
            print("  저장했습니다.")
        return
    if ch == 4:
        print("\n  조건을 직접 정합니다. 모르면 모두 그냥 엔터를 누르세요(조건 없이 무작위).")
        opts = [ask_range(n_) for n_ in LAB]
        row = {"id": "C", "kind": "F", "opts": opts, "name": "직접 정함: " + (" + ".join(x for x in [tag(n_, tuple(o) if o else None) for n_, o in zip(LAB, opts)] if x) or "조건 없음")}
    elif ch == 2:
        row = recent_best(rows)
    elif ch == 3:
        row = recommended(rows, p5)
    else:
        k = ask_int(f"표의 번호 (1~{len(shown) - 1}, 0은 비교용 무작위)", 1, 0, len(shown) - 1)
        row = shown[k]
    n = ask_int("몇 장을 뽑을까요? (1장 = 1,000원)", 5, 1, 50)
    fixed = ask_nums(f"꼭 넣고 싶은 번호 (띄어서 입력, 없으면 그냥 엔터)", 1, game.N)
    banned = ask_nums(f"빼고 싶은 번호 (띄어서 입력, 없으면 그냥 엔터)", 1, game.N)
    if len(fixed) > 5:
        print("  꼭 넣을 번호는 5개까지만 가능합니다. 앞의 5개만 사용합니다.")
        fixed = fixed[:5]
    fixed = tuple(x for x in fixed if x not in banned)
    print("\n  ------ 어떻게 뽑을까요? ------")
    print("   1  바로 뽑기 (기본)")
    print(f"   2  이 전략으로 후보 {POOL_N:,}개를 먼저 뽑은 뒤, 그 안에서 다시 골라서")
    way = ask_int("선택", 1, 1, 2)
    rng = random.Random()
    method, limits, tag2 = 0, (None, None, None), ""
    show_smart_rules(game)
    print(f"\n   1  이상한 조합 거르기 (스마트 정리, 기본)")
    print("   2  거르지 않기")
    smart = ask_int("선택", 1, 1, 2) == 1
    if way == 2:
        try:
            sz = json.load(open(size_cache_path(game), encoding="utf-8"))
        except Exception:
            sz = None
        if sz:
            show_size_table(sz)
        print(f"\n  1차: 전략으로 후보를 몇 개 만들까요? (많을수록 오래 걸립니다)")
        for k_, v_ in enumerate(SIZE_POOLS, 1):
            print(f"   {k_}  {v_:,}개" + ("   (기본)" if v_ == POOL_N else ""))
        pool_n = SIZE_POOLS[ask_int("선택", SIZE_POOLS.index(POOL_N) + 1, 1, len(SIZE_POOLS)) - 1]
        if pool_n < n:
            print(f"  후보가 뽑을 장수보다 적어 {POOL_N:,}개로 바꿉니다.")
            pool_n = POOL_N
        print(f"\n  최근 20회를 되돌려서 이 전략 + 각 선별 방법을 써 봤습니다. (회차마다 그때까지의 자료만 사용, 잠시 걸립니다)")
        got = ss_recent(game, row, n, pool_n=pool_n, smart=smart)
        print(f"  ------ 후보에서 어떤 기준으로 고를까요?  (최근 20회를 되돌려 회차마다 {n}장씩 골랐다면) ------")
        names = {**{str(k_): v for k_, v in SS_METHODS.items()}, **{k_: "  예) " + v[0] for k_, v in SS_PRESETS.items()}}
        print("       " + padr("방법", 52) + TALLY_HEAD)
        for k_ in ["1", "2", "3", "4", "5", "6"]:
            print(f"   {k_}   " + padr(cut(names[k_].split(" (")[0], 50), 52) + tally_cells(got[k_]))
        print("   7   " + padr("금지삼중·사중·오중 기준을 내가 정해서 (다음 화면에 표)", 52))
        for k_ in ["7a", "7b", "7c"]:
            print("       " + padr(cut(names[k_], 50), 52) + tally_cells(got[k_]))
        print("   8   " + padr(cut(names["8"].split(" (")[0], 50), 52) + tally_cells(got["8"]))
        print("  * 당첨 = 5등 이상 장수. 20회는 적어서 몇 장 차이는 우연입니다. 300회 시험에서는 어느 방법도 뚜렷하게 좋지 않았습니다(메뉴 5 -> 5).")
        print("  최근 성적을 보고 마지막으로 직접 고르세요.")
        method = ask_int("선택", 1, 1, 8)
        if method == 7:
            print(f"\n  기준 조합표를 만드는 중입니다. (최근 20회, 잠시 걸립니다)")
            acc = ss_forbid_table(game, row, n, pool_n=pool_n, smart=smart)
            show_fb_table(acc, n)
            print(f"\n  위 표에서 쓸 줄의 번호를 입력하세요. 0 을 입력하면 세 가지 기준을 직접 숫자로 정합니다.")
            pickno = ask_int("조합표 번호", 0, 0, len(FB_GRID))
            if pickno:
                limits = FB_GRID[pickno - 1]
            else:
                print("  기준을 숫자로 입력합니다. 상관없으면 그냥 엔터. (금지삼중 0~20, 금지사중 0~15, 금지오중 0~6)")
                limits = (ask_opt_int("금지삼중이 최대 몇 개까지? (예: 2)", 0, 20), ask_opt_int("금지사중이 최대 몇 개까지? (예: 14)", 0, 15), ask_opt_int("금지오중이 최대 몇 개까지? (예: 5)", 0, 6))
            tag_lim = "금지 " + fb_label(limits)
        pool = candidate_pool(game, row, pool_n, rng, fixed=tuple(fixed), banned=tuple(banned), smart=smart)
        if len(pool) < n:
            print(f"  조건에 맞는 후보를 {len(pool)}개밖에 만들지 못했습니다. 조건을 줄이거나 바로 뽑기를 써 보세요.")
            return
        tickets = ss_select(pool, method, n, rng, ss_context(game.draws), limits)
        ctx, core = context(game.draws, len(game.draws)), None
        if len(tickets) < n:
            print(f"  기준에 맞는 후보가 {len(tickets)}개뿐이라 그만큼만 보여 드립니다. 기준을 느슨하게 해 보세요.")
        tag2 = (f" -> 후보{pool_n:,}개에서 '{SS_METHODS[method].split(' (')[0]}'" if method != 7 else f" -> 후보{pool_n:,}개에서 {tag_lim}") + (" + 스마트 정리" if smart else "")
        print(f"\n  후보 {len(pool):,}개 중에서 고른 결과입니다.")
    elif smart:
        pool = candidate_pool(game, row, max(400, n * 20), rng, fixed=tuple(fixed), banned=tuple(banned), smart=True)
        tickets = []
        for c in pool:   # 서로 4개 넘게 겹치지 않는 조합만 차례로
            if all(len(set(c) & set(o)) <= 3 for o in tickets):
                tickets.append(c)
            if len(tickets) == n:
                break
        if len(tickets) < n:
            for c in pool:
                if c not in tickets and all(len(set(c) & set(o)) <= 4 for o in tickets):
                    tickets.append(c)
                if len(tickets) == n:
                    break
        ctx, core = context(game.draws, len(game.draws)), None
        tag2 = " + 스마트 정리"
    else:
        tickets, ctx, core = make_tickets(game, row, n, rng, tuple(fixed), tuple(banned))
    row = dict(row, name=row["name"] + tag2) if tag2 else row
    print(f"\n  선택한 전략: {row['name']}  ({nxt}회용)")
    show_tickets(tickets, ctx, core)
    if tickets:
        print(f"  ※ 어떤 번호든 한 장이 1등이 될 확률은 1/{comb(game.N, 6):,} 로 같습니다.")
        if ask_int("이 번호를 저장할까요?   1=저장   2=저장 안 함", 1, 1, 2) == 1:
            save_picks(game, nxt, row["id"], row["name"], tickets)
            print("  저장했습니다. 추첨이 끝난 뒤 메뉴 3(당첨번호 받기) → 메뉴 4(결과 보기)를 누르세요.")
    else:
        print("  조건에 맞는 번호를 만들지 못했습니다. 꼭 넣을 번호나 조건을 줄여 보세요.")


def main():
    print(f"\n  ===== 로또 조합 메이커 V{VERSION} =====")
    print("  주의: 이 도구는 당첨 확률을 높이지 않습니다. 오락으로, 여유 자금 안에서만. 상담 1336")
    if any(a in sys.argv for a in ("--game", "--update", "--check", "--weekly", "--pool")):
        key = "ny" if "ny" in sys.argv else "kr"
    else:
        print("\n  어느 나라 로또를 볼까요?\n   1  한국 로또 6/45 (동행복권)\n   2  뉴욕 로또 6/59")
        key = {1: "kr", 2: "ny"}[ask_int("선택", 1, 1, 2)]
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
    summarize_changes(update_status(game, all_rows, led), brief=True)
    save_ledger(game, led)
    rows = active_rows(game, all_rows, led)
    print("  ※ 사용법: 숫자를 입력하고 엔터(Enter) 키를 누르세요. 그냥 엔터만 누르면 [ ] 안의 숫자가 선택됩니다.")
    key_sort = "6"
    shown = show_table(game, rows, key_sort)
    while True:
        print("\n  ------ 무엇을 할까요? ------")
        print("   1  번호 뽑기")
        print("   2  성적표 다시 보기 (정렬 기준 바꾸기)")
        print("   3  최신 당첨번호 받기 (추첨한 다음 날 한 번)")
        print("   4  내가 뽑아 둔 번호의 당첨 결과 보기")
        print("   5  더 자세한 분석 (암호키, 신호, 주간 분석, 25수 풀)")
        print("   0  끝내기")
        m = ask_int("메뉴", 1, 0, 5)
        if m == 0:
            break
        if m == 1:
            pick_numbers(game, rows, shown)
        elif m == 2:
            print("\n  어떤 순서로 볼까요?")
            print("   1  최근 20회 당첨 횟수가 많은 순 (기본)")
            print("   2  최근 20회 당첨금이 많은 순")
            print("   3  300회 합산 성적순")
            print("   4  추천 점수순")
            k = ask_int("선택", 1, 1, 4)
            key_sort = {1: "6", 2: "7", 3: "4", 4: "5"}[k]
            shown = show_table(game, rows, key_sort)
        elif m == 3:
            game.update()
            all_rows = build_table(game)
            rows = active_rows(game, all_rows, load_ledger(game))
            shown = show_table(game, rows, key_sort)
        elif m == 4:
            check_picks(game)
        elif m == 5:
            print("\n  1  암호키 신뢰도    2  신호 분석    3  주간 분석 (금요일에 한 번)    4  25수 풀 분석    5  후보 1,000개 -> 2차 선별 시험    6  1차 후보 수 x 2차 장수 시뮬레이션    0  돌아가기")
            k = ask_int("선택", 0, 0, 6)
            if k == 1:
                show_ciphers(game)
            elif k == 2:
                show_signals(game)
            elif k == 3:
                weekly(game, all_rows)
            elif k == 4:
                pool_report(game)
            elif k == 6:
                try:
                    sz = json.load(open(size_cache_path(game), encoding="utf-8"))
                except Exception:
                    sz = None
                if sz is None:
                    print("  처음 한 번 계산합니다. 몇 분 걸립니다.")
                    sz = size_experiment(game, all_rows)
                show_size_table(sz)
                print(f"\n  1  다시 계산하기 (몇 분)    0  돌아가기")
                if ask_int("선택", 0, 0, 1) == 1:
                    show_size_table(size_experiment(game, all_rows))
            elif k == 5:
                saved = None
                try:
                    saved = json.load(open(ss_cache_path(game), encoding="utf-8"))
                except Exception:
                    pass
                if saved:
                    show_ss_table(saved["strategies"], saved["rounds"])
                    print("\n  1  이 결과를 다시 계산하기 (몇 분 걸립니다)    0  돌아가기")
                    if ask_int("선택", 0, 0, 1) == 1:
                        show_ss_experiment(game, all_rows)
                else:
                    show_ss_experiment(game, all_rows)

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\n  종료합니다.")
