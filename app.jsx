import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";

const CHINESE_CHARACTER = /^[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]$/;
const CHINESE_CHARACTERS = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/g;

function shuffle(items) {
  const result = [...items];
  for (let i = result.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [result[i], result[j]] = [result[j], result[i]];
  }
  return result;
}

function readBrowserCache(key, fallback) {
  try {
    const value = JSON.parse(window.localStorage.getItem(key) || "null");
    return value ?? fallback;
  } catch {
    return fallback;
  }
}

function getAiExampleAudio(example) {
  return `${example.example_word}。${example.example_sentence}`;
}

function TodayPanel({
  file,
  onFileChange,
  charactersText,
  onCharactersChange,
  onStart,
  isImporting,
  status,
}) {
  return (
    <>
      <h2>Today's sheet</h2>
      <p className="sub">Load a daily PDF or enter a few characters.</p>

      <div className="field">
        <label htmlFor="pdf">Choose a practice PDF</label>
        <input
          id="pdf"
          type="file"
          accept="application/pdf"
          onChange={onFileChange}
        />
      </div>

      <div className="or">OR PASTE CHARACTERS</div>

      <div className="field">
        <label htmlFor="chars">Character list</label>
        <textarea
          id="chars"
          value={charactersText}
          onChange={(event) => onCharactersChange(event.target.value)}
          placeholder={"Try: 山水火木人\nSpaces and punctuation are ignored."}
        />
      </div>

      <button className="wide" onClick={onStart} disabled={isImporting}>
        {isImporting ? "Importing…" : "Start practice"}
      </button>
      <div className="status" role="status">
        {status}
      </div>

      <div className="tip">
        <b>Auto audio:</b> the reader plays the character first, then its
        example word and short sentence. Their text stays hidden until you
        reveal the answer.
      </div>
      <p className="note">
        PDFs need selectable text. If a sheet is scanned, paste its characters
        into the box.
      </p>
      <p className="note">
        A PDF is sent temporarily to this service for text extraction and is not
        saved there. Examples and review characters are saved only in this browser.
      </p>
    </>
  );
}

function ReviewPanel({ characters, onRemove, onStart }) {
  return (
    <>
      <h2>Saved for review</h2>
      <p className="sub">Characters you marked as hard to remember.</p>
      <div className="review-count">
        {characters.length
          ? `${characters.length} ${characters.length === 1 ? "character" : "characters"} saved`
          : "No characters saved yet."}
      </div>

      <div className="review-list">
        {characters.length ? (
          characters.map((character) => (
            <span className="review-chip" key={character}>
              {character}
              <button
                type="button"
                title={`Remove ${character} from review`}
                onClick={() => onRemove(character)}
              >
                ×
              </button>
            </span>
          ))
        ) : (
          <div className="review-empty">
            During practice, tap “Save for review” on a character you want to
            revisit.
          </div>
        )}
      </div>

      <button className="wide" onClick={onStart} disabled={!characters.length}>
        Practice saved characters
      </button>
      <p className="note">Saved characters are kept in this browser and are not uploaded.</p>
    </>
  );
}

function PracticePanel({
  character,
  index,
  total,
  mode,
  revealed,
  example,
  aiStatus,
  reviewSaved,
  onListen,
  onReveal,
  onHide,
  onToggleReview,
  onPrevious,
  onNext,
  onSkip,
  canvasRef,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onClearCanvas,
}) {
  const complete = total > 0 && index >= total;
  const progress = complete ? 100 : total ? (index / total) * 100 : 0;

  return (
    <section className="card practice" aria-live="polite">
      <div className="practice-head">
        <span>
          {complete
            ? "Practice complete"
            : character
              ? `${mode === "review" ? "Review · " : ""}Character ${index + 1} of ${total}`
              : "Ready when you are"}
        </span>
        <span>{character ? `${total - index} left` : ""}</span>
      </div>

      <div className="progress">
        <div className="bar" style={{ width: `${progress}%` }} />
      </div>
      <div className="shortcut-hint">
        <kbd>R</kbd> reveal · <kbd>H</kbd> hide · <kbd>N</kbd> next ·{" "}
        <kbd>P</kbd> previous · <kbd>S</kbd> replay
      </div>

      <div className="prompt">
        <p className="cue">
          {complete
            ? "Nice work. Take a short break, then practice again."
            : character
              ? "Listen, then try writing from memory"
              : "Load a sheet to begin"}
        </p>
        <div className="character-row">
          <div className={`character${revealed || complete ? "" : " hidden"}`}>
            {complete ? "完成" : revealed ? character : ""}
          </div>
          {total > 0 && (
            <div className="character-nav" aria-label="Character navigation">
              <button
                type="button"
                className="secondary character-nav-button"
                aria-label="Previous character (up arrow)"
                title="Previous character (↑)"
                onClick={onPrevious}
                disabled={index === 0}
              >
                ↑
              </button>
              <button
                type="button"
                className="secondary character-nav-button"
                aria-label="Next character (down arrow)"
                title="Next character (↓)"
                onClick={onNext}
                disabled={!character}
              >
                ↓
              </button>
            </div>
          )}
        </div>
        <div className="example">
          {revealed && example
            ? `Meaning: ${example.meaning} (${example.pinyin})\nExample word: ${example.example_word}\n${example.example_sentence}\n${example.sentence_translation}`
            : ""}
        </div>
        <div className="ai-status">{aiStatus}</div>
      </div>

      <div className="actions">
        <button onClick={onListen} disabled={!character}>
          🔊 Hear character
        </button>
        <button className="secondary" onClick={onReveal} disabled={!character}>
          Reveal (R)
        </button>
        <button
          className="secondary"
          onClick={onHide}
          disabled={!character || !revealed}
        >
          Hide (H)
        </button>
        <button
          className={`save-btn${reviewSaved ? " saved" : ""}`}
          onClick={onToggleReview}
          disabled={!character}
        >
          {reviewSaved ? "✓ Saved for review" : "☆ Save for review"}
        </button>
      </div>

      <div className="writebox">
        <div className="writehead">
          <strong>Writing space</strong>
          <span>Use your mouse, trackpad or finger</span>
        </div>
        <canvas
          ref={canvasRef}
          width="900"
          height="430"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        />
        <div className="writebuttons">
          <button className="quiet" onClick={onClearCanvas}>
            Clear
          </button>
          <div className="rightbuttons">
            <button
              className="secondary"
              onClick={onPrevious}
              disabled={index === 0 || (!character && !complete)}
            >
              ← Previous (P)
            </button>
            <button
              className="secondary"
              onClick={onSkip}
              disabled={!character}
            >
              Skip
            </button>
            <button onClick={onNext} disabled={!character}>
              {index === total - 1 ? "Finish practice ✓" : "Next character →"}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}

function PracticeApp() {
  const [list, setList] = useState([]);
  const [index, setIndex] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [reviewCharacters, setReviewCharacters] = useState(() =>
    readBrowserCache("hanzi-practice-review-v1", []),
  );
  const [mode, setMode] = useState("today");
  const [aiExamples, setAiExamples] = useState(() =>
    readBrowserCache("hanzi-practice-examples-v1", {}),
  );
  const [status, setStatus] = useState("");
  const [aiStatus, setAiStatus] = useState("");
  const [voiceStatus, setVoiceStatus] = useState("Preparing reading voice…");
  const [aiVoiceEnabled, setAiVoiceEnabled] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [charactersText, setCharactersText] = useState("");
  const [selectedFile, setSelectedFile] = useState(null);
  const [sessionId, setSessionId] = useState(0);

  const canvasRef = useRef(null);
  const drawingRef = useRef(false);
  const exampleRequestsRef = useRef(new Map());
  const readingTokenRef = useRef(0);
  const currentAudioRef = useRef(null);
  const activeSpeakResolveRef = useRef(null);
  const requestControllerRef = useRef(null);
  const listRef = useRef(list);
  const indexRef = useRef(index);
  const examplesRef = useRef(aiExamples);
  const voiceEnabledRef = useRef(aiVoiceEnabled);

  listRef.current = list;
  indexRef.current = index;
  examplesRef.current = aiExamples;
  voiceEnabledRef.current = aiVoiceEnabled;

  const character = list[index] || "";
  const example = aiExamples[character] || null;
  const reviewSaved = reviewCharacters.includes(character);

  function stopReading() {
    readingTokenRef.current += 1;
    requestControllerRef.current?.abort();
    requestControllerRef.current = null;

    if (currentAudioRef.current) {
      const audio = currentAudioRef.current;
      audio.onended = null;
      audio.onerror = null;
      audio.pause();
      if (audio.src.startsWith("blob:")) URL.revokeObjectURL(audio.src);
      currentAudioRef.current = null;
    }

    if (activeSpeakResolveRef.current) {
      const finish = activeSpeakResolveRef.current;
      activeSpeakResolveRef.current = null;
      finish();
    }

    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    return readingTokenRef.current;
  }

  function speakPart(text, token) {
    if (!text || token !== readingTokenRef.current) return Promise.resolve();

    return new Promise((resolve) => {
      let finished = false;
      let audio = null;
      const timeout = setTimeout(finish, 18000);

      function finish() {
        if (finished) return;
        finished = true;
        clearTimeout(timeout);
        if (activeSpeakResolveRef.current === finish)
          activeSpeakResolveRef.current = null;
        if (currentAudioRef.current === audio) currentAudioRef.current = null;
        resolve();
      }

      activeSpeakResolveRef.current = finish;

      async function playWithAiVoice() {
        if (voiceEnabledRef.current) {
          try {
            const controller = new AbortController();
            requestControllerRef.current = controller;
            const abortTimer = setTimeout(() => controller.abort(), 8000);
            let response;

            try {
              response = await fetch("/api/speech", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text }),
                signal: controller.signal,
              });
            } finally {
              clearTimeout(abortTimer);
              if (requestControllerRef.current === controller)
                requestControllerRef.current = null;
            }

            if (token !== readingTokenRef.current) return finish();
            if (!response.ok) throw new Error("AI voice unavailable");

            const audioUrl = URL.createObjectURL(await response.blob());
            audio = new Audio(audioUrl);
            currentAudioRef.current = audio;
            audio.onended = () => {
              URL.revokeObjectURL(audioUrl);
              finish();
            };
            audio.onerror = () => {
              URL.revokeObjectURL(audioUrl);
              finish();
            };
            await audio.play();
            return;
          } catch {
            if (token !== readingTokenRef.current) return finish();
            setAiVoiceEnabled(false);
            setVoiceStatus("AI voice unavailable · using your device voice");
          }
        }

        if (token !== readingTokenRef.current) return finish();
        if (!("speechSynthesis" in window)) return finish();

        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = "zh-CN";
        utterance.rate = 0.88;
        utterance.pitch = 1.04;
        const voices = window.speechSynthesis.getVoices();
        utterance.voice =
          voices.find(
            (voice) =>
              /^zh(-|_)?CN/i.test(voice.lang) &&
              /(female|woman|xiaoxiao|ting.?ting|meijia|huihui|yaoyao|xiao.?chen)/i.test(
                voice.name,
              ),
          ) ||
          voices.find((voice) => /^zh(-|_)?CN/i.test(voice.lang)) ||
          voices.find((voice) => /^zh/i.test(voice.lang)) ||
          null;
        utterance.onend = finish;
        utterance.onerror = finish;
        window.speechSynthesis.speak(utterance);
      }

      playWithAiVoice();
    });
  }

  async function requestExample(characterToLoad) {
    if (examplesRef.current[characterToLoad])
      return examplesRef.current[characterToLoad];

    const requestKey = characterToLoad;
    if (exampleRequestsRef.current.has(requestKey))
      return exampleRequestsRef.current.get(requestKey);

    const request = (async () => {
      let lastError = "";

      for (let attempt = 0; attempt < 2; attempt += 1) {
        try {
          const response = await fetch("/api/ai-example", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ character: characterToLoad }),
          });
          const result = await response.json();
          if (!response.ok)
            throw new Error(result.error || "Could not prepare this example");
          const generatedExample = result.example || result;

          const updatedExamples = {
            ...examplesRef.current,
            [characterToLoad]: generatedExample,
          };
          examplesRef.current = updatedExamples;
          try {
            window.localStorage.setItem(
              "hanzi-practice-examples-v1",
              JSON.stringify(updatedExamples),
            );
          } catch {}
          setAiExamples((previous) => ({ ...previous, [characterToLoad]: generatedExample }));
          if (listRef.current[indexRef.current] === characterToLoad) {
            setAiStatus("AI example ready. Reveal to see it.");
            if (revealed) setRevealed(true);
          }
          return generatedExample;
        } catch (error) {
          lastError = error.message;
          if (attempt === 0)
            await new Promise((resolve) => setTimeout(resolve, 1000));
        }
      }

      if (
        listRef.current[indexRef.current] === characterToLoad
      ) {
        setAiStatus(
          `AI example will retry when you revisit this character. ${lastError}`,
        );
      }
      return null;
    })().finally(() => exampleRequestsRef.current.delete(requestKey));

    exampleRequestsRef.current.set(requestKey, request);
    return request;
  }

  async function prepareFirstExamples(characters) {
    const required = Math.min(5, characters.length);
    for (let position = 0; position < required; position += 1) {
      const nextCharacter = characters[position];
      setStatus(`Preparing examples before practice… ${position}/${required}`);
      const ready = await requestExample(nextCharacter);
      if (!ready) {
        throw new Error(
          `The example for ${nextCharacter} is not ready. Check the connection or AI service, then import the sheet again. Practice has not started.`,
        );
      }
      setStatus(`Preparing examples before practice… ${position + 1}/${required}`);
    }
  }

  function playPrompt(characterToRead) {
    const token = stopReading();
    const characterAudio = speakPart(characterToRead, token);
    const examplePromise = examplesRef.current[characterToRead]
      ? Promise.resolve(examplesRef.current[characterToRead])
      : requestExample(characterToRead);

    characterAudio
      .then(() => examplePromise)
      .then(async (generatedExample) => {
        if (
          token !== readingTokenRef.current ||
          listRef.current[indexRef.current] !== characterToRead
        )
          return;
        if (generatedExample)
          await speakPart(getAiExampleAudio(generatedExample), token);
      });
  }

  function startSession(characters, shuffleOrder = true) {
    const validCharacters = characters.filter((character) =>
      CHINESE_CHARACTER.test(character),
    );
    const sessionCharacters = shuffleOrder
      ? shuffle(validCharacters)
      : validCharacters;
    if (!sessionCharacters.length) {
      setStatus("No Chinese characters found.");
      return;
    }

    stopReading();
    setList(sessionCharacters);
    setIndex(0);
    setRevealed(false);
    setAiStatus("");
    setSessionId((id) => id + 1);
    setStatus(`${sessionCharacters.length} characters ready.`);
  }

  async function startToday() {
    setMode("today");

    if (!selectedFile) {
      startSession(charactersText.match(CHINESE_CHARACTERS) || []);
      return;
    }

    setIsImporting(true);
    setStatus("Importing the sheet…");

    try {
      const response = await fetch("/api/extract", {
        method: "POST",
        body: selectedFile,
      });
      const result = await response.json();
      if (!response.ok)
        throw new Error(result.error || "Could not read the PDF");

      const order = shuffle(result.characters);
      setCharactersText(result.characters.join(""));
      await prepareFirstExamples(order);
      startSession(order, false);
      setStatus("Practice started. Remaining examples will generate as each character comes up.");
    } catch (error) {
      setStatus(error.message);
    } finally {
      setIsImporting(false);
    }
  }

  function changeReview(characterToChange, action) {
    setReviewCharacters((previous) => action === "add"
      ? (previous.includes(characterToChange) ? previous : [...previous, characterToChange])
      : previous.filter((item) => item !== characterToChange));
  }

  async function startReview() {
    setMode("review");
    startSession(reviewCharacters);
  }

  function goTo(target) {
    if (target < 0 || target > list.length) return;
    stopReading();
    setIndex(target);
    setRevealed(false);
    setAiStatus("");
    clearCanvas();
  }

  function clearCanvas() {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
  }

  function handlePointerDown(event) {
    const canvas = canvasRef.current;
    const context = canvas.getContext("2d");
    const bounds = canvas.getBoundingClientRect();
    const x = (event.clientX - bounds.left) * (canvas.width / bounds.width);
    const y = (event.clientY - bounds.top) * (canvas.height / bounds.height);
    drawingRef.current = true;
    canvas.setPointerCapture(event.pointerId);
    context.beginPath();
    context.moveTo(x, y);
  }

  function handlePointerMove(event) {
    if (!drawingRef.current) return;
    const canvas = canvasRef.current;
    const context = canvas.getContext("2d");
    const bounds = canvas.getBoundingClientRect();
    const x = (event.clientX - bounds.left) * (canvas.width / bounds.width);
    const y = (event.clientY - bounds.top) * (canvas.height / bounds.height);
    context.lineWidth = 7;
    context.lineCap = "round";
    context.lineJoin = "round";
    context.strokeStyle = "#176c52";
    context.lineTo(x, y);
    context.stroke();
  }

  useEffect(() => {
    fetch("/api/tts-status")
      .then((response) => response.json())
      .then((result) => {
        setAiVoiceEnabled(Boolean(result.enabled));
        setVoiceStatus(
          result.enabled
            ? "Warm AI voice · repeated clips cached locally"
            : "Using the Chinese voice available on this device",
        );
      })
      .catch(() =>
        setVoiceStatus("Using the Chinese voice available on this device"),
      );
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem("hanzi-practice-review-v1", JSON.stringify(reviewCharacters));
    } catch {}
  }, [reviewCharacters]);

  useEffect(() => {
    try {
      window.localStorage.setItem("hanzi-practice-examples-v1", JSON.stringify(aiExamples));
    } catch {}
  }, [aiExamples]);

  useEffect(() => {
    if (!character) return undefined;
    setAiStatus(examplesRef.current[character]
      ? "AI example ready. Reveal to see it."
      : "AI example generating in the background…");
    playPrompt(character);
    return () => stopReading();
  }, [character, sessionId]);

  useEffect(() => {
    function handleKeyDown(event) {
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (
        event.target.closest(
          'input, textarea, select, button, [contenteditable="true"]',
        )
      )
        return;

      const key = event.key.toLowerCase();
      if (!listRef.current.length) return;
      if (key === "r" && listRef.current[indexRef.current]) setRevealed(true);
      if (key === "h" && listRef.current[indexRef.current]) setRevealed(false);
      if (key === "n") goTo(indexRef.current + 1);
      if (key === "p") goTo(indexRef.current - 1);
      if (key === "s" && listRef.current[indexRef.current])
        playPrompt(listRef.current[indexRef.current]);
      if (["r", "h", "n", "p", "s"].includes(key)) event.preventDefault();
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [revealed, list, index, sessionId]);

  const tab = mode === "today" ? "today" : "review";

  return (
    <main className="shell">
      <header className="top">
        <div className="brand">
          <div className="logo">字</div>
          <div>
            <h1>Character Practice</h1>
            <p>Listen · recall · write</p>
          </div>
        </div>
        <div className="local">● Your practice stays in this browser</div>
      </header>
      <div className="voice-status">{voiceStatus}</div>

      <div className="layout">
        <aside className="card sidebar">
          <div className="tabs">
            <button
              className={`tab${tab === "today" ? " active" : ""}`}
              aria-selected={tab === "today"}
              onClick={() => setMode("today")}
            >
              Today
            </button>
            <button
              className={`tab${tab === "review" ? " active" : ""}`}
              aria-selected={tab === "review"}
              onClick={() => {
                setMode("review");
              }}
            >
              Review{" "}
              {reviewCharacters.length ? `(${reviewCharacters.length})` : ""}
            </button>
          </div>

          {tab === "today" ? (
            <TodayPanel
              file={selectedFile}
              onFileChange={(event) =>
                setSelectedFile(event.target.files?.[0] || null)
              }
              charactersText={charactersText}
              onCharactersChange={setCharactersText}
              onStart={startToday}
              isImporting={isImporting}
              status={status}
            />
          ) : (
            <ReviewPanel
              characters={reviewCharacters}
              onRemove={(characterToRemove) =>
                changeReview(characterToRemove, "remove")
              }
              onStart={startReview}
            />
          )}
        </aside>

        <PracticePanel
          character={character}
          index={index}
          total={list.length}
          mode={mode}
          revealed={revealed}
          example={example}
          aiStatus={aiStatus}
          reviewSaved={reviewSaved}
          onListen={() => character && playPrompt(character)}
          onReveal={() => setRevealed(true)}
          onHide={() => setRevealed(false)}
          onToggleReview={() =>
            character && changeReview(character, reviewSaved ? "remove" : "add")
          }
          onPrevious={() => goTo(index - 1)}
          onNext={() => goTo(index + 1)}
          onSkip={() => goTo(index + 1)}
          canvasRef={canvasRef}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={() => {
            drawingRef.current = false;
          }}
          onClearCanvas={clearCanvas}
        />
      </div>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<PracticeApp />);
