---
layout: post
title: "Rooting a Dreame L40 Ultra from an Apple Silicon Mac, no Linux box required"
categories: tech
tags: [dreame, valetudo, dustbuilder, fastboot, iot, robot-vacuum, macos, reverse-engineering, hardware, uart]
comments: True
---

The [official Valetudo guide](https://valetudo.cloud/pages/installation/dreame/) for rooting a Dreame robot over dustbuilder's FEL image assumes Linux: LiveSuit for the initial samples, Google `fastboot` for the flash itself. I only had an Apple Silicon Mac, and both of those tools either don't exist for macOS or silently fail on it. So I rebuilt the host side from scratch, kept the guide's actual flashing sequence untouched, and spent three days finding out exactly which parts of "just run fastboot" don't survive contact with macOS and a real eMMC.

<!-- readmore -->

## Why the guide doesn't just work on a Mac

| The guide uses | Problem on macOS | What I used instead |
|---|---|---|
| LiveSuit / `sunxi-fel` on Linux | LiveSuit doesn't exist for macOS | `sunxi-fel` built from source, pinned to Debian's version |
| Google `fastboot` | The FEL payload's USB gadget is `bDeviceClass 0xff`; macOS won't configure it, so `fastboot devices` shows nothing. Forcing configuration 1 lets small commands through, but a 400 MB upload stalls at zero bytes | a small libusb fastboot client I wrote, checked byte-for-byte against Google's own fastboot with a differential test against a fake robot |
| `fastboot flash` splitting big images | — | the same libsparse calls fastboot makes, built from Debian's source |

I also tried a Raspberry Pi 1 as a fallback Linux host before giving up on that route entirely: Debian's current `fastboot` is built for ARMv7 and dies with `SIGILL` on the Pi 1's ARMv6, and an older Raspbian build that does run buffers the whole 400 MB upload in RAM — the Pi only has ~430 MB — so it hung and rebooted mid-transfer.

The FEL window itself is short and starts at the button press, not at the first command: the robot's own MCU cuts power after roughly 210 seconds, leaving 160–180 seconds of usable session. `getvar config` has to be the first command every single time, or the payload just answers `FAIL you need to run "fastboot getvar config" first`.

## The samples are your backup, not just an entry ticket

Stage 1 — reading `config` plus three ~400 MB samples off the robot — ran in 61 seconds at 13 MB/s, and those went to dustbuilder to build the actual flashing job. Following [Max Ammann's write-up on the FEL payload](https://maxammann.org/posts/2025/06/dreame-fel-mode/), I decrypted those samples and found they're the first ~1.2 GB of the eMMC, XOR'd against a key derived from a fixed seed: both bootloader copies, the env, both firmware slots, and the calibration partitions. That decrypted copy is what let me make every later decision safely, because I always had a byte-exact pristine reference to diff against.

## The DDR mismatch, and the flash that stopped at boot1

The job zip's `fsbl.bin` turned out to be byte-identical to the stage-1 sample's DDR3 variant. Running `flash.sh probe` against the stage-1 DDR4 fsbl alone and reading back from SRAM showed the SoC falls back to its header default — DDR4 at 792 MHz — which meant the DDR3-default `fsbl.bin` would have set up the wrong timings on DDR4 memory. Dustbuilder itself confirmed it later by publishing a DDR4-specific image for this SoC, and the payload's own U-Boot prints `DRAM: 512 MiB` after training, where the how-to assumes 1 GB. `FSBL=ddr4` fixed it.

Two no-write rehearsals passed clean, downloads to RAM only, read back and compared against the images. Then the real flash stopped dead at `boot1`: `getvar config`, `oem dust`, and `oem prep` all came back `OKAY`, `toc1` flashed fine, and `boot1` accepted the download and then failed bare about six seconds later, with no further explanation over USB.

A read-only post-mortem showed the `boot1` write had actually never landed — it was still byte-identical to factory. But `oem prep` had already rewritten the boot env to point at slot 1, which is the actual rooting step, and the toc1 backup copy had been overwritten. Everything else, including slot 2, was untouched. I got two things wrong reading that result at the time: I assumed the robot "no longer boots" because the next power-on landed in FEL — it landed there because I was holding the boot-select button, not because anything broke — and I called the boot1 failure "deterministic" after a single attempt, when it turned out to be an intermittent eMMC problem I wouldn't understand until day three.

## Wiring a UART turned bare FAILs into actual answers

An FT232RL at 3.3V on the breakout PCB's SoC header needs no soldering: TX→RX, RX→TX, GND→GND, and never VCC. My first capture was garbage because macOS resets a serial port to 9600 baud on last close, so running `stty` and then `cat` as two separate commands captured at the wrong speed. Reading and setting the speed on the same open descriptor fixed that.

With the UART attached, a retry got past `boot1` — the exact step that failed before — and then `rootfs1` stopped after two pieces with a real error on the console: an eMMC multi-block write timeout (`mmc 2 data timeout`, `cmd 25 STO`, `mmc write failed`). After that the card refused reads too, so nothing else worked in that session, not even `getvar config`. Over plain USB, the identical failure had just looked like a generic timeout — there was no way to tell the two apart without the serial log.

I tried stripping HS400/HS200/DDR modes from the payload's device tree, since the payload has no checksum protecting it, on the theory that the fast eMMC modes were the problem. It booted fine and tuned to HS400 anyway — in FEL mode the eMMC tuning walks its own list regardless of what the device tree claims. What actually worked was simpler: fewer megabytes per session. The timeout showed up consistently around 80–100 MB of writes, but a power cycle reset it cleanly. So I wrote `rootfs1` in pieces across separate FEL sessions — three pieces, then a fresh session for the fourth — verified every slot against the images, and left `rootfs2` deliberately stock as a fallback. The reboot after that showed a root login on the serial console, something stock firmware never has.

## Valetudo, and the mistake that almost leaked my Wi-Fi password

Since the Mac can only join one Wi-Fi network at a time, I downloaded the Valetudo binary and verified it against the release manifest before switching to the robot's own AP. From there, one script backed up the private partitions, copied the binary over, checked its sha256 on the robot itself, and enabled the postboot hook. Valetudo came up recognizing the model and its camera stream immediately.

The last mistake was almost a bad one. Joining the robot to home Wi-Fi from the root shell, I ran `stty -echo` before piping in the credentials — and busybox's `stty` segfaulted, killing the shell outright. The login that respawned right after echoed the *next* line, the base64'd SSID and password, straight into the UART log. I scrubbed the log immediately, and switched to `read -s`, which this busybox handles without issue. Lesson: test anything that touches a secret with a dummy value first, especially on an unfamiliar shell.

## What's public now

Everything — the scripts, the tests, the diary of what didn't work — is on GitHub: [`dreame-l40-ultra-macos-root`](https://github.com/3h4x/dreame-l40-ultra-macos-root). The full day-by-day account is in [`JOURNEY.md`](https://github.com/3h4x/dreame-l40-ultra-macos-root/blob/main/JOURNEY.md); the actual step-by-step is the [README](https://github.com/3h4x/dreame-l40-ultra-macos-root/blob/main/README.md). If you're doing this on the same hardware: get a UART adapter before your first write, probe the fsbl before trusting it, and expect the eMMC to time out — write in smaller pieces and power-cycle when it does.

Know what you are doing and have fun!

3h4x

Sources:
- [Dreame → fastboot method — Valetudo installation guide](https://valetudo.cloud/pages/installation/dreame/)
- [dustbuilder — Dennis Giese](https://builder.dontvacuum.me)
- [Reverse engineering the Dreame FEL payload — Max Ammann](https://maxammann.org/posts/2025/06/dreame-fel-mode/)
- [Leo's notes on the Dreame L40 Ultra](https://leo.leung.xyz/wiki/Dreame_L40_Ultra)
- [linux-sunxi/sunxi-tools](https://github.com/linux-sunxi/sunxi-tools)
- [My own writeup and scripts — dreame-l40-ultra-macos-root](https://github.com/3h4x/dreame-l40-ultra-macos-root)
