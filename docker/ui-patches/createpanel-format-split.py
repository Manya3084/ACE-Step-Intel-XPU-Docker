#!/usr/bin/env python3
"""Split AI Format apply paths in CreatePanel.

Style Format:
  - Sends caption only (empty lyrics so LM does not rewrite words)
  - Applies result.caption + bpm/key/time/duration/language
  - Does NOT setLyrics

Lyrics Format:
  - Sends style as context + lyrics
  - Applies result.lyrics only
  - Does NOT setStyle or music meta
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MARKER = "[XPU-FORMAT-SPLIT]"

NEW_HANDLER = r'''
  // Format handler — [XPU-FORMAT-SPLIT] style vs lyrics apply separately
  const handleFormat = async (target: 'style' | 'lyrics') => {
    if (!token) return;
    if (target === 'style' && !style.trim()) return;
    if (target === 'lyrics' && !lyrics.trim()) return;
    if (target === 'style') {
      setIsFormattingStyle(true);
    } else {
      setIsFormattingLyrics(true);
    }
    try {
      // Style: do not send lyrics (LM would rewrite them).
      // Lyrics: send style as context only; never overwrite style on return.
      const result = await generateApi.formatInput({
        caption: style,
        lyrics: target === 'style' ? '' : lyrics,
        bpm: target === 'style' && bpm > 0 ? bpm : undefined,
        duration: target === 'style' && duration > 0 ? duration : undefined,
        keyScale: target === 'style' && keyScale ? keyScale : undefined,
        timeSignature: target === 'style' && timeSignature ? timeSignature : undefined,
        temperature: lmTemperature,
        topK: lmTopK > 0 ? lmTopK : undefined,
        topP: lmTopP,
        lmModel: lmModel || 'acestep-5Hz-lm-1.7B',
        lmBackend: lmBackend || 'pt',
      }, token);

      const hasPayload =
        result.caption || result.lyrics || result.bpm || result.duration || result.key_scale;
      if (!hasPayload && (result.error || result.status_message)) {
        console.error('Format failed:', result.error || result.status_message);
        alert(
          'Format failed: ' +
            (result.error || result.status_message || 'Make sure the LLM is initialized.')
        );
        return;
      }

      if (target === 'style') {
        if (result.caption) setStyle(result.caption);
        if (result.bpm && result.bpm > 0) setBpm(result.bpm);
        if (result.duration && result.duration > 0) setDuration(result.duration);
        if (result.key_scale) setKeyScale(result.key_scale);
        if (result.time_signature) {
          const ts = String(result.time_signature);
          setTimeSignature(ts.includes('/') ? ts : `${ts}/4`);
        }
        if (result.vocal_language) setVocalLanguage(result.vocal_language);
        setIsFormatCaption(true);
        // never setLyrics on style format
      } else {
        if (result.lyrics) setLyrics(result.lyrics);
        // never setStyle / bpm / key on lyrics format
      }
    } catch (err) {
      console.error('Format error:', err);
      alert('Format failed: ' + ((err as any)?.message || String(err)));
    } finally {
      if (target === 'style') {
        setIsFormattingStyle(false);
      } else {
        setIsFormattingLyrics(false);
      }
    }
  };
'''


def main() -> None:
    hits = [p for p in Path(".").rglob("CreatePanel.tsx") if "node_modules" not in str(p)]
    if not hits:
        print("CreatePanel.tsx not found", file=sys.stderr)
        sys.exit(1)
    path = hits[0]
    text = path.read_text()

    if MARKER in text:
        print("format-split already present")
        return

    # Replace entire handleFormat function
    pat = re.compile(
        r"  // Format handler[\s\S]*?const handleFormat = async \(target: 'style' \| 'lyrics'\) => \{[\s\S]*?\n  \};\n",
        re.M,
    )
    if not pat.search(text):
        # looser: from const handleFormat through its closing };
        pat = re.compile(
            r"  const handleFormat = async \(target: 'style' \| 'lyrics'\) => \{[\s\S]*?\n  \};\n",
            re.M,
        )

    if not pat.search(text):
        print("handleFormat not found", file=sys.stderr)
        sys.exit(1)

    text = pat.sub(NEW_HANDLER.strip() + "\n\n", text, count=1)
    path.write_text(text)
    print(f"OK format-split in {path}")


if __name__ == "__main__":
    main()
