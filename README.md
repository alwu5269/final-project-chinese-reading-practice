# 猫猫读 MaoMao Read

A cat-themed Chinese reading coach. Find an article or a story picked for your level, or bring your own text (any web page, a link or pasted text), read it out loud, and see exactly which characters you misread, read with the wrong tone, or skipped. Built for heritage speakers who speak Chinese at home but read it less well.

## How it works

The desktop app is one window: **a real web browser on the left, Coach Mao on the right.** You read directly on the web page: press **🐾 Read on this page**, click any paragraph, read it aloud, and your mistakes are colored right on the page (hover to see what Mao heard). Suggested articles open in the browser pane, ready to read. `static/page_reader.js` is injected into the page for this.

There are two ways to choose what to read:
- **✨ Find me something.** Pick a category (News, Kids' stories, Science & tech, Food & recipes, Culture & life, Sports, Encyclopedia) and your HSK level. Code reads the newest article links from each curated site in `sources.py` (its RSS feed, its "latest" list page, or Wikipedia's featured articles; see `feeds.py`), opens up to 12 of them, and measures each one's HSK level. The **Finder** agent (`gpt-6-luna`, no web search) then picks the best 4 from their titles, opening lines and measured levels, and says why each fits. This takes about 1–2k tokens per search, down from about 17k when the Finder ran its own web searches. Real articles are almost always HSK 3 or above (most measure HSK 5–6), so when every article is far above your level (usual at HSK 1–3), the **Writer** agent's story at your level leads the list. For HSK 1–3 the Writer gets the official HSK word list for that level, and code checks the result: a story that measures too hard goes back with the exact words to replace.
- **📖 I have my own.** Paste text, import a link, or browse in the desktop window's browser pane.

1. **Prepare.** The Leveler agent (`gpt-6-luna`) translates the passage. Its HSK level is measured by code (`levels.py`) against the official HSK 2.0 word list, not guessed by the AI; found articles are labeled and sorted by that measured level. Pinyin comes from the `pypinyin` library, not the AI.
2. **Read.** Your recording is transcribed by Whisper running locally on your computer (`faster-whisper`, model `small`). Audio never leaves the machine.
3. **Score.** `scoring.py` lines up the transcript with the text character by character, with no AI involved. Same sound counts as correct; same syllable with a different tone is a tone error; a different syllable is a misread; a missing character is skipped; text after where you stopped is "not read yet."
4. **Coach.** The Coach agent (`gpt-6-luna`) explains the flagged characters and writes practice sentences that reuse them.
5. **Tone check (no AI).** Speech-to-text auto-corrects tones, so the app also compares the *pitch shape* of each character with a native reading of the same passage: the native voice is lined up with your recording by dynamic time warping (DTW) on MFCC features, and Praat (`parselmouth`) measures both pitch contours. Only clear mismatches are flagged (e.g. rising where it should fall); hover a flagged character to see both contours. The native reading comes from the online neural voice, so without internet the tone check is skipped and everything else still works. See `tones.py`.
6. **Hesitations.** Whisper's word timings show where you paused mid-phrase (not at punctuation); those characters get an orange marker.
7. **Tap for meaning.** Tap any character (in the panel or in the passage on the web page) to see the dictionary word around it, pinyin and meanings from the offline CC-CEDICT dictionary, hear it, or add it to your review deck. See `dictionary.py`.
8. **Progress.** Every checked reading is saved; **📈 Progress** shows accuracy and speed over time, your most-missed characters, recent readings, and a CSV export.
9. **Review deck.** Every tone error or misread is saved (in the reader's browser storage) with a short phrase around it. **Review deck** quizzes you by reading the phrase aloud, scored by the same code with no AI tokens used, then shows the word's meaning. Cards come back after 1, 3, 7 and 21 days (Leitner boxes).

Token usage for every agent call is appended to `output/usage_log.jsonl`.

## English mode (for graders)

Don't read Chinese? Click **English** in the top-right corner. Everything works the same way in English: find articles (BBC, NPR, Smithsonian, NASA, Science News Explores, BBC Good Food, Simple English Wikipedia, Wikipedia), paste your own text, read in the desktop browser pane, coaching, and the review deck. Scoring is per word instead of per character (no tones), the level is an AI estimate shown as CEFR (A1–C2), and instead of a translation you get a short summary in simple English. Try the **Tricky words** and **Safety test** samples under *I have my own → Try a sample*.

## Run it locally

Requires Python 3.11+ and a microphone. The first start downloads the Whisper speech model once (about 480 MB, in the background).

1. Clone the repo and enter the folder:
   ```bash
   git clone https://github.com/alwu5269/final-project-chinese-reading-practice.git && cd final-project-chinese-reading-practice
   ```
2. Put a `.env` file with your key either in this folder or **one level above it**. See `.env.example` for the key name (`PORTKEY_API_KEY`, or `OPENAI_API_KEY`).
3. Create a virtual environment and install dependencies:
   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
   On Windows use `.venv\Scripts\pip` and `.venv\Scripts\python`.
4. Start the desktop app:
   ```bash
   .venv/bin/python desktop.py
   ```
   On macOS, allow microphone access for your terminal when asked. The coach opens at full width; the browser appears when you open an article or a site (or press **🌐 Browser**).

   The terminal may show lines like these. They are harmless and can be ignored:
   - `Error parsing certificate … Failed parsing extensions`: the built-in browser skips one certificate on your Mac it can't read; secure sites still load.
   - `MallocStackLogging: can't turn off malloc stack logging…`: macOS prints this when the app starts its helper processes for reading articles.
5. Pick a suggested article (or browse to any Chinese page and press **🐾 Read on this page**, or highlight some text and press **🐾 Read this**), click a paragraph, press **Start reading**, read it, and press **Stop and check** (or **↺ Start over** if you want to begin again).

Note: some networks (VPNs, campus DNS filters) block mainland-China websites. The curated sources were chosen to work internationally; links that don't open are skipped.

**Without the desktop window:** `.venv/bin/uvicorn app:app --port 8000` and open http://localhost:8000 in any browser; paste text or import an article by link. To test without a microphone, open "Type what you read instead". For a faster but less accurate speech model set `WHISPER_MODEL=base` in `.env`.

## Safety

- Scores are computed by code (`scoring.py`), so pasted text cannot convince the AI to report 100%.
- Passages are sent to the agents as JSON data, and the prompts tell the agents never to follow instructions inside them. Agents flag such text (`suspicious_instructions`) and the UI shows a warning.
- The provider's content filter blocks blatant jailbreak text; the app shows a clear message instead of crashing.
- The Finder never browses: it only chooses among links the app read from the curated sites, by id. Any id outside the list is ignored.
- Every link is downloaded and checked (allowed site, public address, real article text) before the Finder sees it.
- Article import only fetches public web addresses (localhost and private networks are blocked), with a size limit and timeout.
- Reading mode never follows links or runs page instructions; the page's text only goes to the agents as data. Only the coach pane gets the microphone; the browser pane's permission requests are denied.
- Recordings stay in server memory only (last 20) so tones can be checked; nothing is written to disk. Saved progress and the review deck live in the app's own browser storage (`output/browser-profile/`, git-ignored).
- Passages are limited to 600 characters, and each server session stops making AI calls after 500,000 tokens (restart the app to reset).
- Try the two "Safety test" samples to see these defenses work.

## Files

- `desktop.py`: the desktop window (browser + coach) and the bridge between them
- `static/page_reader.js`: in-page reading mode (passages and colored mistakes on the web page)
- `app.py`: FastAPI server and API routes
- `speech.py`: local Whisper transcription with word timings
- `tones.py`: pitch-based tone check (DTW alignment to a native reading) and pause detection
- `dictionary.py`: offline CC-CEDICT lookups for tap-for-meaning
- `levels.py` and `data/hsk_words.json`: measured HSK level (official HSK 2.0 word list, from drkameleon/complete-hsk-vocabulary, MIT licence)
- `fetcher.py`: article import and passage splitting
- `sources.py`: the curated news and story sites
- `voice.py`: natural Mandarin voice for "Hear it" (Microsoft Edge neural voice via `edge-tts`; sends only the text to be spoken)
- `feeds.py`: newest article links from each curated site (RSS, list page or Wikipedia), cached 15 minutes
- `agents.py`: Leveler, Coach, Finder and Writer agents, `.env` lookup, token logging and budget
- `scoring.py`: deterministic character alignment and stats
- `prompts/`: agent instructions (`prompts/en/` for English mode)
- `samples/samples.json`, `samples/samples_en.json`: practice passages and safety tests
- `static/index.html`: the whole front end
