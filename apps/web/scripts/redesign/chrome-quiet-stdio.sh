#!/bin/sh
# Real Google Chrome for the e2e suite, with stdout and stderr on /dev/null.
#
# Why: branded Chrome on macOS spawns helpers that outlive it outside its
# process group (chrome_crashpad_handler, and GoogleUpdater --wake-all some
# 20 s after launch), and they inherit its stdout and stderr. Playwright kills
# Chrome's process group on close and then waits for those two pipes to
# close, which they never do while the updater runs: browser.close() hangs,
# the worker never exits, and the run ends with "worker-N process did not
# exit within 300000ms after stop" and rc=1 although every test passed.
# With /dev/null the orphans hold nothing Playwright waits on. The DevTools
# pipe (fds 3 and 4) is untouched. The price is Chrome's own log lines under
# DEBUG=pw:browser.
exec "${ADELIA_REAL_CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}" "$@" \
  >/dev/null 2>&1
