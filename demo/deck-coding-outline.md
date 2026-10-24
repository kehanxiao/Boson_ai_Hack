# Demo deck 2: "GradeBook" (`demo/deck-coding.pdf`)

An easy, 6-slide intro-programming assignment, so anyone watching the demo can follow every catch without domain knowledge. **This is the demo-video deck.** Scenario: **Assignment oral**, examiner: **The Supervisor**, 4:00 + 1:30 Q&A.

- Built-in session **`gradebook`**: `cd agent && uv run main.py gradebook`, then open http://localhost:5173/session/gradebook. No upload needed.
- Files: the deck comes from `server/scripts/make_coding_deck.py`; the cached Haiku analysis is `demo/prepped-analysis-coding.json`; `demo/session-config-coding.json` comes from `server/scripts/make_gradebook_session.py`.
The **planted weaknesses** are deliberate. Don't fix them.

| # | Title | Content | Planted weakness (examiner target) |
|---|---|---|---|
| 1 | GradeBook: Ranking Student Grades in Python | Intro to Programming, Assignment 2. Presenter: Sam Lee. | none |
| 2 | The Task | Read a CSV of names and scores, sort highest to lowest, print the top 10 and the class average. | none (sets context) |
| 3 | Our Approach | "Bubble sort is the fastest sorting algorithm: O(n log n)." "Python's built-in sorted() uses quicksort, so ours is just as good." | **Wrong complexity.** Bubble sort is O(n²). **Factual error for the web fact-check.** `sorted()` uses Timsort, not quicksort |
| 4 | The Code | About 20 lines of Python in small monospace. | **Unreadable slide**, which invites "which lines matter?" **Real bugs:** a header row crashes `int(score)`, and an empty file divides by zero in the average |
| 5 | Results | Big text: **"5x faster!"** "Sorted 500 students in 0.2 seconds." Bar chart with no labels. | **No baseline.** "5x faster than *what*?" The chart has no axes |
| 6 | Testing & Conclusion | "Tested on 3 CSV files: all worked." "The program is bug-free." "Ready for any school to use." | **Overclaim.** Three happy-path files; no edge cases |

## Presenter run-sheet for the demo
Timed against the agent's rules: no interruptions in the first 20 s, at most one per slide, 30 s between interjections (Supervisor), fact-checks need 10 s since the last interjection, and the Supervisor only interrupts for **major** issues. The T−2:00 reminder fires **2:00 into the talk**.

| Clock | Slide | What to do | What should happen |
|---|---|---|---|
| 0:00–0:30 | 1–2 | Introduce yourself and the task. Take the full 30 s. | Nothing (interruptions are off for the first 20 s). |
| ~0:35 | 3 | **Cold open.** Say confidently: "We wrote our own bubble sort. It's the fastest sorting algorithm, O(n log n)." Keep going. | She cuts in at your next breath: "Bubble sort is O(n squared). Why call it the fastest?" Answer briefly: "Right, it's n squared. We picked it because it was easy to write." |
| ~1:00 | 3 | Wait **at least 10 s** after she finishes, then read: "Python's built-in sorted() uses quicksort, so ours is just as good." **Pause** and let her work. | "Let me check that." Web search, then the correction: Timsort. |
| ~1:30 | 4 | Move to the code slide **early** and walk through it slowly, line by line. | Nothing yet. |
| 2:00 | 4 | **Ignore the reminder:** keep talking ("…so this inner loop compares every pair of neighbours…"). | "Two minutes left." Then she escalates and holds the floor: "Let me stop you there." Then say "Okay, moving on." |
| ~2:20 | 5 | Say "five times faster" and move on quickly. | Possibly "Faster than what?" If not, it comes back in Q&A. |
| ~3:00–4:00 | 6 | "Tested on 3 files, bug-free, ready for any school." Wrap up by 4:00. | The overclaim is usually saved for Q&A. |
| Q&A (1:30) | 6 | When asked about edge cases (empty file, header row), answer partly in Indonesian ("Jujur saja, kami belum tes file kosong…") or Mandarin ("我们没有测试空文件…"), then finish in English. | She follows and continues in English. |

- Every catch works on general knowledge, so it also works with a non-technical audience.
- If the cold open doesn't trigger, the usual cause is starting slide 3 before 0:20, or speaking straight through without a breath after the claim.
