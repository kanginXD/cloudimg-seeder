# CLI output

Where cloudimg-seeder's output goes, and how guest serial specifically is
presented and recorded.

## stdout and stderr

Everything cloudimg-seeder itself prints goes to stderr. stdout carries only
the resulting disk path, so `OUT=$(cloudimg-seeder disk.img user-data.yml)`
captures exactly that path.

On stderr, three kinds of output appear:

- **Step messages** (`▸ output: /path/to/seeded.qcow2`) — cloudimg-seeder's
  own narration of what it is doing.
- **Progress bars** — shown while converting the disk image.
- **Guest serial** — the booted guest's console output, framed by
  `──── guest serial ────` / `──── end guest serial ────` so it is never
  mistaken for cloudimg-seeder's own lines.

`-q`/`--quiet` silences all three, leaving only errors and the result path.
`--no-serial` hides guest serial only, keeping steps and progress.

## Guest serial console

Whether the guest's own color and style escapes (SGR — `ESC[...m`) reach the
console depends on whether the console is ANSI-capable: a real terminal, not
redirected, with `NO_COLOR` unset and `TERM` not `dumb`. On an ANSI-capable
console, SGR sequences are kept and every other escape sequence is removed.
On any other console, all escape sequences are removed, SGR included.

Escape sequences that query the terminal (for example Device Status Report,
`ESC[6n`) are always removed, regardless of ANSI capability, so the host
terminal never emits a reply into the guest's serial channel.

## `--serial-log`

Independent of what the console shows, `--serial-log PATH` writes guest
serial to a file. `--serial-log-format` selects how:

- `plain` (default) — an interpreted rendering. Carriage returns, backspace,
  tabs, and line-editing escape sequences (erase-line, cursor movement) are
  applied as a terminal would apply them, so a line the guest repeatedly
  overwrites (a percent counter, a spinner) appears in the file only as its
  final state, one line per newline.
- `raw` — the unmodified stream, escape sequences and carriage returns
  included, exactly as the guest sent it.

## Recognized sequences

Sequences are recognized in both their 7-bit form (`ESC` followed by `[`,
`]`, or one of `P X ^ _`) and their 8-bit C1 form (a single codepoint in
`U+0090`–`U+009F`). CSI sequences terminate on their final byte; OSC
terminates on BEL or ST (`ESC \`); DCS, SOS, PM, and APC terminate on ST.
CSI parameters may include a colon, so ISO 8613-6 truecolor SGR
(`ESC[38:2::255:0:0m`) is recognized as SGR.

CAN (`0x18`) and SUB (`0x1A`) abort a sequence in progress; a fresh `ESC`
also abandons whatever sequence was open and starts a new one. A sequence
that runs longer than 4096 characters without terminating is abandoned and
parsing resumes from the next character, bounding how much guest output a
malformed or unterminated sequence can hide.

## Completion detection

Completion is detected from cloud-init's default `final_message` on the
guest serial console. If user-data overrides `final_message`, completion
falls back to `--timeout-sec`: the guest is powered down once the timeout
elapses, whether or not cloud-init has actually finished.
