"""Generate the pre-start countdown audio into static/audio/.

    python scripts/gen_audio.py [--voice "Microsoft Zira Desktop"] [--rate 0]

A development-time script, like gen_marks.py and gen_lines.py: it runs on a laptop with
a TTS engine and ffmpeg, and commits its output. The Pi has neither and needs neither,
because it serves finished files (CLAUDE.md: vendor every dependency).

What it makes (DESIGN 10):

    min-10.m4a .. min-2.m4a   "Ten minutes" down to "Two minutes"
    min-1.m4a                 "One minute", singular, because that is English
    final.m4a                 one recording: "ten" .. "one" on the second, then the horn
    manifest.json             what was said, in which voice, and where the horn lands

The final ten seconds are one file rather than ten, because ten separately scheduled
clips can drift apart and this way the gap between "one" and the gun is fixed at the
moment it is built. The horn is at exactly HORN_AT seconds into it, which is the number
static/app.js schedules against; a test asserts the two still agree.

Voices are whatever Windows has. There is no en-AU voice on this machine, so it is an
American one saying numbers, which is not worth minding. To use another, pass --voice;
to hear the choices, --list. Replacing these files with real recordings of a human is
also fine, and is why the manifest records durations: keep the numbers on the second and
the horn at HORN_AT, and nothing else needs to change.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "static" / "audio"

# The horn lands here, in seconds from the start of final.m4a. static/app.js schedules the
# file so that this instant coincides with T-0, so it is a contract between the two.
HORN_AT = 10.0

# One number a second, counting down to the gun.
COUNTDOWN = ["ten", "nine", "eight", "seven", "six", "five", "four", "three", "two", "one"]

MINUTES = {
    10: "Ten minutes", 9: "Nine minutes", 8: "Eight minutes", 7: "Seven minutes",
    6: "Six minutes", 5: "Five minutes", 4: "Four minutes", 3: "Three minutes",
    2: "Two minutes", 1: "One minute",
}

DEFAULT_VOICE = "Microsoft Zira Desktop"

# A spoken number has to finish inside its second or it talks over the next one.
MAX_NUMBER_S = 0.95

# Mono AAC in an MP4 container, the same reasoning as wake.mp4: it is what iOS will play
# without argument. 64k mono is plainly enough for one voice and keeps the whole set small
# enough to sit in git without comment.
ENCODE = ["-c:a", "aac", "-b:a", "64k", "-ac", "1", "-ar", "44100", "-movflags", "+faststart"]

WINGET_FFMPEG = (Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet"
                 / "Packages" / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe")


def find_tool(name: str) -> str:
    """ffmpeg and ffprobe, from the PATH or from where winget puts them."""
    found = shutil.which(name)
    if found:
        return found
    override = os.environ.get(name.upper())
    if override and Path(override).exists():
        return override
    for candidate in sorted(WINGET_FFMPEG.rglob(name + ".exe")):
        return str(candidate)
    raise SystemExit(
        "%s not found. Install it (winget install Gyan.FFmpeg) or set %s to its path."
        % (name, name.upper()))


def run(args: list) -> None:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit("%s failed:\n%s" % (Path(args[0]).name, result.stderr[-2000:]))


def powershell(script: str) -> str:
    """Run a PowerShell snippet from a file, rather than fight quoting on the command line."""
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as handle:
        handle.write(script)
        path = handle.name
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", path],
            capture_output=True, text=True)
        if result.returncode != 0:
            raise SystemExit("powershell failed:\n%s" % result.stderr[-2000:])
        return result.stdout
    finally:
        os.unlink(path)


def list_voices() -> None:
    print(powershell(
        "Add-Type -AssemblyName System.Speech\n"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
        "$s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }\n"
        "$s.Dispose()\n").strip())


def speak(phrases: dict, voice: str, rate: int, into: Path) -> None:
    """Synthesise every phrase to a WAV in one PowerShell session.

    One session for the lot: starting the synthesiser is the slow part, and a single
    voice and rate across the set is the point.
    """
    lines = ["Add-Type -AssemblyName System.Speech",
             "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer",
             "$s.SelectVoice(%s)" % ps_quote(voice),
             "$s.Rate = %d" % rate]
    for name, text in sorted(phrases.items()):
        lines.append("$s.SetOutputToWaveFile(%s)" % ps_quote(str(into / (name + ".wav"))))
        lines.append("$s.Speak(%s)" % ps_quote(text))
    lines += ["$s.SetOutputToNull()", "$s.Dispose()"]
    powershell("\n".join(lines) + "\n")
    missing = [n for n in phrases if not (into / (n + ".wav")).exists()]
    if missing:
        raise SystemExit("the synthesiser produced nothing for: %s" % ", ".join(sorted(missing)))


def ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def trim(ffmpeg: str, source: Path, target: Path) -> None:
    """Cut the silence off both ends of a synthesised clip.

    The synthesiser pads what it produces: "ten" is about four tenths of a second of
    speech inside a one-and-a-third second file. Placed on the second untrimmed, the
    padding is what lands on the beat and the word arrives late.

    Trim the head, reverse, trim the head again, reverse back. Two passes of the same
    filter is the reliable way to get both ends, because silenceremove only ever works
    forwards.
    """
    cut = ("silenceremove=start_periods=1:start_duration=0:start_threshold=-45dB"
           ":detection=peak")
    run([ffmpeg, "-y", "-i", str(source),
         "-af", "%s,areverse,%s,areverse" % (cut, cut),
         "-ac", "1", "-ar", "44100", str(target)])


def normalise(ffmpeg: str, source: Path, target: Path, peak_db: float = -3.0) -> float:
    """Bring a clip's peak to peak_db, so one minute is not louder than the next.

    Straight off the synthesiser the phrases land anywhere over about five decibels,
    which is plainly audible when they arrive a minute apart. Peak rather than loudness
    normalisation because these are half-second clips and the loudness filters want
    several seconds before they mean anything.

    The horn is deliberately left out of this: it is meant to be louder than the voice.
    """
    detect = subprocess.run(
        [ffmpeg, "-i", str(source), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True)
    found = re.search(r"max_volume:\s*(-?[\d.]+) dB", detect.stderr)
    if not found:
        raise SystemExit("could not measure the level of %s" % source.name)
    gain = peak_db - float(found.group(1))
    run([ffmpeg, "-y", "-i", str(source), "-af", "volume=%.2fdB" % gain,
         "-ac", "1", "-ar", "44100", str(target)])
    return gain


def duration(ffprobe: str, path: Path) -> float:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit("ffprobe failed on %s:\n%s" % (path, result.stderr[-500:]))
    return float(result.stdout.strip())


def make_horn(ffmpeg: str, path: Path, seconds: float = 1.8) -> None:
    """A start-gun blast, synthesised rather than sampled: nothing to licence.

    A horn is a fundamental with strong harmonics rather than a pure tone, which is what
    makes a sine wave sound like a test signal and this sound like a horn. Two cents of
    detune on the octave stops it ringing too cleanly, and the envelope is a fast attack
    with a slow release, which is the shape of something with a diaphragm in it.
    """
    voice = ("0.55*sin(2*PI*210*t)"
             "+0.32*sin(2*PI*420.6*t)"
             "+0.18*sin(2*PI*630*t)"
             "+0.09*sin(2*PI*840*t)")
    run([ffmpeg, "-y", "-f", "lavfi", "-i",
         "aevalsrc=%s:d=%.3f:s=44100" % (voice, seconds),
         "-af", "afade=t=in:st=0:d=0.012,afade=t=out:st=%.3f:d=%.3f,alimiter=limit=0.95"
                % (seconds * 0.45, seconds * 0.55),
         "-ac", "1", str(path)])


def build_final(ffmpeg: str, ffprobe: str, work: Path, out: Path) -> dict:
    """Lay the ten numbers on the second, then the horn at HORN_AT.

    adelay places each piece at an exact offset and amix sums them. normalize=0 because
    the pieces do not overlap: normalised, every clip would come out a tenth of its
    volume for no reason.
    """
    pieces = []
    for index, word in enumerate(COUNTDOWN):
        path = work / ("n-%s.wav" % word)
        spoken = duration(ffprobe, path)
        if spoken > MAX_NUMBER_S:
            raise SystemExit(
                '"%s" takes %.2f s, which runs into the next second. Try a higher --rate.'
                % (word, spoken))
        pieces.append((path, float(index), spoken))
    horn = work / "horn.wav"
    pieces.append((horn, HORN_AT, duration(ffprobe, horn)))

    args = [ffmpeg, "-y"]
    for path, _, _ in pieces:
        args += ["-i", str(path)]
    delays = "".join("[%d]adelay=%d:all=1[d%d];" % (i, round(at * 1000), i)
                     for i, (_, at, _) in enumerate(pieces))
    mix = "".join("[d%d]" % i for i in range(len(pieces)))
    args += ["-filter_complex",
             delays + "%samix=inputs=%d:normalize=0[out]" % (mix, len(pieces)),
             "-map", "[out]"] + ENCODE + [str(out)]
    run(args)
    return {word: {"at": float(i), "seconds": round(pieces[i][2], 3)}
            for i, word in enumerate(COUNTDOWN)}


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--rate", type=int, default=0, help="SAPI rate, -10 to 10")
    parser.add_argument("--list", action="store_true", help="list the installed voices and stop")
    args = parser.parse_args(argv)

    if args.list:
        list_voices()
        return 0

    ffmpeg, ffprobe = find_tool("ffmpeg"), find_tool("ffprobe")
    OUT.mkdir(parents=True, exist_ok=True)

    phrases = {"m-%d" % n: text for n, text in MINUTES.items()}
    phrases.update({"n-%s" % word: word for word in COUNTDOWN})

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        print("speaking %d phrases as %s at rate %d" % (len(phrases), args.voice, args.rate))
        speak(phrases, args.voice, args.rate, work)
        for name in phrases:
            trim(ffmpeg, work / (name + ".wav"), work / (name + "-cut.wav"))
            normalise(ffmpeg, work / (name + "-cut.wav"), work / (name + "-lvl.wav"))
            (work / (name + "-lvl.wav")).replace(work / (name + ".wav"))
        make_horn(ffmpeg, work / "horn.wav")

        minutes = {}
        for n in sorted(MINUTES):
            target = OUT / ("min-%d.m4a" % n)
            run([ffmpeg, "-y", "-i", str(work / ("m-%d.wav" % n))] + ENCODE + [str(target)])
            minutes[n] = {"say": MINUTES[n], "seconds": round(duration(ffprobe, target), 3)}
            print("  min-%-2d %-14s %5.2f s" % (n, MINUTES[n], minutes[n]["seconds"]))

        final = OUT / "final.m4a"
        numbers = build_final(ffmpeg, ffprobe, work, final)
        total = duration(ffprobe, final)
        print("  final  %-14s %5.2f s, horn at %.1f s" % ("ten .. one", total, HORN_AT))

    manifest = {
        "note": ("Generated by scripts/gen_audio.py. The horn in final.m4a is at horn_at "
                 "seconds, which static/app.js lines up with T-0 (DESIGN 10)."),
        "voice": args.voice,
        "rate": args.rate,
        "horn_at": HORN_AT,
        "final_seconds": round(total, 3),
        "minutes": minutes,
        "countdown": numbers,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("wrote %d files to %s" % (len(minutes) + 2, OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
