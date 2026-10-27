# PGL daily drills

Two GitHub jobs ask Claude (Opus 5.5) for fresh workouts in Point Guard Lab's style:

- **Every morning** (about 3 AM Kelowna time), `generate.py daily` writes the **Workout of the Day** to
  `today.json`: 4 new drills, a new name every day.
- **Every Monday** (about 2 AM), `generate.py weekly` writes `weekly.json`: new drills for each regular
  workout (Handles, Basketball IQ, Score at the Rim, Shot Lab, Lockdown, Engine). **The names and focus stay the
  same**; only the drills inside change. Handles stays ball handling, Lockdown stays defense, and so on.

The iPhone app downloads both when it opens. If the daily file is missing or old, the app uses a built-in
workout for the Workout of the Day. If a Monday update fails, the app keeps last week's drills (or the
built-in ones if it has never had a week).

- **Cost:** about $0.10 a day for the daily workout plus about $0.30 a week for the weekly set, roughly
  $4-5 a month in total, however many players use the app.
- **Basketball IQ is film study only** (Tyler's choice, Oct 26): each week it gets 3 new 10-minute film tasks, like
  "Watch 10 minutes of game film and watch pick-and-roll coverages". No on-court drills.
- **Weekly checks:** every workout present once, the right number of drills, and only drills that fit the
  workout's focus (Shot Lab only gets shooting drills, etc.); Basketball IQ tasks must be 10-minute film study;
  no drill name repeated anywhere in the week.
  If Claude's answer fails twice, last week's file stays up.
- **Daily checks before publishing:** exactly 4 drills; at least 3 of the 6 skills (Ball Handling, Basketball IQ,
  Shooting, Finishing, Defense, Conditioning); 1–6 minutes per drill; no repeats of the built-in drills or the last two
  weeks of daily drills. If Claude's answer fails the checks twice, nothing is published and yesterday's
  file stays up (the app then falls back to its built-in workouts).
- **Reviewing or editing a day:** every day's set is saved in `archive/`, and `today.json` is a normal
  file. You can edit or fix it right on github.com and the app picks up the change within a few minutes.
- **Fresh set on demand:** on github.com, go to Actions → Daily drills (or Weekly workouts) → Run workflow.
- **Changing the style or rules:** edit `SYSTEM` and `build_prompt` in `generate.py`.

## One-time setup (Tyler)
1. Create an Anthropic API account at https://console.anthropic.com, add a payment method, and create an
   API key. (Optional: set a monthly spend limit there for peace of mind.)
2. In the GitHub repo **pgl-daily-drills**: Settings → Secrets and variables → Actions →
   New repository secret. Name: `ANTHROPIC_API_KEY`, value: the key from step 1.
3. Actions tab → **Weekly workouts** → Run workflow, then **Daily drills** → Run workflow, to make the
   first sets. Each should finish in a minute or two.

`samples/` holds made-up test files for checking the app locally. The app never downloads from there.

The repo must be **public**, because the app downloads `today.json` from it without logging in. Only
drills live here; the API key is stored as a GitHub secret and is never visible in the repo or the app.
