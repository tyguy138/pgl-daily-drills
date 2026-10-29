"""Point Guard Lab: generate fresh workouts for The Lab app with Claude.

    python generate.py daily    -> today.json   (Workout of the Day; runs every morning)
    python generate.py weekly   -> weekly.json  (new drills for the regular workouts; runs Mondays)

Runs on GitHub Actions (see .github/workflows/). Each run also saves a copy under archive/.
Needs the ANTHROPIC_API_KEY secret. Nothing here ships inside the iPhone app.
"""

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Literal
from zoneinfo import ZoneInfo

import anthropic
from pydantic import BaseModel, Field, ValidationError, field_validator

ROOT = Path(__file__).parent
TODAY_FILE = ROOT / "today.json"
WEEKLY_FILE = ROOT / "weekly.json"
ARCHIVE = ROOT / "archive"            # daily files: archive/YYYY-MM-DD.json
WEEKLY_ARCHIVE = ARCHIVE / "weekly"   # weekly files: archive/weekly/YYYY-MM-DD.json (the Monday)
MODEL = "claude-opus-5-5"
DRILLS_PER_DAY = 4

# Category codes match DrillCategory.code in the app (PGL/Models/Drill.swift).
Code = Literal["BH", "IQ", "FN", "SH", "DF", "CN"]
SKILL_OF = {"BH": "handling", "IQ": "iq", "SH": "shooting",
            "FN": "finishing", "DF": "defense", "CN": "conditioning"}

# Drills already built into the app, so Claude makes new ones instead of repeating them.
BUILT_IN = [
    "Pound Series", "Two-Ball Control", "Cone Attack Moves", "Hesitation & Hang",
    "Call It Out", "Pick-and-Roll Reads", "Advantage Advance", "Mikan Series",
    "Euro & Pro Hop", "Contact Finishes", "Form Shooting", "Pull-Up Jumpers",
    "Catch & Shoot", "Stance & Slides", "Zig-Zag", "Closeouts", "Line Touches",
    "Lane Agility", "Full-Court Layups",
    "Film: Off-Ball Movement", "Film: Pick-and-Roll Coverages", "Film: Point Guard Decisions",
    # Beginner and Advanced levels (Oct 29)
    "Stationary Basics", "Figure 8", "Walking Crossovers", "Tennis Ball Toss", "Two-Ball Combos",
    "Combo Move Gauntlet", "Film: Follow One Player", "Film: Find the Spacing", "Film: Scout an Opponent",
    "Film: Late-Game Decisions", "Film: Help Defense Rotations", "Basic Layups", "Power Layups",
    "Floater Series", "Reverse & Up-and-Under", "Speed Finishes", "Free Throw Routine", "Close Spot Shots",
    "Off-Screen Shooting", "Step-Backs & Side-Steps", "Beat the Pro", "Mirror Slides", "Closeout Footwork",
    "1-on-1 Contain", "Closeout to Contain", "Deny the Wing", "Defensive Slide Gauntlet", "Jog & Sprint",
    "Jump Rope", "17s", "Sprint & Shoot",
]


class Theme(BaseModel):
    """One of the app's regular workouts. Name and focus stay fixed; the drills change weekly."""
    name: str
    focus: str
    drills: int
    allowed: List[str]      # category codes its drills may use
    must_have: str          # the workout's main category...
    min_main: int           # ...and how many of its drills must be that category
    setting: str
    film: bool = False      # film study at home instead of on-court drills (Basketball IQ)


# Keep these ids and names in sync with DrillLibrary.workouts in the app.
THEMES: Dict[str, Theme] = {
    "daily-handles": Theme(name="Handles", focus="ball handling with eyes up, both hands",
                           drills=3, allowed=["BH"], must_have="BH", min_main=3,
                           setting="solo, 1 ball, works on a driveway"),
    # Basketball IQ is film study only, no on-court drills (Tyler's choice, Oct 26).
    "guard-iq": Theme(name="Basketball IQ", focus="film study: watch game film and read the game like a point guard "
                                             "(off-ball movement, pick-and-roll coverages, decisions, spacing, "
                                             "transition, defensive rotations)",
                      drills=3, allowed=["IQ"], must_have="IQ", min_main=3,
                      setting="anywhere with game film on a phone, tablet or laptop; no court, no ball",
                      film=True),
    "score-the-rim": Theme(name="Score at the Rim", focus="attacking off the dribble and finishing with both hands",
                           drills=4, allowed=["FN", "BH"], must_have="FN", min_main=3,
                           setting="gym with a hoop"),
    "shot-lab": Theme(name="Shot Lab", focus="shooting: form, catch-and-shoot, off the dribble",
                      drills=3, allowed=["SH"], must_have="SH", min_main=3,
                      setting="gym with a hoop, solo or with a rebounder"),
    "lockdown": Theme(name="Lockdown", focus="on-ball defense: stance, staying in front, closeouts",
                      drills=3, allowed=["DF"], must_have="DF", min_main=3,
                      setting="partner for at most two drills"),
    "engine": Theme(name="Engine", focus="conditioning for guards: game-speed work, short rest",
                    drills=4, allowed=["CN", "DF"], must_have="CN", min_main=3,
                    setting="gym; no equipment beyond a ball and cones"),
}


class Drill(BaseModel):
    name: str = Field(min_length=3, max_length=40)
    category: Code
    seconds: int = Field(ge=60, le=600)   # court drills 60-360; film tasks up to 600 (checked below)
    equipment: str = Field(min_length=2, max_length=40)
    summary: str = Field(min_length=10, max_length=140)
    steps: List[str] = Field(min_length=3, max_length=6)
    cues: List[str] = Field(min_length=2, max_length=3)

    @field_validator("seconds")
    @classmethod
    def whole_half_minutes(cls, v: int) -> int:
        return round(v / 30) * 30


class DailyWorkout(BaseModel):
    name: str = Field(min_length=3, max_length=30)
    summary: str = Field(min_length=10, max_length=140)
    drills: List[Drill] = Field(min_length=DRILLS_PER_DAY, max_length=DRILLS_PER_DAY)


class WeeklyWorkout(BaseModel):
    id: str
    summary: str = Field(min_length=10, max_length=140)
    drills: List[Drill] = Field(min_length=2, max_length=4)


class WeeklySet(BaseModel):
    workouts: List[WeeklyWorkout]


# Plain JSON Schemas for structured outputs; the Pydantic models above do the range checks afterwards.
DRILL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "category", "seconds", "equipment", "summary", "steps", "cues"],
    "properties": {
        "name": {"type": "string"},
        "category": {"type": "string", "enum": list(SKILL_OF)},
        "seconds": {"type": "integer"},
        "equipment": {"type": "string"},
        "summary": {"type": "string"},
        "steps": {"type": "array", "items": {"type": "string"}},
        "cues": {"type": "array", "items": {"type": "string"}},
    },
}
DAILY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "summary", "drills"],
    "properties": {
        "name": {"type": "string"},
        "summary": {"type": "string"},
        "drills": {"type": "array", "items": DRILL_SCHEMA},
    },
}
WEEKLY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["workouts"],
    "properties": {
        "workouts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "summary", "drills"],
                "properties": {
                    "id": {"type": "string", "enum": list(THEMES)},
                    "summary": {"type": "string"},
                    "drills": {"type": "array", "items": DRILL_SCHEMA},
                },
            },
        },
    },
}

SYSTEM = """You write workouts for The Lab, the training app of Point Guard Lab, a guard-focused \
basketball training program in Kelowna, BC for high school players (grades 9-12, boys and girls). \
The program's idea: "See, think and play like a point guard, at any position."

A player does a workout alone or with one partner, on a driveway or in a gym, following a timer on \
their phone. Write it the way our coaches talk in the gym: short, plain, direct sentences a 14-year-old \
reads at a glance between reps. Coaching cues are 2-4 words each, said out loud mid-rep \
("Eyes up", "Sell the shot", "Chin the ball").

Category codes: BH ball handling, IQ reads/decision-making with the ball, FN finishing at the rim, \
SH shooting, DF on-ball defense, CN conditioning.

Every drill must be safe for a high school player training without a coach: no jumping off or onto \
objects, no heavy weights, no contact drills without a partner. If a drill needs a partner, say \
"partner" in its equipment. 3-6 steps and 2-3 cues per drill; 60-360 seconds of work time each.

Film study tasks (Basketball IQ only) are not on-court drills. The player watches game film (their own, or a \
college or pro game on YouTube) on a phone, tablet or laptop for 10 minutes (600 seconds) and studies one \
thing, e.g. "Watch 10 minutes of game film and watch off-ball movement" or "Watch 10 minutes of game film \
and watch pick-and-roll coverages". Category IQ, equipment "Game film on a phone or laptop", name starting \
"Film: ". Steps tell them what to watch for, when to pause and say what they see, and to write one or two \
takeaways in their notebook. No ball, no court, no movement.

Example of one drill in our style:
{"name": "Hesitation & Hang", "category": "BH", "seconds": 180, "equipment": "1 ball",
 "summary": "Freeze the defender with your eyes and shoulders, then go.",
 "steps": ["Push the ball up the floor at 75% speed.", "Hang the dribble high and lift your eyes to the rim.",
           "Explode past an imaginary defender with a long first step.",
           "Repeat both directions, then add a crossover out of the hang."],
 "cues": ["Sell the shot", "Then go", "Long first step"]}"""


# MARK: - Shared helpers

def now() -> datetime:
    return datetime.now(ZoneInfo("America/Vancouver"))


def names_in(paths: List[Path]) -> List[str]:
    names = []
    for path in paths:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        workouts = data.get("workouts") or [data]
        workouts += [w for entries in data.get("levels", {}).values() for w in entries]
        names += [d.get("name", "") for w in workouts for d in w.get("drills", [])]
    return [n for n in names if n]


def recent_daily_names(days: int = 14) -> List[str]:
    return names_in(sorted(ARCHIVE.glob("*.json"))[-days:])


def recent_weekly_names(weeks: int = 2) -> List[str]:
    return names_in(sorted(WEEKLY_ARCHIVE.glob("*.json"))[-weeks:])


def call_claude(client: anthropic.Anthropic, prompt: str, schema: dict) -> str:
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined the request")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Response was cut off")
    return next(b.text for b in response.content if b.type == "text")


def check_new(drills: List[Drill]) -> None:
    taken = {n.lower() for n in BUILT_IN}
    repeats = [d.name for d in drills if d.name.lower() in taken]
    if repeats:
        raise ValueError(f"repeats built-in drills: {repeats}")
    names = [d.name.lower() for d in drills]
    if len(names) != len(set(names)):
        raise ValueError("same drill name used twice")


def check_length(drills: List[Drill], film: bool) -> None:
    """Court drills are 1-6 minutes. Film tasks are exactly 10 minutes and must actually be film study."""
    for d in drills:
        if film:
            if d.seconds != 600:
                raise ValueError(f"film task {d.name} is {d.seconds}s, needs 600")
            if "film" not in d.equipment.lower() and "film" not in d.name.lower():
                raise ValueError(f"{d.name} doesn't look like film study")
        elif d.seconds > 360:
            raise ValueError(f"{d.name} is {d.seconds}s, max 360")


def with_retry(make):
    for attempt in (1, 2):
        try:
            return make()
        except (ValidationError, ValueError, RuntimeError, StopIteration) as err:
            print(f"Attempt {attempt} rejected: {err}", file=sys.stderr)
    return None


def save(text: str, current: Path, archived: Path) -> None:
    current.write_text(text)
    archived.parent.mkdir(parents=True, exist_ok=True)
    archived.write_text(text)


# MARK: - Daily (Workout of the Day)

def daily_prompt(day: datetime, avoid: List[str]) -> str:
    return f"""Write today's Workout of the Day.

- Exactly {DRILLS_PER_DAY} drills, in the order the player should do them (warm-up feel first, hardest last).
- Cover at least three of these six areas: ball handling (BH), basketball IQ (IQ), shooting (SH), \
finishing (FN), defense (DF), conditioning (CN).
- The whole workout is 10-18 minutes of work.
- At most one drill needs a partner. Everything else works solo with a ball, cones or nothing.
- Name the workout plainly after its basketball focus, 2-4 words, like "Handles & Help Defense" or \
"Shooting Off the Bounce". No days of the week, no puns, slang or slogans.
- Give it a one-sentence summary of the work. Don't mention the day or the week.
- Make these drills new. Don't reuse or lightly rename any of these: {", ".join(avoid)}."""


# Workout names and summaries must not be day-of-the-week slogans (Tyler, Oct 28: "Hump Day Heat" was not OK).
DAY_WORDS = re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|hump|weekend|midweek|"
                       r"mid-week|middle of the week|tgif)\b", re.IGNORECASE)


def check_title(workout: DailyWorkout) -> None:
    for text in (workout.name, workout.summary):
        if DAY_WORDS.search(text):
            raise ValueError(f"mentions the day: {text!r}")


def ask_daily(client: anthropic.Anthropic, prompt: str) -> DailyWorkout:
    workout = DailyWorkout.model_validate_json(call_claude(client, prompt, DAILY_SCHEMA))
    check_title(workout)
    skills = {SKILL_OF[d.category] for d in workout.drills}
    if len(skills) < 3:
        raise ValueError(f"only covers {sorted(skills)}")
    check_length(workout.drills, film=False)
    check_new(workout.drills)
    return workout


def run_daily(client: anthropic.Anthropic) -> int:
    day = now()
    avoid = BUILT_IN + recent_daily_names() + names_in([WEEKLY_FILE])  # don't repeat this week's drills
    workout = with_retry(lambda: ask_daily(client, daily_prompt(day, avoid)))
    if workout is None:
        print("No valid workout today; leaving yesterday's file in place.", file=sys.stderr)
        return 1

    stamp = day.strftime("%Y-%m-%d")
    payload = {
        "date": stamp,
        "name": workout.name,
        "summary": workout.summary,
        "drills": [{"id": f"daily-{stamp}-{i + 1}", **d.model_dump()} for i, d in enumerate(workout.drills)],
    }
    save(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", TODAY_FILE, ARCHIVE / f"{stamp}.json")
    print(f"Wrote {workout.name}: " + ", ".join(d.name for d in workout.drills))
    return 0


# MARK: - Weekly (the regular workouts, same names, new drills)

# Each regular workout comes in three difficulty levels (added Oct 29 from tester feedback). Intermediate is
# the original workout and stays in weekly.json's "workouts" list, so older app builds keep working; beginner
# and advanced go in "levels". Must match Difficulty in the app (PGL/Models/Drill.swift).
LEVELS = {
    "intermediate": "Intermediate: players with some training behind them. Game speed once the move is clean.",
    "beginner": "Beginner: newer players, often grade 9 or new to training. Basic movements at a controlled speed, "
                "one skill at a time, simple steps. Shorter drills (60-180 seconds). Film tasks study one simple "
                "thing (one player, one action).",
    "advanced": "Advanced: experienced varsity and university guards. Full game speed, combo moves, decisions "
                "under pressure and while tired. Longer drills (180-360 seconds). Film tasks go deeper: scouting, "
                "several reads at once, late-game decisions.",
}
MINUTES = {"beginner": "6-12", "intermediate": "8-16", "advanced": "12-20"}


def drill_count(theme: Theme, level: str) -> int:
    if level == "beginner":
        return 2 if theme.film else 3
    if level == "advanced":
        return 3 if theme.film else 4
    return theme.drills


def weekly_prompt(monday: datetime, avoid: List[str], level: str) -> str:
    lines = "\n".join(
        f'- id "{wid}" ({t.name}): {t.focus}. Exactly {drill_count(t, level)} drills, categories '
        f'{"/".join(t.allowed)} only, at least {min(t.min_main, drill_count(t, level))} of them {t.must_have}. '
        f"Setting: {t.setting}."
        for wid, t in THEMES.items()
    )
    return f"""Write this week's drills for the app's regular workouts (week of {monday:%B %-d}), \
{level} level. Each workout keeps its name and focus; only the drills are new this week.

Level: {LEVELS[level]}

{lines}

- Return every workout above exactly once, using its id.
- For each, a one-sentence summary of this week's version, and its drills in the order to do them \
(easier first, hardest last). Each workout is {MINUTES[level]} minutes of work, except Basketball IQ.
- Basketball IQ is film study only: film tasks of exactly 600 seconds (10 minutes) each, \
each studying something different. No on-court drills.
- Every drill name must be different across the whole week.
- Make the drills new. Don't reuse or lightly rename any of these: {", ".join(avoid)}."""


def ask_weekly(client: anthropic.Anthropic, prompt: str, level: str) -> WeeklySet:
    week = WeeklySet.model_validate_json(call_claude(client, prompt, WEEKLY_SCHEMA))
    ids = [w.id for w in week.workouts]
    if sorted(ids) != sorted(THEMES):
        raise ValueError(f"wrong workouts: {ids}")
    for w in week.workouts:
        theme = THEMES[w.id]
        count = drill_count(theme, level)
        if len(w.drills) != count:
            raise ValueError(f"{theme.name} has {len(w.drills)} drills, needs {count}")
        off = [d.name for d in w.drills if d.category not in theme.allowed]
        if off:
            raise ValueError(f"{theme.name} has off-focus drills: {off}")
        check_length(w.drills, film=theme.film)
        if sum(d.category == theme.must_have for d in w.drills) < min(theme.min_main, count):
            raise ValueError(f"{theme.name} doesn't have enough {theme.must_have} drills")
    check_new([d for w in week.workouts for d in w.drills])
    return week


def weekly_entries(week: WeeklySet, stamp: str, level: str) -> List[dict]:
    order = list(THEMES)
    tag = "" if level == "intermediate" else f"{level}-"
    return [
        {
            "id": w.id,
            "summary": w.summary,
            "drills": [{"id": f"week-{stamp}-{tag}{w.id}-{i + 1}", **d.model_dump()} for i, d in enumerate(w.drills)],
        }
        for w in sorted(week.workouts, key=lambda w: order.index(w.id))
    ]


def run_weekly(client: anthropic.Anthropic) -> int:
    today = now()
    monday = today - timedelta(days=today.weekday())
    stamp = monday.strftime("%Y-%m-%d")
    avoid = BUILT_IN + recent_weekly_names() + recent_daily_names(7)

    sets: Dict[str, List[dict]] = {}
    for level in LEVELS:   # intermediate first: without it there's no new week at all
        week = with_retry(lambda: ask_weekly(client, weekly_prompt(monday, avoid, level), level))
        if week is None:
            if level == "intermediate":
                print("No valid weekly set; leaving last week's file in place.", file=sys.stderr)
                return 1
            print(f"No valid {level} set; the app uses its built-in {level} workouts this week.", file=sys.stderr)
            continue
        sets[level] = weekly_entries(week, stamp, level)
        avoid += [d.name for w in week.workouts for d in w.drills]   # every level gets its own drills

    payload = {
        "week": stamp,
        "workouts": sets["intermediate"],
        "levels": {level: entries for level, entries in sets.items() if level != "intermediate"},
    }
    save(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", WEEKLY_FILE, WEEKLY_ARCHIVE / f"{stamp}.json")
    for level, entries in sets.items():
        for w in entries:
            print(f"{THEMES[w['id']].name} ({level}): " + ", ".join(d["name"] for d in w["drills"]))
    return 0


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if mode not in ("daily", "weekly"):
        print("usage: python generate.py [daily|weekly]", file=sys.stderr)
        return 2
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    return run_daily(client) if mode == "daily" else run_weekly(client)


if __name__ == "__main__":
    sys.exit(main())
