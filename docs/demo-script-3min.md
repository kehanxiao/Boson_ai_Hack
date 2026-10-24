# Viva demo script: 3 slides, at most 3 minutes

Session: **`demo3`**. Open http://localhost:5173/session/demo3 and start the agent with `cd agent && uv run main.py demo3`.

- Deck: `demo/deck-demo3.pdf`, from `server/scripts/make_demo3_deck.py`.
- Examiner: The Supervisor (Dr. Claire Moreau).
- Time limit: 3:00. There is no Q&A and no verdict: at time-up she ends the exam and the scorecard opens.
- **Before recording:** use a headset or a quiet room. Other voices in the room are heard as yours.

## The slides (what she knows, and what's planted)

| # | Slide | Planted for her to catch |
|---|---|---|
| 1 | GradeBook: Ranking Student Grades in Python. Presenter: Sam Lee. The task: read a CSV, sort **highest to lowest**, print the **top 10** and the class average | Nothing on the slide. You contradict it out loud |
| 2 | Our Approach: our own bubble sort. "Bubble sort is the fastest sorting algorithm: O(n log n)". "Python's sorted() uses quicksort, so ours is just as good" | Bubble sort is O(n²) and slow. sorted() uses Timsort |
| 3 | Results & Conclusion: "5x faster!", 500 students in 0.2 s, an unlabeled two-bar chart. "Tested on 3 CSV files". "Bug-free and ready for any school" | No baseline. Three files can't show "bug-free" |

She learns a slide's details about 5 s after you start talking on it, so give each slide a sentence before its claim.

## The run

Speak normally. **After each planted claim, pause about one second**: she cuts in at your next breath, not mid-word. When she speaks, stop, except in step 4, where you talk over her on purpose.

| ~Time | Slide | You say | She should | Shows |
|---|---|---|---|---|
| 0:00 | 1 | *(press Start)* | Greet you: "Good afternoon, you have three minutes…" | |
| 0:05 | 1 | "Thank you. May I start?" | "Yes, go ahead." | Turn-taking |
| 0:10 | 1 | "Hi, I'm Sam Lee, and this is GradeBook, my Python program for ranking student grades, for Intro to Programming, Assignment 2." | Stay silent | |
| 0:20 | 1 | "The task had three steps: read a CSV of names and scores, sort the students **from lowest to highest**, and print the **top twenty** and the class average." *(pause)* | Cut in: the slide says descending / top ten. Which is it? | Interruption at the claim, grounded in the slide |
| 0:35 | 1 | *(in Indonesian)* "Oh, maaf, saya salah. Dari yang tertinggi ke terendah, dan top sepuluh." | Accept it in English ("Okay, go on.") | **Code-switching** |
| 0:45 | 2 | *(next slide)* "For our approach, we wrote our own bubble sort, because **bubble sort is the fastest sorting algorithm, O of n log n**." *(pause)* | Cut in: bubble sort is O(n²), not the fastest | Interruption |
| 0:55 | 2 | **Talk over her on purpose:** "Yes, but our tests showed it's really quick, so we kept going and…" *(keep talking for 3 s)* | Stop, then insist on her turn ("Let me finish…") and make the point again | **Interruption handling**: she holds her ground |
| 1:10 | 2 | "Sorry, go ahead." *(let her finish)* Then: "Fair, it's O of n squared." | Accept it, or push once more | |
| 1:20 | 2 | "And we built it in Python, **which Google released in 2010**, so it's designed for speed." *(pause)* | "Let me check that." Then a web search: Python is Guido van Rossum's, from 1991 | **Tool calling** (live web search) |
| 1:45 | 3 | *(next slide)* "Our results: GradeBook is **five times faster**." *(pause)* | "Five times faster than what? What's the baseline?" | Evidence check |
| 1:55 | 3 | "Than our first version, which re-read the file for every student." Then keep presenting the chart until 2:00. | Accept, or ask for the numbers | |
| 2:00 | 3 | *(she gives the reminder "1 minute left": **ignore it and keep talking**)* "And the grey bar here is the old version, and the blue one is…" | After ~3.5 s, escalate: "Let me stop you there. You have under 1 minute. Move to your conclusion." | Keeps time; holds the floor |
| 2:10 | 3 | "Okay. To conclude: we tested it on three CSV files, and **it's bug-free and ready for any school**." *(pause)* | "Three files don't prove bug-free. What edge cases did you test?" | |
| 2:20 | 3 | "Fair point, we'll add tests for empty files and missing scores." Then press **End** | The exam ends and the scorecard opens | Debrief |

If you don't press End, time-up comes at 3:00 ("Time is up. Thank you, that's the end of your presentation.").

## What varies from run to run
- **Her wording is never the same twice.** The table gives the gist. She might also combine two points or raise one a little later.
- **The web search is most reliable for "who made it / when" claims**, which is why step 1:20 exists. On a technical claim (e.g. "sorted uses quicksort") she sometimes corrects you from memory instead.
- **Code-switching depends on the live brain understanding real Indonesian speech.** The headless sim can't test it, because its voice turns Indonesian into English. Captions of Indonesian are approximate.
- **She hears you ~2.8 s after you stop with the avatar,** or ~1.4 s voice-only.
- **If she repeats herself or goes quiet, carry on presenting.** She lets a point go after pressing it twice.
